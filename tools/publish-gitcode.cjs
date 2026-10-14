// Run only in a trusted maintainer workflow. Tokens stay in Actions Secrets.
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),{execFileSync}=require('node:child_process')
const {mirrors,GITHUB,manifest}=require('../lib/distribution-sources'),{GitHubUpdates,candidate,fetchTrusted}=require('../lib/github-updates')
async function readBody(response,max=2*1024*1024){
 if(!response.body)return Buffer.alloc(0)
 const chunks=[];let size=0;const reader=response.body.getReader()
 try{for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>max)throw Error('发布服务返回的内容过大。');chunks.push(Buffer.from(value))}}
 finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
 return Buffer.concat(chunks)
}
function uploadRecipe(value,token){
 let url;try{url=new URL(value?.url)}catch{throw Error('发行附件上传地址无效。')}
 const allowed=['file-cdn.gitcode.com','file-cdn.atomgit.com'].includes(url.hostname)||/^[a-z0-9-]+\.obs\.[a-z0-9-]+\.myhuaweicloud\.com$/.test(url.hostname)
 if(url.protocol!=='https:'||!allowed||url.username||url.password||url.port||url.href.includes(token))throw Error('发行附件上传地址无效。')
 if(!value.headers||typeof value.headers!=='object'||Array.isArray(value.headers))throw Error('发行附件上传信息无效。')
 for(const [key,header] of Object.entries(value.headers)){
  if(!/^(content-type|content-md5|authorization|x-obs-[a-z0-9-]+)$/i.test(key)||typeof header!=='string'||header.includes('\r')||header.includes('\n')||header.includes(token))throw Error('发行附件上传信息无效。')
 }
 return {url:url.href,headers:value.headers}
}
class GitCodePublisher{
 constructor({source,token,fetcher=globalThis.fetch}){
  if(!['atomgit','gitcode'].includes(source.provider)||!token||/\s/.test(token)||token.length>1024||/^(github_pat_|ghp_)/.test(token))throw Error('请在 GITCODE_TOKEN 中配置 AtomGit / GitCode 的访问令牌，不能使用 GitHub 令牌。')
  this.source=source;this.token=token;this.fetcher=fetcher
 }
 async call(method,endpoint,body){
  // Credentialed requests never follow redirects, including same-platform ones.
  const url=endpoint==='user'?new URL('/api/v5/user',this.source.api).href:this.source.api+endpoint
  const response=await this.fetcher(url,{method,redirect:'error',credentials:'omit',signal:AbortSignal.timeout(30000),headers:{Accept:'application/json',Authorization:'Bearer '+this.token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined})
  if(response.status===400&&method==='GET'&&/^releases\/tags\/v\d+\.\d+\.\d+$/.test(endpoint)){
   await response.body?.cancel();const list=await this.call('GET','releases?per_page=100&page=1&direction=desc')
   if(!Array.isArray(list))throw Error('国内发行版列表无法读取。')
   return list.find(release=>release.tag_name===endpoint.slice('releases/tags/'.length))||null
  }
  if(response.status===404)return null
  if(!response.ok)throw Error('GitCode 发布请求未完成（HTTP '+response.status+'），请检查令牌权限与平台配额。')
  const bytes=await readBody(response);try{return bytes.length?JSON.parse(bytes.toString('utf8')):null}catch{throw Error('GitCode 发布响应无法读取。')}
 }
 syncGit(root,{tag}={}){
  return this.call('GET','user').then(user=>{
   if(!/^[A-Za-z0-9_.-]+$/.test(user?.login||''))throw Error('无法确定 GitCode 发布账户。')
   const remote=this.source.web+'.git',env={...process.env,GIT_TERMINAL_PROMPT:'0',GIT_CONFIG_COUNT:'1',GIT_CONFIG_KEY_0:'http.'+remote+'.extraheader',GIT_CONFIG_VALUE_0:'Authorization: Basic '+Buffer.from(user.login+':'+this.token).toString('base64')}
   // No force pushes, no tokens in command arguments or remote configuration.
   try{
    execFileSync('git',['fetch','origin','main'],{cwd:root,windowsHide:true,stdio:'pipe'})
    execFileSync('git',['merge','--ff-only','origin/main'],{cwd:root,windowsHide:true,stdio:'pipe'})
    const refs=['HEAD:refs/heads/main']
    if(tag){execFileSync('git',['fetch','origin','refs/tags/'+tag+':refs/tags/'+tag],{cwd:root,windowsHide:true,stdio:'pipe'});refs.push('refs/tags/'+tag+':refs/tags/'+tag)}
    execFileSync('git',['-c','credential.helper=','push',remote,...refs],{cwd:root,windowsHide:true,stdio:'pipe',env,timeout:10*60*1000})
   }catch{throw Error('国内仓库同步未完成。请使用空仓库或从 GitHub 导入的仓库；已有分支和标签不会被强制覆盖。')}
  })
 }
 async upload(tag,name,bytes){
  const recipe=uploadRecipe(await this.call('GET','releases/'+encodeURIComponent(tag)+'/upload_url?file_name='+encodeURIComponent(name)),this.token)
  const response=await this.fetcher(recipe.url,{method:'PUT',redirect:'error',credentials:'omit',signal:AbortSignal.timeout(10*60*1000),headers:recipe.headers,body:bytes})
  if(!response.ok)throw Error('国内发行附件上传未完成（HTTP '+response.status+'），请检查免费附件限额。')
  // OBS can report an unsuccessful attachment callback in an otherwise 200 body.
  const body=await readBody(response,512*1024)
  if(body.length){let result;try{result=JSON.parse(body.toString('utf8'))}catch{throw Error('国内附件上传结果无法确认。')}
   if(result.error||result.success===false||(result.code!==undefined&&![0,200,'0','200'].includes(result.code)))throw Error('国内附件登记未完成，请重新检查发行版。')}
 }
 async retained(release,userData){
  const a=candidate(release,'0.0.0'),tag='v'+a.version
  const existing=await this.call('GET','releases/tags/'+tag)
  if(!existing||existing.release_status==='pre')return false
  const engine=new GitHubUpdates({currentVersion:'0.0.0',userData,fetcher:this.fetcher,distribution:{schema:1,mirrors:[{provider:this.source.provider,repository:this.source.repository}]}})
  const remote=candidate(await engine.release(tag,this.source),'0.0.0',this.source)
  if(!remote||remote.sha256!==a.sha256||remote.size!==a.size)throw Error('国内已有正式发行版内容不同，未修改其文件。')
  return true
 }
 async publish({release,bytes,userData}){
  const a=candidate(release,'0.0.0'),tag='v'+a.version
  if(await this.retained(release,userData))return {retained:true,version:a.version}
  if(bytes.length!==a.size||crypto.createHash('sha256').update(bytes).digest('hex')!==a.sha256)throw Error('国内镜像必须与 GitHub 已发布的安装包逐字节一致。')
  const engine=new GitHubUpdates({currentVersion:'0.0.0',userData,fetcher:this.fetcher,distribution:{schema:1,mirrors:[{provider:this.source.provider,repository:this.source.repository}]}})
  const existing=await this.call('GET','releases/tags/'+tag)
  if(existing&&existing.release_status!=='pre')throw Error('国内发行版状态已变化，请重新核对。')
  if(!existing)await this.call('POST','releases',{tag_name:tag,name:'星译官 '+tag,body:a.notes,release_status:'pre'})
  const details={schema:1,version:a.version,platform:'win32',architecture:'x64',filename:a.filename,size:a.size,sha256:a.sha256}
  manifest(details,a.version,a.filename)
  // Verification metadata goes last. Incomplete releases remain prereleases.
  const files=[[a.filename,bytes],['SHA256SUMS.txt',Buffer.from(a.sha256+'  '+a.filename+'\n')],['update.json',Buffer.from(JSON.stringify(details,null,2)+'\n')]]
  for(const [name,content] of files){
   const old=existing?.assets?.find(asset=>asset.name===name)
   if(old){
    const response=await fetchTrusted(this.fetcher,this.source.assetUrl(old.browser_download_url,tag,name),{},this.source.trusted)
    if(!response.ok)throw Error('国内已有附件无法核对，未覆盖其内容。')
    const prior=await readBody(response,content.length)
    if(!prior.equals(content))throw Error('国内已有附件与原发行版不同，未覆盖其内容。')
   }else await this.upload(tag,name,content)
  }
  const ready=await this.call('GET','releases/tags/'+tag)
  if(!ready||!files.every(([name])=>(ready.assets||[]).filter(a=>a.name===name).length===1))throw Error('国内发行版附件登记不完整，保持预发布状态。')
  // Read back the installer anonymously before making it a stable update source.
  const publicUrl=this.source.assetUrl(ready.assets.find(x=>x.name===a.filename).browser_download_url,tag,a.filename)
  const response=await fetchTrusted(this.fetcher,publicUrl,{},this.source.trusted)
  if(!response.ok)throw Error('国内安装包尚不能匿名下载，保持预发布状态。')
  const actual=await readBody(response,a.size)
  if(actual.length!==a.size||crypto.createHash('sha256').update(actual).digest('hex')!==a.sha256)throw Error('国内安装包复核未通过，保持预发布状态。')
  const metaResponse=await fetchTrusted(this.fetcher,this.source.assetUrl(ready.assets.find(x=>x.name==='update.json').browser_download_url,tag,'update.json'),{},this.source.trusted)
  if(!metaResponse.ok)throw Error('国内更新信息尚不能匿名读取，保持预发布状态。')
  const checked=manifest(JSON.parse((await readBody(metaResponse)).toString('utf8')),a.version,a.filename)
  if(checked.sha256!==a.sha256||checked.size!==a.size)throw Error('国内更新信息与原发行包不同，保持预发布状态。')
  await this.call('PATCH','releases/'+encodeURIComponent(tag),{name:'星译官 '+tag,release_status:'latest',body:a.notes})
  const remote=candidate(await engine.release(tag,this.source),'0.0.0',this.source)
  if(!remote||remote.sha256!==a.sha256||remote.size!==a.size)throw Error('国内发行版的最终状态无法确认。')
  return {published:true,version:a.version,size:a.size,sha256:a.sha256}
 }
}
async function run(root=path.resolve(__dirname,'..')){
 const config=JSON.parse(await fs.readFile(path.join(root,'backend/distribution.json'),'utf8')),s=mirrors(config).find(s=>['atomgit','gitcode'].includes(s.provider))
 if(!s)return {skipped:true,reason:'国内公开仓库尚未配置。'}
 if(!process.env.GITCODE_TOKEN)return {skipped:true,reason:'GITCODE_TOKEN 尚未配置，原 GitHub 发布流程正常保留。'}
 const publisher=new GitCodePublisher({source:s,token:process.env.GITCODE_TOKEN}),pkg=JSON.parse(await fs.readFile(path.join(root,'package.json'),'utf8'))
 const engine=new GitHubUpdates({currentVersion:'0.0.0',userData:path.join(root,'dist/qa/domestic-publish')})
 const release=await engine.release('v'+pkg.version),a=candidate(release,'0.0.0')
 await publisher.syncGit(root,{tag:a?'v'+a.version:undefined})
 if(!a)return {synced:true,reason:'源码与词库已同步，此版本尚未在 GitHub 正式发布。'}
 if(await publisher.retained(release,path.join(root,'dist/qa/domestic-publish')))return {synced:true,retained:true,version:a.version}
 let bytes;try{bytes=await fs.readFile(path.join(root,'dist/星译官 Setup '+a.version+'.exe'))}catch{}
 if(!bytes||bytes.length!==a.size||crypto.createHash('sha256').update(bytes).digest('hex')!==a.sha256){
  const response=await fetchTrusted(globalThis.fetch,a.url,{signal:AbortSignal.timeout(10*60*1000)},GITHUB.trusted)
  if(!response.ok)throw Error('GitHub 原发行包无法读取，国内发行版保持不变。')
  bytes=await readBody(response,a.size)
 }
 return publisher.publish({release,bytes,userData:path.join(root,'dist/qa/domestic-publish')})
}
if(require.main===module)run().then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error.message);process.exitCode=1})
module.exports={GitCodePublisher,uploadRecipe,readBody,run}
