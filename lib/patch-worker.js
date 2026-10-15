// A separate Windows process replaces closed program files. The plan and every
// staged file are rechecked; originals remain until the final integrity scan.
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),{spawn}=require('node:child_process')
const {stagePatch,hash}=require('./incremental-update'),{directoryNeedsElevation}=require('./setup-worker')
const quote=s=>"'"+s.replaceAll("'","''")+"'"
const worker=String.raw`
param([switch]$Recover)
$PlanFile=Join-Path $PSScriptRoot 'plan.json';$PlanHash='__PLAN_HASH__'
$ErrorActionPreference='Stop'
function HashFile($p){$stream=[IO.File]::OpenRead($p);try{$sha=[Security.Cryptography.SHA256]::Create();try{return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}}finally{$stream.Dispose()}}
function CheckFile($p,$e){if(!(Test-Path -LiteralPath $p -PathType Leaf) -or (Get-Item -LiteralPath $p).Length -ne $e.size -or (HashFile $p) -ne $e.sha256){throw 'Program file verification failed'}}
function SafePath($root,$relative){
 if($relative -match '[\\:\x00-\x1f]' -or $relative -match '(^|/)\.{1,2}(/|$)' -or $relative -match '^/' ){throw 'Invalid update path'}
 $p=[IO.Path]::GetFullPath((Join-Path $root $relative));if(!$p.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Update escaped installation'}
 $probe=$p;while($probe -and $probe.Length -ge $root.Length){if(Test-Path -LiteralPath $probe){if((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked update target'}};$probe=[IO.Path]::GetDirectoryName($probe)}
 return $p
}
$plan=$null;$transaction=$null;$locked=$null;$success=$false;$mutating=$false;$closed=$Recover;$canRestart=$false
try{
 if((HashFile $PlanFile) -ne $PlanHash){throw 'Update plan changed'}
 $plan=Get-Content -LiteralPath $PlanFile -Raw -Encoding UTF8|ConvertFrom-Json
 if($plan.schema -ne 1 -or $plan.from -notmatch '^\d+\.\d+\.\d+$' -or $plan.to -notmatch '^\d+\.\d+\.\d+$'){throw 'Invalid update plan'}
 $root=[IO.Path]::GetFullPath($plan.root).TrimEnd('\');$folder=[IO.Path]::GetFullPath($plan.folder)
 $transaction=Join-Path $root ('.star-update-'+$plan.id)
 if($plan.id -notmatch '^[a-f0-9-]{36}$' -or !(Test-Path -LiteralPath $root -PathType Container)){throw 'Invalid installation'}
 $manifest=SafePath $root 'resources/install-manifest.json'
 $all=@($plan.changed)+@($plan.removed|ForEach-Object { [pscustomobject]@{path=$_;stage=$null} })
 foreach($entry in $all){$null=SafePath $root $entry.path}
 $runKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce';$runName='StarTranslatorUpdate-'+$plan.id
 function RestoreOriginals {
   for($i=$all.Count-1;$i -ge 0;$i--){$e=$all[$i];$dest=SafePath $root $e.path;$backup=Join-Path $transaction ('old-'+$i)
     if(Test-Path -LiteralPath $backup){if(Test-Path -LiteralPath $dest){Remove-Item -LiteralPath $dest -Force};[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest))|Out-Null;[IO.File]::Move($backup,$dest)}
     elseif(!@($plan.base.files.path).Contains($e.path) -and $e.path -ne 'resources/install-manifest.json' -and (Test-Path -LiteralPath $dest)){CheckFile $dest $e;Remove-Item -LiteralPath $dest -Force}
   }
 }
 if($Recover){
   if(Test-Path -LiteralPath (Join-Path $transaction 'committed')){$success=$true}
   elseif(Test-Path -LiteralPath (Join-Path $transaction 'applying')){RestoreOriginals;foreach($e in $plan.base.files){if($e.path -notmatch '(^|/)__pycache__/|\.py[co]$'){CheckFile (SafePath $root $e.path) $e}};$canRestart=$true}
 }else{
   if((HashFile $manifest) -ne $plan.baseManifest){throw 'Installed version changed'}
   foreach($e in $plan.base.files){if($e.path -notmatch '(^|/)__pycache__/|\.py[co]$'){CheckFile (SafePath $root $e.path) $e}}
   foreach($e in $plan.changed){CheckFile (Join-Path $folder $e.stage) $e}
   # The lock is local to this installation. A second updater cannot enter.
   $locked=[IO.File]::Open((Join-Path $root '.star-update.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
   [IO.Directory]::CreateDirectory($transaction)|Out-Null
   foreach($e in $plan.changed){$dest=Join-Path $transaction ('new-'+$e.stage);[IO.File]::Copy((Join-Path $folder $e.stage),$dest,$false);CheckFile $dest $e}
   $self=$PSCommandPath
   $resume='powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$self+'" -Recover'
   if($resume.Length -gt 260){throw 'Recovery path is too long; use the full installer'}
   New-Item -Path $runKey -Force|Out-Null;New-ItemProperty -Path $runKey -Name $runName -Value $resume -PropertyType String -Force|Out-Null
   [IO.File]::WriteAllText((Join-Path $folder 'started'),'ready')
   if($plan.parentPid -gt 0){$parent=Get-Process -Id $plan.parentPid -ErrorAction SilentlyContinue;if($parent -and !$parent.WaitForExit(120000)){throw 'Application did not close'}}
   $closed=$true
   # Never terminate another instance or a document-rendering process.
   $busy=Get-Process -ErrorAction SilentlyContinue|Where-Object {try{$_.Path -and $_.Path.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)}catch{$false}}
   if($busy){throw 'Installation is still in use'}
   if((HashFile $manifest) -ne $plan.baseManifest){throw 'Installed version changed'}
   foreach($e in $plan.base.files){if($e.path -notmatch '(^|/)__pycache__/|\.py[co]$'){CheckFile (SafePath $root $e.path) $e}}
   foreach($e in $plan.changed){if($e.path -ne 'resources/install-manifest.json' -and !@($plan.base.files.path).Contains($e.path) -and (Test-Path -LiteralPath (SafePath $root $e.path))){throw 'New program file conflicts with an existing file'}}
   [IO.File]::WriteAllText((Join-Path $transaction 'applying'),'1');$mutating=$true
   for($i=0;$i -lt $all.Count;$i++){$e=$all[$i];$dest=SafePath $root $e.path
     if(Test-Path -LiteralPath $dest){[IO.File]::Move($dest,(Join-Path $transaction ('old-'+$i)))}
     if($null -ne $e.stage){[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest))|Out-Null;[IO.File]::Move((Join-Path $transaction ('new-'+$e.stage)),$dest)}
   }
   foreach($e in $plan.target.files){CheckFile (SafePath $root $e.path) $e}
   [IO.File]::WriteAllText((Join-Path $transaction 'committed'),'1');$success=$true
 }
 if($success){
   $canRestart=$true
   # Preserve scope and location; only update this product's registered version.
   foreach($hive in @('HKCU','HKLM')){$key=$hive+':\Software\Microsoft\Windows\CurrentVersion\Uninstall\40dcc9aa-3b67-5e68-9a54-dc7e46ccf86d';try{$record=Get-ItemProperty -LiteralPath $key -ErrorAction Stop;if($record.InstallLocation -and $record.InstallLocation.TrimEnd('\') -eq $root){Set-ItemProperty -LiteralPath $key -Name DisplayVersion -Value $plan.to}}catch{}}
 }
 [IO.File]::WriteAllText((Join-Path $folder 'result.json'),('{"complete":'+$success.ToString().ToLowerInvariant()+',"rolledBack":'+(!$success).ToString().ToLowerInvariant()+'}'))
 Remove-ItemProperty -Path $runKey -Name $runName -ErrorAction SilentlyContinue
 if($success -and [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($transaction)) -eq $root -and [IO.Path]::GetFileName($transaction) -eq ('.star-update-'+$plan.id)){
   # The final installed files have passed the complete target manifest. Release
   # the rollback data here while the helper still has installation permission.
   try{Remove-Item -LiteralPath $transaction -Recurse -Force}catch{}
 }
}catch{
 $message=$_.Exception.Message
 if($mutating){try{RestoreOriginals;foreach($e in $plan.base.files){if($e.path -notmatch '(^|/)__pycache__/|\.py[co]$'){CheckFile (SafePath $root $e.path) $e}};$canRestart=$true;$message='Update failed; original installation restored. '+$message}catch{$canRestart=$false;$message='Automatic rollback needs repair. '+$message}}
 elseif($closed -and !$busy){$canRestart=$true}
 if($plan){[IO.File]::WriteAllText((Join-Path $folder 'error.txt'),$message);[IO.File]::WriteAllText((Join-Path $folder 'result.json'),' {"complete":false}')}
}finally{
 if($locked){$locked.Dispose()}
 if($closed -and $canRestart -and $plan -and $plan.restart -and (Test-Path -LiteralPath (Join-Path $root '星译官.exe'))){
   if($plan.elevated){try{(New-Object -ComObject Shell.Application).ShellExecute((Join-Path $root '星译官.exe'),'',$root,'open',1)}catch{[IO.File]::WriteAllText((Join-Path $folder 'restart.txt'),'Please reopen StarTranslator.')}}
   else{Start-Process -FilePath (Join-Path $root '星译官.exe') -WorkingDirectory $root}
 }
}
`
async function launchPatch({file,root,currentVersion,userData,parentPid=process.pid,restart=true,spawnProcess=spawn}){
  const folder=path.join(userData,'updates','apply-'+crypto.randomUUID()),plan=await stagePatch({file,root,currentVersion,folder})
  const elevate=await directoryNeedsElevation(root)
  Object.assign(plan,{id:crypto.randomUUID(),parentPid,restart,elevated:elevate})
  const planFile=path.join(folder,'plan.json'),script=path.join(folder,'apply.ps1'),bytes=Buffer.from(JSON.stringify(plan))
  await fs.writeFile(planFile,bytes,{flag:'wx'});await fs.writeFile(script,'\ufeff'+worker.replace('__PLAN_HASH__',hash(bytes)),{flag:'wx'})
  const exe=path.join(process.env.SystemRoot||'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe')
  const args=['-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',script]
  let child
  if(elevate){const list=args.map(s=>'"'+s.replaceAll('"','')+'"').join(' '),code=`try {Start-Process -FilePath ${quote(exe)} -ArgumentList ${quote(list)} -Verb RunAs -WindowStyle Hidden -Wait} catch {exit 1223}`;child=spawnProcess(exe,['-NoProfile','-NonInteractive','-WindowStyle','Hidden','-EncodedCommand',Buffer.from(code,'utf16le').toString('base64')],{windowsHide:true,stdio:'ignore',detached:true})}
  else child=spawnProcess(exe,args,{windowsHide:true,stdio:'ignore',detached:true})
  let failure;child.on('error',e=>{failure=e});child.on('exit',code=>{if(code)failure=Error('更新辅助程序未能启动，或管理员授权已取消。')});child.unref()
  for(let i=0;i<600;i++){
    if(failure)throw failure
    if(await fs.readFile(path.join(folder,'started'),'utf8').catch(()=>null)==='ready')return {started:true,folder}
    const error=await fs.readFile(path.join(folder,'error.txt'),'utf8').catch(()=>null);if(error)throw Error('增量更新准备失败：'+error)
    await new Promise(resolve=>setTimeout(resolve,100))
  }
  throw Error('更新辅助程序未确认启动，原程序尚未关闭。')
}
async function cleanupAppliedPatches({root,userData,currentVersion,verifyInstalled}){
  const base=path.resolve(userData,'updates');let checked
  for(const name of await fs.readdir(base).catch(()=>[])){
    if(!/^apply-[a-f0-9-]{36}$/.test(name))continue
    const folder=path.resolve(base,name);if(path.dirname(folder)!==base||(await fs.lstat(folder)).isSymbolicLink())continue
    try{
      const result=JSON.parse(await fs.readFile(path.join(folder,'result.json'),'utf8')),plan=JSON.parse(await fs.readFile(path.join(folder,'plan.json'),'utf8'))
      if(!result.complete||plan.root!==path.resolve(root)||plan.to!==currentVersion||!/^[a-f0-9-]{36}$/.test(plan.id))continue
      checked ||= await verifyInstalled();if(!checked?.complete)return {unverified:true}
      const transaction=path.resolve(root,'.star-update-'+plan.id)
      if(path.dirname(transaction)!==path.resolve(root))continue
      if(await fs.lstat(transaction).then(s=>s.isSymbolicLink(),e=>{if(e.code==='ENOENT')return false;throw e}))continue
      // Both absolute targets have been checked against their owned roots.
      await fs.rm(transaction,{recursive:true,force:true});await fs.rm(folder,{recursive:true,force:true})
    }catch(error){if(['EACCES','EPERM','EBUSY'].includes(error.code))return {deferred:true}}
  }
  return {deferred:false}
}
module.exports={worker,launchPatch,cleanupAppliedPatches}
