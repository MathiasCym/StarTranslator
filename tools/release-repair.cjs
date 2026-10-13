const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto')
function repairPlan(release,version,policies){
 if(!release)return null
 const policy=policies.find(p=>p.version===version&&p.releaseId===release.id)
 const asset=release.assets.find(a=>a.name==='StarTranslator-Setup-'+version+'.exe')
 return policy&&asset?.digest===policy.previousDigest?policy:null
}
async function preserveRelease(release,directory,fetcher=fetch){
 fs.mkdirSync(directory,{recursive:true})
 const allowed=new Set(['StarTranslator-Setup-2.0.0.exe','update.json','SHA256SUMS.txt'])
 for(const asset of release.assets){
  if(!allowed.has(asset.name)||asset.browser_download_url!=='https://github.com/MathiasCym/StarTranslator/releases/download/v2.0.0/'+asset.name||!/^sha256:[a-f0-9]{64}$/.test(asset.digest)||!Number.isSafeInteger(asset.size)||asset.size<1||asset.size>1024*1024*1024)throw Error('Previous release backup metadata is invalid')
  const response=await fetcher(asset.browser_download_url,{credentials:'omit'});if(!response.ok)throw Error('Previous release backup download failed')
  const chunks=[];let count=0
  for await(const value of response.body){count+=value.length;if(count>asset.size)throw Error('Previous release backup exceeds recorded size');chunks.push(Buffer.from(value))}
  const bytes=Buffer.concat(chunks)
  if(count!==asset.size||'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex')!==asset.digest)throw Error('Previous release backup verification failed')
  fs.writeFileSync(path.join(directory,asset.name),bytes)
 }
 for(const name of allowed)if(!release.assets.some(a=>a.name===name))throw Error('Previous release backup is incomplete')
 fs.writeFileSync(path.join(directory,'release.json'),JSON.stringify(release,null,2))
}
module.exports={repairPlan,preserveRelease}
