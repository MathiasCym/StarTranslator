// Remove only verified online-update cache files after the installed version
// has succeeded. Downloads chosen outside this application's cache are kept.
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto')
const {createReadStream}=require('node:fs')
function parts(value){const m=/^(\d+)\.(\d+)\.(\d+)$/.exec(value||'');return m&&m.slice(1).map(Number).every(n=>Number.isSafeInteger(n)&&n<=65535)?m.slice(1).map(Number):null}
function installed(target,current){const a=parts(target),b=parts(current);if(!a||!b)return false;for(let i=0;i<3;i++){if(a[i]!==b[i])return a[i]<b[i]}return true}
async function prepareCleanup({userData,currentVersion,installer}){
 const folder=path.join(path.resolve(userData),'updates'),readyFile=path.join(folder,'ready.json')
 try{
  const directory=await fs.lstat(folder),metadata=await fs.lstat(readyFile)
  if(!directory.isDirectory()||directory.isSymbolicLink()||!metadata.isFile()||metadata.isSymbolicLink()||metadata.size>16384)return null
  const readyBytes=await fs.readFile(readyFile),ready=JSON.parse(readyBytes.toString('utf8'))
  if(!installed(ready.version,currentVersion)||ready.filename!=='StarTranslator-Setup-'+ready.version+'.exe'||!/^[a-f0-9]{64}$/.test(ready.sha256||'')||!Number.isSafeInteger(ready.size)||ready.size<256*1024||ready.size>1024*1024*1024)return null
  const file=path.join(folder,ready.filename)
  if(installer&&path.resolve(installer).toLowerCase()!==file.toLowerCase())return null
  const info=await fs.lstat(file)
  if(!info.isFile()||info.isSymbolicLink()||info.size!==ready.size)return null
  const hash=crypto.createHash('sha256');for await(const chunk of createReadStream(file))hash.update(chunk)
  if(hash.digest('hex')!==ready.sha256)return null
  return {file,folder,readyFile,version:ready.version,size:ready.size,sha256:ready.sha256}
 }catch(error){if(['ENOENT','EACCES','EPERM'].includes(error.code)||error instanceof SyntaxError)return null;throw error}
}
async function removeReady(value){
 try{const ready=JSON.parse(await fs.readFile(value.readyFile,'utf8'));if(ready.filename===path.basename(value.file)&&ready.sha256===value.sha256&&ready.version===value.version)await fs.unlink(value.readyFile)}catch(error){if(!['ENOENT','EACCES','EPERM'].includes(error.code)&&!(error instanceof SyntaxError))throw error}
}
async function cleanupInstalledUpdate(options){
 const value=await prepareCleanup(options);if(!value)return {removed:false,deferred:false}
 if(options.verifyInstalled&&!(await options.verifyInstalled())?.complete)return {removed:false,deferred:false,unverified:true}
 try{await (options.unlink||fs.unlink)(value.file)}catch(error){if(['EACCES','EPERM','EBUSY'].includes(error.code))return {removed:false,deferred:true};if(error.code!=='ENOENT')throw error}
 await removeReady(value)
 return {removed:true,deferred:false,version:value.version}
}
module.exports={prepareCleanup,cleanupInstalledUpdate}
