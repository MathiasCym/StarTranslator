const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process')
const {createManifest,MANIFEST,verifyInstallation}=require('../lib/install-integrity'),{buildPatch}=require('../lib/incremental-update'),{launchPatch,cleanupAppliedPatches}=require('../lib/patch-worker')
const wait=ms=>new Promise(r=>setTimeout(r,ms))
test('published script-launch baselines receive a one-time native small update entry',()=>{
 const {needsBridge}=require('../tools/build-incremental.cjs')
 for(const version of ['2.0.10','2.0.12','2.3.4','2.3.5','2.3.6'])assert(needsBridge(version),version)
 for(const version of ['2.3.7','2.3.8','2.4.0'])assert(!needsBridge(version),version)
})
async function fixture(t){
 const folder=await fs.mkdtemp(path.join(__dirname,'.native-patch-')),base=path.join(folder,'old'),target=path.join(folder,'new'),profile=path.join(process.env.APPDATA,'StarTranslatorUpdater-QA-'+crypto.randomUUID())
 t.after(async()=>{assert.equal(path.dirname(folder),__dirname);await fs.rm(folder,{recursive:true,force:true,maxRetries:20,retryDelay:100});assert.equal(path.dirname(profile),process.env.APPDATA);await fs.rm(profile,{recursive:true,force:true,maxRetries:20,retryDelay:100})})
 for(const dir of [base,target])for(const name of ['星译官.exe','resources/app.asar','resources/officecli/officecli.exe','resources/python-runtime/python.exe','resources/python-runtime/python311.dll','resources/app.asar.unpacked/backend/server.py']){await fs.mkdir(path.dirname(path.join(dir,name)),{recursive:true});await fs.writeFile(path.join(dir,name),dir===base?'old bytes':'new bytes')}
 for(const [dir,version] of [[base,'2.3.5'],[target,'2.3.7']])await fs.writeFile(path.join(dir,MANIFEST),JSON.stringify(await createManifest(dir,version)))
 await fs.writeFile(path.join(base,'personal.txt'),'keep')
 const file=path.join(folder,'patch.stpatch');await buildPatch(base,target,file)
 return {folder,base,target,profile,file}
}
async function result(launched){for(let i=0;i<200;i++){const value=await fs.readFile(path.join(launched.folder,'result.json'),'utf8').then(JSON.parse,()=>null);if(value){await wait(300);return value}await wait(50)}throw Error('Native worker did not finish')}
test('native GUI helper applies from Roaming without generating scripts and cleans only verified owned files',{skip:process.platform!=='win32'},async t=>{
 const f=await fixture(t),launched=await launchPatch({file:f.file,root:f.base,currentVersion:'2.3.5',userData:f.profile,parentPid:0,restart:false,showProgress:false,registerRecovery:false})
 assert((await result(launched)).complete,await fs.readFile(path.join(launched.folder,'error.txt'),'utf8').catch(()=>''))
 const manifest=JSON.parse(await fs.readFile(path.join(f.target,MANIFEST))),verify=()=>verifyInstallation(f.base,manifest,'2.3.7')
 assert((await verify()).complete);assert.equal(await fs.readFile(path.join(f.base,'personal.txt'),'utf8'),'keep')
 const names=await fs.readdir(launched.folder);assert(!names.some(n=>/\.(ps1|cmd|vbs)$/i.test(n)))
 assert(JSON.parse(await fs.readFile(path.join(launched.folder,'launcher.json'))).native)
 assert(!(await cleanupAppliedPatches({root:f.base,userData:f.profile,currentVersion:'2.3.7',verifyInstalled:verify})).deferred)
 await assert.rejects(fs.stat(launched.folder),{code:'ENOENT'})
})
test('native mid-application failure restores every original byte and keeps personal files',{skip:process.platform!=='win32'},async t=>{
 const f=await fixture(t),helper=require('../tools/build-patch-helper.cjs').build({output:path.join(f.folder,'fault-helper.exe'),testing:true})
 const launched=await launchPatch({file:f.file,root:f.base,currentVersion:'2.3.5',userData:f.profile,parentPid:0,restart:false,showProgress:false,registerRecovery:false,helperPath:helper,
  spawnProcess:(exe,args,options)=>require('node:child_process').spawn(exe,args,{...options,env:{...options.env,STAR_PATCH_TEST_FAIL_AFTER:'2'}})})
 const outcome=await result(launched);assert.equal(outcome.complete,false);assert(!outcome.requiresFull)
 assert((await verifyInstallation(f.base,JSON.parse(await fs.readFile(path.join(launched.folder,'plan.json'))).base,'2.3.5')).complete)
 assert.equal(await fs.readFile(path.join(f.base,'personal.txt'),'utf8'),'keep');assert.match(await fs.readFile(path.join(launched.folder,'error.txt'),'utf8'),/原程序已恢复/)
})
test('native helper rejects changed plans before readiness and preserves the running version',{skip:process.platform!=='win32'},async t=>{
 const f=await fixture(t)
 await assert.rejects(launchPatch({file:f.file,root:f.base,currentVersion:'2.3.5',userData:f.profile,parentPid:0,restart:false,showProgress:false,registerRecovery:false,
  spawnProcess:(exe,args,options)=>{const file=path.join(path.dirname(exe),'plan.json');require('node:fs').appendFileSync(file,' ');return require('node:child_process').spawn(exe,args,options)}}),/校验失败|异常退出/)
 const manifest=JSON.parse(await fs.readFile(path.join(f.base,MANIFEST)));assert.equal(manifest.version,'2.3.5');assert((await verifyInstallation(f.base,manifest,'2.3.5')).complete)
})
test('native launch errors retain exact diagnostics without claiming UAC cancellation',{skip:process.platform!=='win32'},async t=>{
 const f=await fixture(t)
 await assert.rejects(launchPatch({file:f.file,root:f.base,currentVersion:'2.3.5',userData:f.profile,parentPid:0,restart:false,showProgress:false,registerRecovery:false,
  spawnProcess:()=>{const e=Error('Injected start rejection');e.code='EACCES';throw e}}),/EACCES/)
 const folder=path.join(f.profile,'updates',(await fs.readdir(path.join(f.profile,'updates')))[0]),diag=JSON.parse(await fs.readFile(path.join(folder,'launcher.json')))
 assert.equal(diag.code,'EACCES');assert(!JSON.stringify(diag).includes('授权已取消'));assert.equal(await fs.readFile(path.join(folder,'cancel'),'utf8'),'1')
})
