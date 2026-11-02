// A separate Windows process replaces closed program files. The plan and every
// staged file are rechecked; originals remain until the final integrity scan.
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),{spawn}=require('node:child_process')
const {stagePatch,hash}=require('./incremental-update'),{directoryNeedsElevation}=require('./setup-worker')
const quote=s=>"'"+s.replaceAll("'","''")+"'"
const worker=String.raw`
param([switch]$Recover)
$PlanFile=Join-Path $PSScriptRoot 'plan.json';$PlanHash='__PLAN_HASH__'
$ErrorActionPreference='Stop'
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'worker.pid'),[string]$PID)
$progressForm=$null;$progressText=$null;$progressBar=$null
function Progress($phase,$done,$total,$message){
 $value=@{phase=$phase;done=$done;total=$total;message=$message}|ConvertTo-Json -Compress
 [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'progress.json'),$value,[Text.UTF8Encoding]::new($false))
 if($progressForm){$progressText.Text=$message;$progressBar.Value=[Math]::Min(100,[Math]::Max(0,[int](100*$done/[Math]::Max(1,$total))));[Windows.Forms.Application]::DoEvents()}
 if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'cancel')){throw 'Update preparation cancelled; original program is unchanged'}
}
function OpenProgress {
 if(!$plan.showProgress){return}
 try{
  Add-Type -AssemblyName System.Windows.Forms;Add-Type -AssemblyName System.Drawing
  $script:progressForm=New-Object Windows.Forms.Form
  $progressForm.Text='星译官 · 更新';$progressForm.Width=520;$progressForm.Height=185;$progressForm.StartPosition='CenterScreen';$progressForm.FormBorderStyle='FixedDialog';$progressForm.ControlBox=$false
  try{$progressForm.Icon=[Drawing.Icon]::ExtractAssociatedIcon((Join-Path $root '星译官.exe'))}catch{}
  $progressForm.BackColor=[Drawing.Color]::FromArgb(12,29,46);$progressForm.ForeColor=[Drawing.Color]::FromArgb(220,237,250)
  $progressForm.Font=New-Object Drawing.Font('Microsoft YaHei UI',10)
  $script:progressText=New-Object Windows.Forms.Label;$progressText.SetBounds(24,24,460,48)
  $script:progressBar=New-Object Windows.Forms.ProgressBar;$progressBar.SetBounds(24,88,460,16)
  $progressForm.Controls.Add($progressText);$progressForm.Controls.Add($progressBar);$progressForm.Show();[Windows.Forms.Application]::DoEvents()
 }catch{$script:progressForm=$null}
}
function RegisterRecovery($name,$command){
 $key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\RunOnce')
 try{$key.SetValue($name,$command,[Microsoft.Win32.RegistryValueKind]::String)}finally{$key.Dispose()}
}
function RemoveRecovery($name){
 $key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\RunOnce',$true)
 if($key){try{$key.DeleteValue($name,$false)}finally{$key.Dispose()}}
}
Progress 'starting' 0 1 '正在启动更新辅助程序'
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
   # Confirm the helper before lengthy disk work. The app stays visible during
   # staging, then this independent window carries progress through replacement.
   [IO.File]::WriteAllText((Join-Path $folder 'started'),'ready')
   if($plan.parentPid -gt 0){$parent=Get-Process -Id $plan.parentPid -ErrorAction SilentlyContinue;if($parent -and !$parent.WaitForExit(120000)){throw 'Application did not close'}}
   $closed=$true;OpenProgress
   Progress 'verify' 0 $plan.base.files.Count '正在验证原程序，即将应用小包更新'
   if((HashFile $manifest) -ne $plan.baseManifest){throw 'Installed version changed'}
   $verified=0;foreach($e in $plan.base.files){if($e.path -notmatch '(^|/)__pycache__/|\.py[co]$'){CheckFile (SafePath $root $e.path) $e};$verified++;Progress 'verify' $verified $plan.base.files.Count ('正在验证原程序 '+$verified+' / '+$plan.base.files.Count)}
   foreach($e in $plan.changed){CheckFile (Join-Path $folder $e.stage) $e}
   Progress 'prepare' 0 1 '正在准备安全替换与恢复资料'
   # The lock is local to this installation. A second updater cannot enter.
   $locked=[IO.File]::Open((Join-Path $root '.star-update.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
   [IO.Directory]::CreateDirectory($transaction)|Out-Null
   foreach($e in $plan.changed){$dest=Join-Path $transaction ('new-'+$e.stage);[IO.File]::Copy((Join-Path $folder $e.stage),$dest,$false);CheckFile $dest $e}
   $self=$PSCommandPath
   $resume='powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$self+'" -Recover'
   if($resume.Length -gt 260){throw 'Recovery path is too long; use the full installer'}
   Progress 'recovery' 0 1 '正在登记更新恢复信息'
   RegisterRecovery $runName $resume
   # Never terminate another instance or a document-rendering process.
   Progress 'closing' 0 1 '正在确认程序文件已释放'
   $busy=Get-Process -ErrorAction SilentlyContinue|Where-Object {try{$_.Path -and $_.Path.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)}catch{$false}}
   if($busy){throw 'Installation is still in use'}
   if((HashFile $manifest) -ne $plan.baseManifest){throw 'Installed version changed'}
   Progress 'verify' 0 $plan.base.files.Count '正在进行替换前最终校验'
   foreach($e in $plan.base.files){if($e.path -notmatch '(^|/)__pycache__/|\.py[co]$'){CheckFile (SafePath $root $e.path) $e}}
   foreach($e in $plan.changed){if($e.path -ne 'resources/install-manifest.json' -and !@($plan.base.files.path).Contains($e.path) -and (Test-Path -LiteralPath (SafePath $root $e.path))){throw 'New program file conflicts with an existing file'}}
   [IO.File]::WriteAllText((Join-Path $transaction 'applying'),'1');$mutating=$true
   for($i=0;$i -lt $all.Count;$i++){$e=$all[$i];$dest=SafePath $root $e.path
     Progress 'apply' $i $all.Count ('正在更新程序文件 '+($i+1)+' / '+$all.Count)
     if(Test-Path -LiteralPath $dest){[IO.File]::Move($dest,(Join-Path $transaction ('old-'+$i)))}
     if($null -ne $e.stage){[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest))|Out-Null;[IO.File]::Move((Join-Path $transaction ('new-'+$e.stage)),$dest)}
   }
   $verified=0;foreach($e in $plan.target.files){CheckFile (SafePath $root $e.path) $e;$verified++;Progress 'check' $verified $plan.target.files.Count ('正在校验更新完整性 '+$verified+' / '+$plan.target.files.Count)}
   [IO.File]::WriteAllText((Join-Path $transaction 'committed'),'1');$success=$true
 }
 if($success){
   Progress 'complete' 1 1 '更新完成，正在重新打开星译官'
   $canRestart=$true
   # Preserve scope and location; only update this product's registered version.
   foreach($hive in @('HKCU','HKLM')){$key=$hive+':\Software\Microsoft\Windows\CurrentVersion\Uninstall\40dcc9aa-3b67-5e68-9a54-dc7e46ccf86d';try{$record=Get-ItemProperty -LiteralPath $key -ErrorAction Stop;if($record.InstallLocation -and $record.InstallLocation.TrimEnd('\') -eq $root){Set-ItemProperty -LiteralPath $key -Name DisplayVersion -Value $plan.to}}catch{}}
 }
 [IO.File]::WriteAllText((Join-Path $folder 'result.json'),('{"complete":'+$success.ToString().ToLowerInvariant()+',"rolledBack":'+(!$success).ToString().ToLowerInvariant()+'}'))
 RemoveRecovery $runName
 if($success -and [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($transaction)) -eq $root -and [IO.Path]::GetFileName($transaction) -eq ('.star-update-'+$plan.id)){
   # The final installed files have passed the complete target manifest. Release
   # the rollback data here while the helper still has installation permission.
   try{Remove-Item -LiteralPath $transaction -Recurse -Force}catch{}
 }
}catch{
 $message=$_.Exception.Message
 if($mutating){try{RestoreOriginals;foreach($e in $plan.base.files){if($e.path -notmatch '(^|/)__pycache__/|\.py[co]$'){CheckFile (SafePath $root $e.path) $e}};$canRestart=$true;$message='Update failed; original installation restored. '+$message}catch{$canRestart=$false;$message='Automatic rollback needs repair. '+$message}}
 elseif($closed -and !$busy){$canRestart=$true}
 if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'cancel')){$canRestart=$false}
 if($canRestart -and $plan){try{RemoveRecovery $runName}catch{}}
 if($plan){[IO.File]::WriteAllText((Join-Path $folder 'error.txt'),$message);[IO.File]::WriteAllText((Join-Path $folder 'result.json'),('{"complete":false,"requiresFull":'+($mutating -and !$canRestart).ToString().ToLowerInvariant()+'}'))}
 if($plan -and $plan.showProgress -and $closed -and !(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'cancel'))){
   try{Add-Type -AssemblyName System.Windows.Forms;$notice=if($canRestart){'更新未完成，原程序已保留或恢复。'}else{'更新未完成，请使用完整安装包修复程序。'};[Windows.Forms.MessageBox]::Show($notice+[Environment]::NewLine+$message,'星译官 · 更新未完成')|Out-Null}catch{}
 }
}finally{
 if($progressForm){$progressForm.Close();$progressForm.Dispose()}
 if($locked){$locked.Dispose()}
 if($closed -and $canRestart -and $plan -and $plan.restart -and (Test-Path -LiteralPath (Join-Path $root '星译官.exe'))){
   if($plan.elevated){try{(New-Object -ComObject Shell.Application).ShellExecute((Join-Path $root '星译官.exe'),'',$root,'open',1)}catch{[IO.File]::WriteAllText((Join-Path $folder 'restart.txt'),'Please reopen StarTranslator.')}}
   else{Start-Process -FilePath (Join-Path $root '星译官.exe') -WorkingDirectory $root}
 }
}
`
async function launchPatch({file,root,currentVersion,userData,parentPid=process.pid,restart=true,showProgress=true,registerRecovery=true,helperPath,spawnProcess=spawn,progress=()=>{},startupTimeout=30000}){
  await fs.mkdir(path.join(userData,'updates'),{recursive:true})
  const folder=path.join(userData,'updates','apply-'+crypto.randomUUID()),plan=await stagePatch({file,root,currentVersion,folder,progress})
  const elevate=await directoryNeedsElevation(root)
  Object.assign(plan,{id:crypto.randomUUID(),parentPid,restart,elevated:elevate,showProgress,registerRecovery})
  const planFile=path.join(folder,'plan.json'),bytes=Buffer.from(JSON.stringify(plan))
  await fs.writeFile(planFile,bytes,{flag:'wx'})
  let source=helperPath||path.join(root,'resources','update-helper','StarTranslator.Update.exe')
  if(!helperPath&&!await fs.stat(source).then(s=>s.isFile(),()=>false)&&!__dirname.includes('app.asar'))source=path.resolve(__dirname,'../vendor/update-helper/StarTranslator.Update.exe')
  const native=await fs.readFile(source).catch(()=>{throw Error('缺少原生更新辅助程序，请使用本版一次性小更新入口。')})
  const exe=path.join(folder,'StarTranslator.Update.exe');await fs.writeFile(exe,native,{flag:'wx'})
  if(hash(await fs.readFile(exe))!==hash(native))throw Error('原生更新辅助程序复制校验失败。')
  const args=['--sha',hash(bytes)],options={windowsHide:true,stdio:'ignore',detached:true,cwd:process.env.SystemRoot||'C:\\Windows',env:{...process.env}}
  delete options.env.ELECTRON_RUN_AS_NODE
  let failure
  const diagnostic=value=>fs.writeFile(path.join(folder,'launcher.json'),JSON.stringify({native:true,elevate,...value})).catch(()=>{})
  await diagnostic({state:'spawning',helperSha256:hash(native)})
  let child
  try{child=spawnProcess(exe,args,options)}catch(error){await diagnostic({message:error.message,code:error.code,errno:error.errno});await fs.writeFile(path.join(folder,'cancel'),'1');throw Error('原生更新辅助程序未能启动（'+(error.code||error.message)+'），原程序未修改。')}
  child.on('error',e=>{failure=e;diagnostic({message:e.message,code:e.code,errno:e.errno})});child.on('exit',code=>{diagnostic({exitCode:code,hex:(code>>>0).toString(16)});if(code)failure=Error('原生更新辅助程序异常退出（'+code+'），原程序未修改。')});child.unref()
  const deadline=Date.now()+startupTimeout
  try{while(Date.now()<deadline){
    if(await fs.readFile(path.join(folder,'started'),'utf8').catch(()=>null)==='ready'){await diagnostic({state:'ready'});return {started:true,folder}}
    const error=await fs.readFile(path.join(folder,'error.txt'),'utf8').catch(()=>null);if(error)throw Error('增量更新准备失败：'+error)
    if(failure)throw failure
    progress({phase:'installing',progress:85,message:'正在启动更新辅助程序，原程序保持打开…'})
    await new Promise(resolve=>setTimeout(resolve,100))
  }throw Error('更新辅助程序未确认启动，原程序尚未关闭。可重试小包更新；启动诊断已保留。')}
  catch(error){await fs.writeFile(path.join(folder,'cancel'),'1');throw error}
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
