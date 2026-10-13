// Run in GitHub Actions with its repository-scoped token; never ship that token.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto')
const root=path.resolve(__dirname,'..'),pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'))),repository=process.env.GITHUB_REPOSITORY||'MathiasCym/StarTranslator',token=process.env.GITHUB_TOKEN
if(!token)throw Error('GitHub Actions publishing token is required')
const tag='v'+pkg.version,api='https://api.github.com/repos/'+repository
async function call(method,url,body,headers={}){const response=await fetch(url,{method,headers:{Accept:'application/vnd.github+json',Authorization:'Bearer '+token,'X-GitHub-Api-Version':'2022-11-28',...headers},body:body===undefined?undefined:Buffer.isBuffer(body)?body:JSON.stringify(body)});if(response.status===404)return null;if(!response.ok)throw Error('GitHub publishing failed: HTTP '+response.status);return response.status===204?null:response.json()}
;(async()=>{
 const existing=await call('GET',api+'/releases/tags/'+tag)
 if(existing&&!existing.draft){console.log('Version already published; existing assets retained.');return}
 const match=fs.readFileSync(path.join(root,'CHANGELOG.md'),'utf8').match(new RegExp('## \\['+pkg.version.replaceAll('.','\\.')+'\\] - [^\\n]+\\n([\\s\\S]*?)(?=\\n## |$)'))
 const release=existing||await call('POST',api+'/releases',{tag_name:tag,target_commitish:process.env.GITHUB_SHA,name:'星译官 '+tag,body:match?.[1].trim()||'',draft:true,prerelease:false},{'Content-Type':'application/json'})
 const installer=fs.readFileSync(path.join(root,'dist/星译官 Setup '+pkg.version+'.exe'))
 const name='StarTranslator-Setup-'+pkg.version+'.exe',sha=crypto.createHash('sha256').update(installer).digest('hex')
 const metadata={schema:1,version:pkg.version,platform:'win32',architecture:'x64',filename:name,size:installer.length,sha256:sha}
 const files=[[name,installer],['update.json',Buffer.from(JSON.stringify(metadata,null,2)+'\n')],['SHA256SUMS.txt',Buffer.from(sha+'  '+name+'\n')]]
 for(const [filename,bytes] of files){
  const old=(release.assets||[]).find(a=>a.name===filename)
  if(old)await call('DELETE',api+'/releases/assets/'+old.id)
  const asset=await call('POST',release.upload_url.split('{')[0]+'?name='+encodeURIComponent(filename),bytes,{'Content-Type':'application/octet-stream','Content-Length':String(bytes.length)})
  if(asset.size!==bytes.length||filename===name&&asset.digest!=='sha256:'+sha)throw Error('Uploaded release asset verification failed')
 }
 await call('PATCH',api+'/releases/'+release.id,{draft:false,make_latest:'true'},{'Content-Type':'application/json'})
 console.log(JSON.stringify({published:true,version:pkg.version,url:'https://github.com/'+repository+'/releases/tag/'+tag,size:installer.length,sha256:sha}))
})().catch(error=>{console.error(error.message);process.exitCode=1})
