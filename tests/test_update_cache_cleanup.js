const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto')
const {prepareCleanup,cleanupInstalledUpdate}=require('../lib/update-cache-cleanup')
async function fixture(t){
 const root=await fs.mkdtemp(path.join(__dirname,'.update-clean-'));t.after(async()=>{assert.equal(path.dirname(root),__dirname);await fs.rm(root,{recursive:true,force:true})})
 const folder=path.join(root,'updates');await fs.mkdir(folder);const bytes=Buffer.alloc(256*1024,17),filename='StarTranslator-Setup-2.0.4.exe',file=path.join(folder,filename),readyFile=path.join(folder,'ready.json')
 const ready={filename,version:'2.0.4',size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')}
 await fs.writeFile(file,bytes);await fs.writeFile(readyFile,JSON.stringify(ready));await fs.writeFile(path.join(root,filename),'manual installer');await fs.writeFile(path.join(folder,'company.P2P.DOWNLOAD'),'unrelated')
 return {root,folder,file,readyFile,ready,options:{userData:root,currentVersion:'2.0.4'}}
}
test('successful installed version removes only its verified cached installer and matching metadata',async t=>{
 const f=await fixture(t),result=await cleanupInstalledUpdate(f.options);assert.equal(result.removed,true)
 assert.deepEqual(await fs.readdir(f.folder),['company.P2P.DOWNLOAD']);assert.equal(await fs.readFile(path.join(f.root,f.ready.filename),'utf8'),'manual installer')
})
test('a cancelled or unfinished upgrade retains the future installer for retry',async t=>{
 const f=await fixture(t);assert.equal((await cleanupInstalledUpdate({...f.options,currentVersion:'2.0.3'})).removed,false);assert.equal((await fs.stat(f.file)).size,f.ready.size)
})
test('matching version without a complete installation still retains the installer for repair',async t=>{
 const f=await fixture(t);assert.deepEqual(await cleanupInstalledUpdate({...f.options,verifyInstalled:async()=>({complete:false})}),{removed:false,deferred:false,unverified:true})
 assert.equal((await fs.stat(f.file)).size,f.ready.size)
 assert.equal((await cleanupInstalledUpdate({...f.options,verifyInstalled:async()=>({complete:true})})).removed,true)
})
test('older installed update caches are cleaned after a later version starts',async t=>{
 const f=await fixture(t);assert.equal((await cleanupInstalledUpdate({...f.options,currentVersion:'2.1.0'})).removed,true)
})
test('corrupt packages, metadata path escapes and user-selected installers are never scheduled for deletion',async t=>{
 const f=await fixture(t);assert.equal(await prepareCleanup({...f.options,installer:path.join(f.root,f.ready.filename)}),null)
 await fs.writeFile(f.readyFile,JSON.stringify({...f.ready,filename:'../'+f.ready.filename}));assert.equal((await cleanupInstalledUpdate(f.options)).removed,false)
 await fs.writeFile(f.readyFile,JSON.stringify(f.ready));const bad=await fs.readFile(f.file);bad[123]^=1;await fs.writeFile(f.file,bad)
 assert.equal((await cleanupInstalledUpdate(f.options)).removed,false);assert.equal((await fs.stat(f.file)).size,f.ready.size)
})
test('an installer still open in Windows is deferred and can be cleaned on the next successful start',async t=>{
 const f=await fixture(t);assert.deepEqual(await cleanupInstalledUpdate({...f.options,unlink:async()=>{throw Object.assign(Error('busy'),{code:'EPERM'})}}),{removed:false,deferred:true})
 assert.equal((await fs.stat(f.file)).size,f.ready.size);assert.equal((await cleanupInstalledUpdate(f.options)).removed,true)
})
test('changed newer metadata survives cleanup of the older installer',async t=>{
 const f=await fixture(t);await cleanupInstalledUpdate({...f.options,unlink:async file=>{await fs.writeFile(f.readyFile,JSON.stringify({...f.ready,version:'2.0.5',filename:'StarTranslator-Setup-2.0.5.exe'}));await fs.unlink(file)}})
 assert.equal(JSON.parse(await fs.readFile(f.readyFile,'utf8')).version,'2.0.5')
})
