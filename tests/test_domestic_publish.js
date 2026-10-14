const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto')
const {GitCodePublisher,uploadRecipe}=require('../tools/publish-gitcode.cjs'),{fromUrl}=require('../tools/configure-distribution.cjs'),{source}=require('../lib/distribution-sources')
const token='gitcode-synthetic-private',s=source('gitcode','synthetic/StarTranslator')
function fixture(provider='gitcode'){
 const s=source(provider,'synthetic/StarTranslator')
 const bytes=Buffer.alloc(256*1024,27);bytes.write('MZ');bytes.writeUInt32LE(128,60);bytes.set([80,69,0,0],128)
 const tag='v2.0.4',name='StarTranslator-Setup-2.0.4.exe',sha=crypto.createHash('sha256').update(bytes).digest('hex')
 const release={tag_name:tag,prerelease:false,body:'Verified release',assets:[{name,state:'uploaded',size:bytes.length,digest:'sha256:'+sha,browser_download_url:'https://github.com/MathiasCym/StarTranslator/releases/download/'+tag+'/'+name}]}
 const state={remote:null,files:new Map(),calls:[],failName:'',badMetadata:false}
 const fetcher=async(url,options={})=>{
  state.calls.push({url,options})
  if(url.startsWith(s.api)){
   if(options.method==='POST'){state.remote={tag_name:tag,release_status:'pre',prerelease:true,assets:[]};return Response.json(state.remote)}
   if(options.method==='PATCH'){assert.equal(options.redirect,'error');assert.equal(options.headers.Authorization,'Bearer '+token);assert(JSON.parse(options.body).name);state.remote.release_status='latest';state.remote.prerelease=false;return Response.json(state.remote)}
   if(url.includes('/upload_url?')){
    const filename=new URL(url).searchParams.get('file_name');return Response.json({url:'https://bucket.obs.cn-south-1.myhuaweicloud.com/'+filename,headers:{'Content-Type':'application/octet-stream','x-obs-acl':'public-read'}})
   }
   return state.remote?Response.json(state.remote):new Response(null,{status:404})
  }
  if(url.startsWith('https://bucket.obs.')){
   assert.equal(options.method,'PUT');assert.equal(options.redirect,'error');assert.equal(options.headers.Authorization,undefined)
   const filename=new URL(url).pathname.slice(1);if(filename===state.failName)return new Response(null,{status:413})
   state.files.set(filename,Buffer.from(options.body));state.remote.assets.push({name:filename,browser_download_url:s.web+'/releases/download/'+tag+'/'+filename});return new Response(null,{status:204})
  }
  assert.equal(options.headers?.Authorization,undefined)
  const filename=new URL(url).pathname.split('/').at(-1)
  let data=state.files.get(filename)
  if(filename==='update.json'&&state.badMetadata)data=Buffer.from(JSON.stringify({...JSON.parse(data.toString()),sha256:'a'.repeat(64)}))
  return data?new Response(data):new Response(null,{status:404})
 }
 return {bytes,release,state,publisher:new GitCodePublisher({source:s,token,fetcher}),args:{release,bytes,userData:'unused-synthetic-path'}}
}
test('configuration accepts repository links but refuses credentials and unrelated hosts',()=>{
 assert.deepEqual(fromUrl('https://gitcode.com/synthetic/StarTranslator'),{schema:1,mirrors:[{provider:'gitcode',repository:'synthetic/StarTranslator'}]})
 assert.deepEqual(fromUrl('https://atomgit.com/synthetic/StarTranslator'),{schema:1,mirrors:[{provider:'atomgit',repository:'synthetic/StarTranslator'}]})
 for(const url of ['http://gitcode.com/a/b','https://token@gitcode.com/a/b','https://gitcode.com/a/b?access_token=secret','https://unknown.example/a/b','https://gitcode.com/a/b/c'])assert.throws(()=>fromUrl(url))
})
test('GitHub tokens cannot accidentally become domestic publishing credentials',()=>{
 for(const value of ['', 'github_pat_synthetic_123','ghp_synthetic_123','has whitespace'])assert.throws(()=>new GitCodePublisher({source:s,token:value}),/GitCode/)
})
test('upload recipes cannot forward the personal token, follow redirects or upload to arbitrary servers',()=>{
 const safe={url:'https://bucket.obs.cn-south-1.myhuaweicloud.com/file',headers:{'Content-Type':'application/octet-stream'}}
 assert.equal(uploadRecipe(safe,token).url,safe.url)
 for(const change of [{url:'http://bucket.obs.cn-south-1.myhuaweicloud.com/file'},{url:'https://evil.example/file'},{url:safe.url+'?token='+token},{headers:{Authorization:'Bearer '+token}},{headers:{'PRIVATE-TOKEN':token}}])assert.throws(()=>uploadRecipe({...safe,...change},token))
})

