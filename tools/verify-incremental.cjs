const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process')
const {stagePatch,hash}=require('../lib/incremental-update'),{verifyInstallation}=require('../lib/install-integrity'),{worker}=require('../lib/patch-worker')
async function verify({file,base,target,output}){
 const current=JSON.parse(await fs.readFile(path.join(base,'resources/install-manifest.json'),'utf8')).version,folder=await fs.mkdtemp(path.join(path.dirname(file),'.stage-'))
 // stagePatch requires a fresh directory so it cannot overwrite an old stage.
 await fs.rmdir(folder)
 const plan=await stagePatch({file,root:base,currentVersion:current,folder});Object.assign(plan,{id:crypto.randomUUID(),parentPid:0,restart:false})
 const bytes=Buffer.from(JSON.stringify(plan)),script=path.join(folder,'apply.ps1')
 await fs.writeFile(path.join(folder,'plan.json'),bytes)
 // QA suppresses only login recovery registration. The production replacement,
 // SHA checks and rollback code execute unchanged, against this extracted copy.
 const source=worker.replace('__PLAN_HASH__',hash(bytes)).replace(/RegisterRecovery \$runName \$resume/,'# No registry writes for extracted QA.').replace(/RemoveRecovery \$runName/,'# No registry writes for extracted QA.')
 await fs.writeFile(script,'\ufeff'+source)
 const result=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',script],{windowsHide:true,encoding:'utf8',timeout:180000})
 const outcome=JSON.parse(await fs.readFile(path.join(folder,'result.json'),'utf8').catch(()=>'{"complete":false}'))
 if(result.status!==0||!outcome.complete)throw Error('Incremental application failed: '+(await fs.readFile(path.join(folder,'error.txt'),'utf8').catch(()=>result.stderr)))
 const actual=await verifyInstallation(base,plan.target,plan.to)
 if(!actual.complete)throw Error('Incremental result differs from full installer: '+JSON.stringify(actual.failures))
 if(!(await fs.readFile(path.join(base,'resources/install-manifest.json'))).equals(await fs.readFile(path.join(target,'resources/install-manifest.json'))))throw Error('Incremental install manifest differs from full installer')
 await fs.writeFile(output,JSON.stringify({passed:true,from:plan.from,version:plan.to,files:actual.checked,patchBytes:(await fs.stat(file)).size,installerExecuted:false,isolatedInstallation:true},null,2))
 if(path.dirname(folder)!==path.dirname(file)||!path.basename(folder).startsWith('.stage-'))throw Error('Unsafe stage cleanup')
 await fs.rm(folder,{recursive:true,force:true})
}
module.exports={verify}
