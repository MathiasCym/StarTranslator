const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto')
const {request,seal,unseal,files}=require('../domestic-relay.cjs')
const {publicKey,privateKey}=crypto.generateKeyPairSync('rsa',{modulusLength:3072,publicKeyEncoding:{type:'spki',format:'pem'},privateKeyEncoding:{type:'pkcs8',format:'pem'}})
const req={schema:1,repository:'MathiasCym/StarTranslator',phase:'prepare',version:'2.0.9',id:'1'.repeat(32),sha256:'2'.repeat(64),size:1024*1024,expires:new Date(Date.now()+1800000).toISOString(),public_key:publicKey}
const meta=files({version:req.version,filename:'StarTranslator-Setup-'+req.version+'.exe',size:req.size,sha256:req.sha256}).find(f=>f.name==='update.json')
const plan={id:req.id,version:req.version,sha256:req.sha256,size:req.size,files:[{...meta,recipe:{url:'https://bucket.obs.cn-south-1.myhuaweicloud.com/asset',headers:{'Content-Type':'application/octet-stream'}}}]}
test('a one-use upload plan is encrypted for the local maintainer only',()=>{
 const envelope=seal(plan,req);assert(!JSON.stringify(envelope).includes('myhuaweicloud'))
 assert.deepEqual(unseal(envelope,privateKey,req),plan)
 const altered={...envelope,data:Buffer.alloc(Buffer.from(envelope.data,'base64').length,1).toString('base64')}
 assert.throws(()=>unseal(altered,privateKey,req));assert.throws(()=>unseal(envelope,publicKey,req))
})
test('expired, foreign or redirected grants cannot transfer files',()=>{
 assert.throws(()=>request({...req,expires:new Date(0).toISOString()}));assert.throws(()=>request({...req,repository:'other/repo'}))
 assert.throws(()=>unseal(seal({...plan,files:[{...plan.files[0],name:'../secret'}]},req),privateKey,req))
 assert.throws(()=>unseal(seal({...plan,files:[{...plan.files[0],recipe:{url:'https://unrelated.example/upload',headers:{}}}]},req),privateKey,req))
 assert.throws(()=>unseal(seal({...plan,files:[{...plan.files[0],sha256:'4'.repeat(64)}]},req),privateKey,req))
})
test('small attachment bytes exactly match the original release contract',()=>{
 const list=files({version:'2.0.9',filename:'StarTranslator-Setup-2.0.9.exe',sha256:req.sha256,size:req.size})
 assert.equal(list.length,3);assert.equal(list[0].size,req.size);assert.equal(list[2].size,97)
})
