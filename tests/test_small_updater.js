const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{spawn,execFileSync}=require('node:child_process')
const {createManifest,MANIFEST,verifyInstallation}=require('../lib/install-integrity'),{buildPatch}=require('../lib/incremental-update')
test('small executable uses the old runtime, survives launcher exit, applies exact bytes and restarts the new app',{skip:process.platform!=='win32',timeout:60000},async t=>{
 const folder=await fs.mkdtemp(path.join(__dirname,'.small-updater-'));t.after(()=>fs.rm(folder,{recursive:true,force:true,maxRetries:20,retryDelay:200}))
 const base=path.join(folder,'base'),target=path.join(folder,'target'),profile=path.join(folder,'user')
 for(const root of [base,target]){
  for(const name of ['resources/app.asar','resources/officecli/officecli.exe','resources/python-runtime/python.exe','resources/python-runtime/python311.dll','resources/app.asar.unpacked/backend/server.py']){await fs.mkdir(path.dirname(path.join(root,name)),{recursive:true});await fs.writeFile(path.join(root,name),root===base?'original':'updated')}
 }
 await fs.copyFile(process.execPath,path.join(base,'星译官.exe'))
 const cs=path.join(folder,'restarted.cs');await fs.writeFile(cs,'class Restarted {static void Main(){System.IO.File.WriteAllText(System.IO.Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory,"restarted.txt"),"new app started");}}')
 execFileSync(path.join(process.env.SystemRoot,'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),['/nologo','/target:winexe','/out:'+path.join(target,'星译官.exe'),cs],{windowsHide:true,stdio:'ignore'})
 for(const [root,version] of [[base,'2.0.11'],[target,'2.0.12']])await fs.writeFile(path.join(root,MANIFEST),JSON.stringify(await createManifest(root,version)))
 await fs.writeFile(path.join(base,'personal.txt'),'keep')
 const filename='StarTranslator-Patch-2.0.11-to-2.0.12.stpatch',patch=await buildPatch(base,target,path.join(folder,filename))
 const wrapper=await require('../tools/build-small-updater.cjs').buildSmallUpdater(patch,{output:folder})
 assert(wrapper.size<2*1024*1024);assert.equal(wrapper.to,'2.0.12')
 const child=spawn(path.join(folder,wrapper.filename),[base,profile,'--no-progress'],{windowsHide:true,stdio:['ignore','ignore','pipe']});let stderr='';child.stderr.on('data',value=>stderr+=value)
 const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve)})
 assert.equal(code,0,stderr);let result,apply
 for(let i=0;i<250;i++){
  apply=(await fs.readdir(path.join(profile,'updates'))).find(n=>n.startsWith('apply-'))
  if(apply)result=await fs.readFile(path.join(profile,'updates',apply,'result.json'),'utf8').then(JSON.parse,()=>null)
  if(result&&await fs.stat(path.join(base,'restarted.txt')).then(()=>true,()=>false))break
  await new Promise(resolve=>setTimeout(resolve,100))
 }
 const diagnostics={result,files:apply?await fs.readdir(path.join(profile,'updates',apply)):[],progress:apply?await fs.readFile(path.join(profile,'updates',apply,'progress.json'),'utf8').catch(()=>''):''}
 if(!result?.complete&&apply){await fs.mkdir(path.resolve(__dirname,'../dist/qa'),{recursive:true});await fs.writeFile(path.resolve(__dirname,'../dist/qa/failed-small-updater.json'),JSON.stringify(diagnostics,null,2))}
 assert(result?.complete,JSON.stringify(diagnostics)+' '+await fs.readFile(path.join(profile,'updates',apply||'','error.txt'),'utf8').catch(()=>''))
 assert.equal(await fs.readFile(path.join(base,'restarted.txt'),'utf8'),'new app started')
 assert((await verifyInstallation(base,JSON.parse(await fs.readFile(path.join(target,MANIFEST))),'2.0.12')).complete)
 assert.equal(await fs.readFile(path.join(base,'personal.txt'),'utf8'),'keep')
 const verifyInstalled=()=>verifyInstallation(base,JSON.parse(require('node:fs').readFileSync(path.join(base,MANIFEST))),'2.0.12')
 await require('../lib/patch-worker').cleanupAppliedPatches({root:base,userData:profile,currentVersion:'2.0.12',verifyInstalled})
 assert((await require('../lib/update-cache-cleanup').cleanupInstalledUpdate({userData:profile,currentVersion:'2.0.12',verifyInstalled})).removed)
 assert.deepEqual(await fs.readdir(path.join(profile,'updates')),[])
})
