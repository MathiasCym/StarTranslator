// One-use, encrypted upload grants let a maintainer transfer formal assets locally.
// The repository token stays in Actions; signed URLs never enter source or logs.
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict')
const {GitCodePublisher,uploadRecipe,uploadRequest,readBody}=require('../tools/publish-gitcode.cjs')
const {GitHubUpdates,candidate,fetchTrusted}=require('../lib/github-updates')
const {source}=require('../lib/distribution-sources')
const REPO='MathiasCym/StarTranslator',ROOT=path.resolve(__dirname,'..')
function request(value,now=Date.now()){
 assert.equal(value.schema,1);assert.equal(value.repository,REPO)
 assert(['prepare','finalize'].includes(value.phase));assert(/^\d+\.\d+\.\d+$/.test(value.version))
 assert(/^[a-f0-9]{32}$/.test(value.id));assert(/^[a-f0-9]{64}$/.test(value.sha256));assert(Number.isSafeInteger(value.size)&&value.size>256*1024)
 const expires=Date.parse(value.expires);assert(expires>now&&expires<now+3600000,'Expired upload request')
 const key=crypto.createPublicKey(value.public_key);assert.equal(key.asymmetricKeyType,'rsa');assert(key.asymmetricKeyDetails.modulusLength>=3072)
 return value
}
function seal(value,req){
 const key=crypto.randomBytes(32),iv=crypto.randomBytes(12),cipher=crypto.createCipheriv('aes-256-gcm',key,iv)
 cipher.setAAD(Buffer.from(req.id))
 const bytes=Buffer.concat([cipher.update(JSON.stringify(value),'utf8'),cipher.final()])
 return {schema:1,id:req.id,key:crypto.publicEncrypt({key:req.public_key,oaepHash:'sha256'},key).toString('base64'),iv:iv.toString('base64'),tag:cipher.getAuthTag().toString('base64'),data:bytes.toString('base64')}
}
function unseal(envelope,privateKey,req){
 request(req);assert.equal(envelope.schema,1);assert.equal(envelope.id,req.id)
 const key=crypto.privateDecrypt({key:privateKey,oaepHash:'sha256'},Buffer.from(envelope.key,'base64'))
 const cipher=crypto.createDecipheriv('aes-256-gcm',key,Buffer.from(envelope.iv,'base64'));cipher.setAAD(Buffer.from(req.id));cipher.setAuthTag(Buffer.from(envelope.tag,'base64'))
 const plan=JSON.parse(Buffer.concat([cipher.update(Buffer.from(envelope.data,'base64')),cipher.final()]).toString('utf8'))
 assert.equal(plan.id,req.id);assert.equal(plan.version,req.version);assert.equal(plan.sha256,req.sha256);assert.equal(plan.size,req.size)
 const expected=files({version:req.version,filename:'StarTranslator-Setup-'+req.version+'.exe',size:req.size,sha256:req.sha256})
 const allowed=expected.map(f=>f.name);assert(Array.isArray(plan.files)&&plan.files.length<=3)
 const names=new Set()
 for(const file of plan.files){assert(allowed.includes(file.name)&&!names.has(file.name));names.add(file.name);const canonical=expected.find(f=>f.name===file.name);assert.equal(file.size,canonical.size);assert.equal(file.sha256,canonical.sha256);uploadRecipe(file.recipe,'reserved-relay-validation-token')}
 return plan
}
async function formal(req){
 const engine=new GitHubUpdates({currentVersion:'0.0.0',userData:path.join(ROOT,'dist/qa/domestic-relay')})
 const release=await engine.release('v'+req.version),a=candidate(release,'0.0.0')
 assert(a&&a.version===req.version&&a.size===req.size&&a.sha256===req.sha256,'Formal release mismatch')
 return a
}
function files(a){
 const details={schema:1,version:a.version,platform:'win32',architecture:'x64',filename:a.filename,size:a.size,sha256:a.sha256}
 const small=[['update.json',Buffer.from(JSON.stringify(details,null,2)+'\n')],['SHA256SUMS.txt',Buffer.from(a.sha256+'  '+a.filename+'\n')]]
 return [{name:a.filename,size:a.size,sha256:a.sha256},...small.map(([name,bytes])=>({name,size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')}))]
}
async function checkFile(s,asset,file){
 const response=await fetchTrusted(fetch,s.assetUrl(asset.browser_download_url,'v'+file.version,file.name),{signal:AbortSignal.timeout(180000)},s.trusted)
 assert(response.ok,'Public attachment unavailable')
 const bytes=await readBody(response,file.size)
 assert.equal(bytes.length,file.size);assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),file.sha256)
}
async function remote(req){
 request(req);assert.equal(JSON.parse(await fs.readFile(path.join(ROOT,'package.json'))).version,req.version)
 const a=await formal(req),s=source('atomgit',REPO),publisher=new GitCodePublisher({source:s,token:process.env.GITCODE_TOKEN})
 const release=await publisher.call('GET','releases/tags/v'+req.version);assert(release,'Domestic prerelease missing')
 const expected=files(a),plan={id:req.id,version:req.version,size:req.size,sha256:req.sha256,files:[]}
 for(const file of expected){
  const matches=(release.assets||[]).filter(asset=>asset.name===file.name);assert(matches.length<=1,'Duplicate attachment')
  if(matches.length){await checkFile(s,matches[0],{...file,version:req.version});continue}
  assert.equal(req.phase,'prepare','Missing domestic attachment')
  assert.equal(release.release_status,'pre','Do not replace formal release assets')
  const recipe=uploadRecipe(await publisher.call('GET','releases/v'+req.version+'/upload_url?file_name='+encodeURIComponent(file.name)),process.env.GITCODE_TOKEN)
  plan.files.push({...file,recipe})
 }
 if(req.phase==='prepare'){
  const out=path.join(ROOT,'dist/qa/domestic-relay');await fs.mkdir(out,{recursive:true});await fs.writeFile(path.join(out,'grant.json'),JSON.stringify(seal(plan,req)))
  return {prepared:true,files:plan.files.map(f=>f.name),encrypted:true}
 }
 // All three public files have been read back and checked before promotion.
 await publisher.call('PATCH','releases/v'+req.version,{name:'星译官 v'+req.version,body:a.notes,release_status:'latest',prerelease:false})
 const final=await publisher.call('GET','releases/tags/v'+req.version)
 assert(final&&final.release_status!=='pre'&&!final.prerelease,'Formal status not confirmed')
 return {published:true,version:req.version,size:a.size,sha256:a.sha256}
}
async function local(req,envelopeFile,privateFile,assets){
 const plan=unseal(JSON.parse(await fs.readFile(envelopeFile)),await fs.readFile(privateFile),req)
 const result=[]
 for(const file of plan.files){
  const bytes=await fs.readFile(path.join(assets,file.name));assert.equal(bytes.length,file.size);assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),file.sha256)
  const recipe=uploadRecipe(file.recipe,'reserved-relay-validation-token')
  console.log(JSON.stringify({phase:'upload-start',file:file.name,bytes:bytes.length}))
  const response=await uploadRequest(recipe.url,{method:'PUT',headers:recipe.headers,body:bytes,signal:AbortSignal.timeout(240000),onProgress:event=>console.log(JSON.stringify({phase:event.phase,file:file.name,bytes:event.bytes}))})
  assert(response.ok,'Local direct upload failed')
  const body=await readBody(response,512*1024)
  if(body.length){let reply;try{reply=JSON.parse(body.toString())}catch{}if(reply)assert(!reply.error&&reply.success!==false&&(reply.code===undefined||[0,200,'0','200'].includes(reply.code)),'Attachment callback failed')}
  result.push({file:file.name,status:response.status,bytes:bytes.length})
 }
 return {uploaded:result,formalReleaseChanged:false}
}
if(require.main===module)(async()=>{
 const req=JSON.parse(await fs.readFile(path.join(__dirname,'domestic-upload-request.json')))
 const result=process.argv[2]==='local'?await local(req,...process.argv.slice(3)):await remote(req)
 console.log(JSON.stringify(result))
})().catch(()=>{console.error('Domestic relay did not complete; release remains unverified. No credentials were logged.');process.exitCode=1})
module.exports={request,seal,unseal,files}
