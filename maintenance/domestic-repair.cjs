// Maintainer-only recovery. Never rebuild an already published installer.
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),{spawn}=require('node:child_process')
const {GitCodePublisher,readBody,uploadRecipe}=require('../tools/publish-gitcode.cjs')
const {GitHubUpdates,candidate,fetchTrusted}=require('../lib/github-updates')
const {GITHUB,mirrors}=require('../lib/distribution-sources')
const REPO='MathiasCym/StarTranslator'
function configValue(value){
 if(typeof value!=='string'||/[\r\n\0]/.test(value))throw Error('Invalid upload configuration')
 return '"'+value.replaceAll('\\','\\\\').replaceAll('"','\\"')+'"'
}
function curlConfig(url,headers){
 // Validate the signed destination and header names with the existing policy.
 const recipe=uploadRecipe({url,headers},'reserved-validation-token')
 return ['url = '+configValue(recipe.url),...Object.entries(recipe.headers).map(([key,value])=>'header = '+configValue(key+': '+value))].join('\n')+'\n'
}
async function curlUpload(url,options,spawnProcess=spawn){
 const configuration=curlConfig(url,options.headers)
 const folder=await fs.mkdtemp(path.join(os.tmpdir(),'star-domestic-curl-'))
 const payload=path.join(folder,'payload.bin'),responseFile=path.join(folder,'response.bin')
 try{
  await fs.writeFile(payload,options.body)
  const args=['--silent','--show-error','--http1.1','--proto','=https','--request','PUT','--connect-timeout','20','--max-time','180','--retry','0','--config','-','--upload-file',payload,'--output',responseFile,'--write-out','%{http_code}']
  const status=await new Promise((resolve,reject)=>{
   let output='',settled=false
   const child=spawnProcess('curl.exe',args,{windowsHide:true,stdio:['pipe','pipe','pipe'],timeout:200000})
   const finish=(error,value)=>{if(settled)return;settled=true;options.signal?.removeEventListener('abort',abort);error?reject(error):resolve(value)}
   const abort=()=>{child.kill();finish(Error('备用上传已取消。'))}
   child.stdout.on('data',value=>{if(output.length<1024)output+=value.toString()})
   // curl errors may contain signed URLs. Capture neither them nor private headers in logs.
   child.stderr.on('data',()=>{})
   child.on('error',()=>finish(Error('备用上传工具未能启动。')))
   child.on('close',code=>{
    if(code!==0)return finish(Error('备用上传未完成（curl '+(Number.isInteger(code)?code:'terminated')+'）。'))
    if(!/^\d{3}$/.test(output.trim()))return finish(Error('备用上传响应状态无效。'))
    finish(null,Number(output.trim()))
   })
   child.stdin.on('error',()=>finish(Error('备用上传配置未能传入。')))
   if(options.signal?.aborted)return abort()
   options.signal?.addEventListener('abort',abort,{once:true})
   child.stdin.end(configuration)
  })
  if(status<200||status>599)throw Error('备用上传响应状态无效。')
  const info=await fs.stat(responseFile);if(info.size>512*1024)throw Error('备用上传响应过大。')
  const bytes=await fs.readFile(responseFile)
  if(status>=200&&status<300)options.onProgress?.({phase:'upload-sent',bytes:options.body.length,transport:'curl-http1'})
  return new Response([204,205,304].includes(status)?null:bytes,{status})
 }finally{
  await Promise.all([payload,responseFile].map(file=>fs.unlink(file).catch(()=>{})))
  await fs.rmdir(folder).catch(()=>{})
 }
}
function staleUpload(run,jobs,releaseSha,currentRun){
 if(String(run.id)===String(currentRun)||run.head_sha!==releaseSha||run.status!=='in_progress')return false
 const build=jobs.find(job=>job.name==='windows')
 const upload=jobs.some(job=>['mirror','public-mirror / mirror'].includes(job.name)&&job.status==='in_progress')
 return upload&&((run.name==='Build and publish StarTranslator'&&build?.status==='completed'&&build.conclusion==='success')||run.name==='Sync owned public mirror')
}
async function stopStaleUploads(root=path.resolve(__dirname,'..'),fetcher=fetch,wait=ms=>new Promise(resolve=>setTimeout(resolve,ms))){
 const version=JSON.parse(await fs.readFile(path.join(root,'package.json'))).version
 if(!/^\d+\.\d+\.\d+$/.test(version)||!process.env.GITHUB_TOKEN)throw Error('Missing workflow authorization')
 const call=async(endpoint,method='GET')=>{
  const response=await fetcher('https://api.github.com/repos/'+REPO+'/'+endpoint,{method,redirect:'error',signal:AbortSignal.timeout(30000),headers:{Accept:'application/vnd.github+json',Authorization:'Bearer '+process.env.GITHUB_TOKEN}})
  if(!response.ok)throw Error('GitHub maintenance request failed (HTTP '+response.status+')')
  if(method!=='GET'||response.status===204){await response.body?.cancel();return null}
  return response.json()
 }
 const release=await call('releases/tags/v'+version)
 if(release.draft||release.prerelease||!/[a-f0-9]{40}/.test(release.target_commitish)||release.target_commitish.length!==40)throw Error('No immutable formal release to recover')
 const runs=await call('actions/runs?head_sha='+release.target_commitish+'&status=in_progress&per_page=30')
 const stopped=[]
 for(const run of runs.workflow_runs){
  const {jobs}=await call('actions/runs/'+run.id+'/jobs')
  if(!staleUpload(run,jobs,release.target_commitish,process.env.GITHUB_RUN_ID))continue
  await call('actions/runs/'+run.id+'/cancel','POST')
  let ended=false
  for(let attempt=0;attempt<18;attempt++){
   if((await call('actions/runs/'+run.id)).status==='completed'){ended=true;break}
   await wait(10000)
  }
  if(!ended)throw Error('Prior upload has not ended; recovery was not started')
  stopped.push(run.id)
 }
 return {version,stopped,formalReleaseUnchanged:true}
}
async function publish(root=path.resolve(__dirname,'..')){
 const version=JSON.parse(await fs.readFile(path.join(root,'package.json'))).version
 const source=mirrors(JSON.parse(await fs.readFile(path.join(root,'backend/distribution.json')))).find(s=>s.provider==='atomgit'&&s.repository===REPO)
 if(!source)throw Error('Owned domestic repository is not configured')
 const userData=path.join(root,'dist/qa/domestic-recovery')
 const engine=new GitHubUpdates({currentVersion:'0.0.0',userData})
 const release=await engine.release('v'+version),a=candidate(release,'0.0.0')
 if(!a||a.version!==version)throw Error('Formal release is not available')
 const publisher=new GitCodePublisher({source,token:process.env.GITCODE_TOKEN,uploader:curlUpload,onProgress:value=>console.log(JSON.stringify(value))})
 await publisher.syncGit(root,{tag:'v'+version})
 if(await publisher.retained(release,userData))return {version,retained:true}
 const response=await fetchTrusted(fetch,a.url,{signal:AbortSignal.timeout(10*60*1000)},GITHUB.trusted)
 if(!response.ok)throw Error('Original formal installer download failed')
 const bytes=await readBody(response,a.size)
 return publisher.publish({release,bytes,userData})
}
if(require.main===module){
 const action=process.argv[2]
 ;(action==='stop'?stopStaleUploads():action==='publish'?publish():Promise.reject(Error('Choose stop or publish')))
  .then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error.message);process.exitCode=1})
}
module.exports={curlConfig,curlUpload,staleUpload,stopStaleUploads}
