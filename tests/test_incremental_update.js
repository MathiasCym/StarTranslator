const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process')
const {createManifest,MANIFEST,verifyInstallation}=require('../lib/install-integrity'),{buildPatch,stagePatch,inspectPatch,hash}=require('../lib/incremental-update')
async function fixture(t){
 const folder=await fs.mkdtemp(path.join(__dirname,'.patch-test-'));t.after(()=>fs.rm(folder,{recursive:true,force:true}));const base=path.join(folder,'old'),target=path.join(folder,'new');const random=crypto.randomBytes(2*1024*1024)
 const files={'星译官.exe':random,'resources/app.asar':Buffer.from('old application'),'resources/officecli/officecli.exe':random,'resources/python-runtime/python.exe':random,'resources/python-runtime/python311.dll':random,'resources/app.asar.unpacked/backend/server.py':Buffer.from('old backend'),'resources/repair/components.gzpack':random,'resources/repair/index.json':Buffer.from('old recovery'),'resources/app.asar.unpacked/backend/obsolete.py':Buffer.from('obsolete')}
 for(const root of [base,target])for(const [p,bytes] of Object.entries(files)){await fs.mkdir(path.dirname(path.join(root,p)),{recursive:true});await fs.writeFile(path.join(root,p),bytes)}
 for(const [p,bytes] of Object.entries({'星译官.exe':Buffer.concat([random.subarray(0,200000),Buffer.from('version2.0.11'),random.subarray(200000)]),'resources/app.asar':Buffer.from('new application'),'resources/app.asar.unpacked/backend/server.py':Buffer.from('new backend'),'resources/app.asar.unpacked/backend/new.py':Buffer.from('new module'),'resources/repair/components.gzpack':Buffer.concat([Buffer.from('new compressed member'),random]),'resources/repair/index.json':Buffer.from('new recovery')}))await fs.writeFile(path.join(target,p),bytes)
 await fs.unlink(path.join(target,'resources/app.asar.unpacked/backend/obsolete.py'))
 for(const [root,v] of [[base,'2.0.10'],[target,'2.0.11']])await fs.writeFile(path.join(root,MANIFEST),JSON.stringify(await createManifest(root,v)))
 const file=path.join(folder,'patch.stpatch'),result=await buildPatch(base,target,file)
 return {folder,base,target,file,result}
}
test('small version-bound patch reproduces exact changed bytes including shifted binaries and repair data',async t=>{
 const f=await fixture(t);assert(f.result.size<400000);const stage=path.join(f.folder,'stage'),plan=await stagePatch({file:f.file,root:f.base,currentVersion:'2.0.10',folder:stage})
 for(const entry of plan.changed)assert((await fs.readFile(path.join(stage,entry.stage))).equals(await fs.readFile(path.join(f.target,entry.path))))
 assert.deepEqual(plan.removed,['resources/app.asar.unpacked/backend/obsolete.py']);assert(!plan.changed.some(e=>e.path.includes('officecli')))
 assert.equal(await fs.readFile(path.join(f.base,'resources/app.asar'),'utf8'),'old application')
})
test('wrong base version, changed installed files and corrupt patch data never change the original installation',async t=>{
 const f=await fixture(t)
 await assert.rejects(stagePatch({file:f.file,root:f.base,currentVersion:'2.0.9',folder:path.join(f.folder,'wrong')}),/不适合/)
 await fs.writeFile(path.join(f.base,'resources/app.asar'),'tampered');await assert.rejects(stagePatch({file:f.file,root:f.base,currentVersion:'2.0.10',folder:path.join(f.folder,'bad')}),/不完整/)
 assert.equal(await fs.readFile(path.join(f.base,'resources/app.asar'),'utf8'),'tampered')
})
test('path traversal, missing changes, out-of-range binary references and duplicate paths are rejected',async t=>{
 const f=await fixture(t),bytes=await fs.readFile(f.file),count=bytes.readUInt32LE(8),h=JSON.parse(bytes.subarray(12,12+count)),payload=bytes.subarray(12+count)
 for(const change of [x=>x.changed[0].path='../outside',x=>x.changed.pop(),x=>x.changed[0].operations[0].copy=Number.MAX_SAFE_INTEGER,x=>x.changed.push(x.changed[0])]){const value=structuredClone(h);change(value);const json=Buffer.from(JSON.stringify(value)),prefix=Buffer.from(bytes.subarray(0,12));prefix.writeUInt32LE(json.length,8);const bad=path.join(f.folder,'bad.stpatch');await fs.writeFile(bad,Buffer.concat([prefix,json,payload]));await assert.rejects(inspectPatch(bad))}
})
test('Windows helper applies exact files, keeps user data and rolls back locked-file failures', {skip:process.platform!=='win32'},async t=>{
 const f=await fixture(t);await fs.writeFile(path.join(f.base,'my-document.txt'),'keep');const plan=await stagePatch({file:f.file,root:f.base,currentVersion:'2.0.10',folder:path.join(f.folder,'stage')})
 async function run(fail=false){Object.assign(plan,{id:crypto.randomUUID(),parentPid:0,restart:false});const script=path.join(plan.folder,'apply.ps1'),json=Buffer.from(JSON.stringify(plan));await fs.writeFile(path.join(plan.folder,'plan.json'),json);let worker=require('../lib/patch-worker').worker.replace('__PLAN_HASH__',hash(json)).replace(/New-Item -Path \$runKey[^\n]+/,'# The isolated harness does not register a login action.').replace(/Remove-ItemProperty -Path \$runKey[^\n]+/,'# No login action in this harness.');if(fail)worker=worker.replace('for($i=0;$i -lt $all.Count;$i++){$e=$all[$i];','for($i=0;$i -lt $all.Count;$i++){if($i -eq 2){throw \'Injected write failure\'};$e=$all[$i];');await fs.writeFile(script,'\ufeff'+worker);const result=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',script],{windowsHide:true,encoding:'utf8'});assert.equal(result.status,0,result.stderr);const value=JSON.parse(await fs.readFile(path.join(plan.folder,'result.json'),'utf8'));value.error=await fs.readFile(path.join(plan.folder,'error.txt'),'utf8').catch(()=>null);return value}
 const failed=await run(true);assert.equal(failed.complete,false);assert((await verifyInstallation(f.base,plan.base,'2.0.10')).complete,failed.error)
 const success=await run();assert.equal(success.complete,true,success.error);assert((await verifyInstallation(f.base,plan.target,'2.0.11')).complete);assert.equal(await fs.readFile(path.join(f.base,'my-document.txt'),'utf8'),'keep');await assert.rejects(fs.stat(path.join(f.base,'resources/app.asar.unpacked/backend/obsolete.py')),{code:'ENOENT'})
})