test('the official AtomGit upload gateway is accepted without broadening subdomain trust',()=>{
 const recipe={url:'https://file.gitcode.com/synthetic-signed-object',headers:{'x-obs-meta-project-id':'synthetic','x-obs-acl':'public-read','x-obs-callback':'synthetic','Content-Type':'application/octet-stream'}}
 assert.equal(uploadRecipe(recipe,token).url,recipe.url)
 for(const url of ['https://evil.file.gitcode.com/object','https://file.gitcode.com.evil.example/object','http://file.gitcode.com/object','https://file.gitcode.com/object?access_token='+token])assert.throws(()=>uploadRecipe({...recipe,url},token))
})
test('publishing keeps a release private to the update list until every asset is anonymously verified',async()=>{
 const f=fixture(),result=await f.publisher.publish(f.args)
 assert.equal(result.published,true);assert.equal(f.state.remote.release_status,'latest');assert.equal(f.state.files.size,3)
 const lastUpload=f.state.calls.findLastIndex(c=>c.options.method==='PUT'),promote=f.state.calls.findIndex(c=>c.options.method==='PATCH')
 assert(lastUpload<promote);assert(f.state.calls.slice(lastUpload+1,promote).some(c=>c.url.endsWith('.exe')&&!c.options.headers?.Authorization))
 assert(f.state.calls.filter(c=>c.options.method==='PUT').at(-1).url.endsWith('/update.json'))
})
test('an upload limit error leaves the original release and stable mirrors unchanged',async()=>{
 const f=fixture();f.state.failName='update.json';await assert.rejects(f.publisher.publish(f.args),/限额/)
 assert.equal(f.state.remote.release_status,'pre');assert(!f.state.calls.some(c=>c.options.method==='PATCH'))
 f.state.failName='';await f.publisher.publish(f.args);assert.equal(f.state.files.size,3)
})
test('a metadata mismatch is rejected before promoting a release',async()=>{
 const f=fixture();f.state.badMetadata=true;await assert.rejects(f.publisher.publish(f.args),/原发行包不同/)
 assert.equal(f.state.remote.release_status,'pre');assert(!f.state.calls.some(c=>c.options.method==='PATCH'))
})
test('published matching releases are retained without uploading or downloading the installer again',async()=>{
 const f=fixture();await f.publisher.publish(f.args);f.state.calls=[]
 const result=await f.publisher.publish({...f.args,bytes:undefined});assert.equal(result.retained,true)
 assert(!f.state.calls.some(c=>['PUT','POST','PATCH','DELETE'].includes(c.options.method)));assert(!f.state.calls.some(c=>c.url.endsWith('.exe')))
})
test('a differing published release is never overwritten',async()=>{
 const f=fixture();await f.publisher.publish(f.args);f.state.calls=[];f.state.badMetadata=true
 await assert.rejects(f.publisher.publish(f.args),/正式发行版内容不同/)
 assert(!f.state.calls.some(c=>['PUT','POST','PATCH','DELETE'].includes(c.options.method)))
})
test('mirror payload must match the exact original published installer bytes',async()=>{
 const f=fixture(),different=Buffer.from(f.bytes);different[200]^=1
 await assert.rejects(f.publisher.publish({...f.args,bytes:different}),/逐字节/);assert.equal(f.state.remote,null)
})
test('AtomGit publishing uses its own API and anonymous attachment origin',async()=>{
 const f=fixture('atomgit');assert.equal((await f.publisher.publish(f.args)).published,true)
 assert(f.state.calls.filter(c=>c.options.headers?.Authorization==='Bearer '+token).every(c=>c.url.startsWith('https://api.atomgit.com/')))
 assert(f.state.calls.some(c=>c.url.startsWith('https://atomgit.com/')&&c.url.endsWith('.exe')))
})
test('the AtomGit current-user request never sends a credential to the legacy API',async()=>{
 const api=source('atomgit','synthetic/StarTranslator'),calls=[]
 const p=new GitCodePublisher({source:api,token,fetcher:async(url,options)=>{calls.push({url,options});return Response.json({login:'synthetic'})}})
 assert.equal((await p.call('GET','user')).login,'synthetic');assert.equal(calls[0].url,'https://api.atomgit.com/api/v5/user');assert.equal(calls[0].options.redirect,'error')
})
