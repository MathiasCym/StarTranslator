using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Drawing;
using Microsoft.Win32;
using System.Reflection;
using System.Runtime.InteropServices;

// GUI subsystem: no ConsoleHost, cmd START, PowerShell or script execution.
class PatchHelper {
 public class Entry {public string path,stage,sha256;public long size;}
 public class Manifest {public string version;public Entry[] files;}
 public class Plan {public int schema,parentPid;public string from,to,id,root,folder,baseManifest,userData;public bool restart,elevated,showProgress,registerRecovery;public Manifest @base,target;public Entry[] changed;public string[] removed;}
 static JavaScriptSerializer json=new JavaScriptSerializer(){MaxJsonLength=16*1024*1024};
 static Plan plan;static string folder,root,transaction,runName,planFile,planHash;
 static List<Entry> all;static Form form;static Label label;static ProgressBar bar;
 static bool mutating,closed,success,canRestart,conflict;static FileStream locked;
 static string Sha(string p){using(var s=File.OpenRead(p))using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(s)).Replace("-","").ToLowerInvariant();}
 static void Write(string name,object value){File.WriteAllText(Path.Combine(folder,name),value is string?(string)value:json.Serialize(value),new UTF8Encoding(false));}
 static bool Cancelled(){return File.Exists(Path.Combine(folder,"cancel"));}
 static void Progress(string phase,int done,int total,string message){
  Write("progress.json",new{phase,done,total,message});
  if(form!=null){label.Text=message;bar.Value=Math.Min(100,Math.Max(0,(int)(100.0*done/Math.Max(1,total))));Application.DoEvents();}
  if(Cancelled())throw new IOException("更新准备已取消，原程序保持不变。");
 }
 static string Safe(string relative){
  if(String.IsNullOrEmpty(relative)||Path.IsPathRooted(relative)||Regex.IsMatch(relative,@"[\\:\x00-\x1f]")||relative.Split('/').Any(s=>s==""||s=="."||s==".."||s.EndsWith(".")||s.EndsWith(" ")))throw new IOException("更新路径无效。");
  string p=Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));
  if(!p.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("更新路径超出安装目录。");
  for(string probe=p;probe!=null&&probe.Length>=root.Length;probe=Path.GetDirectoryName(probe))
   if((File.Exists(probe)||Directory.Exists(probe))&&(File.GetAttributes(probe)&FileAttributes.ReparsePoint)!=0)throw new IOException("更新目标包含目录链接。");
  return p;
 }
 static void Check(string file,Entry e){if(!File.Exists(file)||new FileInfo(file).Length!=e.size||Sha(file)!=e.sha256)throw new IOException("程序文件校验失败："+e.path);}
 static bool Cache(string p){return Regex.IsMatch(p,@"(^|/)__pycache__/|\.py[co]$");}
 static void CheckBase(bool progress){int n=0;foreach(var e in plan.@base.files){if(!Cache(e.path))Check(Safe(e.path),e);if(progress)Progress("verify",++n,plan.@base.files.Length,"正在验证原程序 "+n+" / "+plan.@base.files.Length);}}
 static void CheckTarget(){int n=0;foreach(var e in plan.target.files){Check(Safe(e.path),e);Progress("check",++n,plan.target.files.Length,"正在校验更新完整性 "+n+" / "+plan.target.files.Length);}}
 static void RemoveRecovery(){if(!plan.registerRecovery)return;using(var k=Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\RunOnce",true)){if(k!=null)k.DeleteValue(runName,false);}}
 static string Arg(string s){return "\""+s.Replace("\"","")+"\"";}
 static void RegisterRecovery(){
  if(!plan.registerRecovery)return;
  string cmd=Arg(Application.ExecutablePath)+" --sha "+planHash+" --recover";
  if(cmd.Length>260)throw new IOException("更新恢复路径过长，请使用小更新入口或完整安装包。");
  using(var k=Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\RunOnce"))k.SetValue(runName,cmd,RegistryValueKind.String);
 }
 static void OpenProgress(){if(!plan.showProgress)return;try{
  form=new Form(){Text="星译官 · 更新",Width=520,Height=185,StartPosition=FormStartPosition.CenterScreen,FormBorderStyle=FormBorderStyle.FixedDialog,ControlBox=false,BackColor=Color.FromArgb(12,29,46),ForeColor=Color.FromArgb(220,237,250),Font=new Font("Microsoft YaHei UI",10)};
  try{form.Icon=Icon.ExtractAssociatedIcon(Path.Combine(root,"星译官.exe"));}catch{}
  label=new Label(){Left=24,Top=24,Width=460,Height=48};bar=new ProgressBar(){Left=24,Top=88,Width=460,Height=16};form.Controls.Add(label);form.Controls.Add(bar);form.Show();Application.DoEvents();
 }catch{form=null;}}
 static void Restore(){
  for(int i=all.Count-1;i>=0;i--){var e=all[i];string dest=Safe(e.path),backup=Path.Combine(transaction,"old-"+i);
   if(File.Exists(backup)){if(File.Exists(dest))File.Delete(dest);Directory.CreateDirectory(Path.GetDirectoryName(dest));File.Move(backup,dest);}
   else if(e.path!="resources/install-manifest.json"&&!plan.@base.files.Any(b=>b.path==e.path)&&File.Exists(dest)){Check(dest,e);File.Delete(dest);}
  }
 }
 static bool Busy(){int own=Process.GetCurrentProcess().Id;foreach(var p in Process.GetProcesses()){try{if(p.Id==own)continue;string file=p.MainModule.FileName;if(file.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))return true;}catch{}finally{p.Dispose();}}return false;}
 static void Restart(){
  if(!closed||!canRestart||!plan.restart||Cancelled())return;
  string exe=Path.Combine(root,"星译官.exe");if(!File.Exists(exe))return;
  string arguments=String.IsNullOrEmpty(plan.userData)?"":"--user-data-dir="+Arg(plan.userData);
  try{if(plan.elevated){object shell=Activator.CreateInstance(Type.GetTypeFromProgID("Shell.Application"));try{shell.GetType().InvokeMember("ShellExecute",BindingFlags.InvokeMethod,null,shell,new object[]{exe,arguments,root,"open",1});}finally{Marshal.FinalReleaseComObject(shell);}}
   else Process.Start(new ProcessStartInfo(exe,arguments){WorkingDirectory=root,UseShellExecute=true});
  }catch{Write("restart.txt","更新已完成，请手动重新打开星译官。");}
 }
 static void Validate(){
  if(plan==null||plan.schema!=1||!Regex.IsMatch(plan.from??"",@"^\d+\.\d+\.\d+$")||!Regex.IsMatch(plan.to??"",@"^\d+\.\d+\.\d+$")||!Regex.IsMatch(plan.id??"",@"^[a-f0-9-]{36}$"))throw new IOException("更新计划无效。");
  if(!String.Equals(Path.GetFullPath(plan.folder),folder,StringComparison.OrdinalIgnoreCase))throw new IOException("更新工作目录不一致。");
  root=Path.GetFullPath(plan.root).TrimEnd(Path.DirectorySeparatorChar);if(!Directory.Exists(root))throw new IOException("安装目录不存在。");
  transaction=Path.Combine(root,".star-update-"+plan.id);runName="StarTranslatorUpdate-"+plan.id;
  all=plan.changed.Concat((plan.removed??new string[0]).Select(p=>new Entry(){path=p})).ToList();
  var paths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
  foreach(var e in all){Safe(e.path);if(!paths.Add(e.path))throw new IOException("更新计划中存在重复路径。");}
  foreach(var e in plan.changed)if(!Regex.IsMatch(e.stage??"",@"^\d+$")||!Regex.IsMatch(e.sha256??"",@"^[a-f0-9]{64}$")||e.size<0)throw new IOException("更新暂存清单无效。");
  if(plan.@base==null||plan.target==null||plan.@base.version!=plan.from||plan.target.version!=plan.to||plan.@base.files==null||plan.target.files==null)throw new IOException("更新版本不一致。");
 }
 static void Run(bool recover){
  Validate();if(Cancelled())throw new IOException("更新准备已取消。");
  if(plan.elevated&&!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)){
   try{Process.Start(new ProcessStartInfo(Application.ExecutablePath,"--plan "+Arg(planFile)+" --sha "+planHash+(recover?" --recover":"")){UseShellExecute=true,Verb="runas",WindowStyle=ProcessWindowStyle.Hidden});return;}
   catch(System.ComponentModel.Win32Exception e){Write("error.txt",e.NativeErrorCode==1223?"管理员授权已取消（1223），原程序保持不变。":"更新辅助程序启动失败（"+e.NativeErrorCode+"）："+e.Message);return;}
  }
  Write("worker.pid",Process.GetCurrentProcess().Id.ToString());Progress("starting",0,1,"正在启动原生更新辅助程序");
  try{
   if(recover){closed=true;if(File.Exists(Path.Combine(transaction,"committed"))){CheckTarget();success=true;}else if(File.Exists(Path.Combine(transaction,"applying"))){Restore();CheckBase(false);canRestart=true;}}
   else{
    Write("started","ready");
    if(plan.parentPid>0){try{using(var p=Process.GetProcessById(plan.parentPid))if(!p.WaitForExit(120000))throw new IOException("星译官尚未关闭，未替换任何文件。");}catch(ArgumentException){}}
    closed=true;OpenProgress();Progress("verify",0,plan.@base.files.Length,"正在验证原程序，即将应用小包更新");
    if(Sha(Safe("resources/install-manifest.json"))!=plan.baseManifest)throw new IOException("安装版本已改变。");
    CheckBase(true);foreach(var e in plan.changed)Check(Path.Combine(folder,e.stage),e);
    Progress("prepare",0,1,"正在准备安全替换与恢复资料");
    try{locked=new FileStream(Safe(".star-update.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);}catch(IOException){conflict=true;throw new IOException("已有更新正在进行，请等待其完成后再打开星译官。");}
    if(Directory.Exists(transaction))throw new IOException("更新事务目录已存在，请重试。");Directory.CreateDirectory(transaction);
    foreach(var e in plan.changed){string dest=Path.Combine(transaction,"new-"+e.stage);File.Copy(Path.Combine(folder,e.stage),dest,false);Check(dest,e);}
    Progress("recovery",0,1,"正在登记更新恢复信息");RegisterRecovery();
    Progress("closing",0,1,"正在等待程序文件释放");var wait=Stopwatch.StartNew();while(Busy()){if(wait.ElapsedMilliseconds>15000){conflict=true;throw new IOException("安装目录仍有程序使用，请关闭其他星译官窗口后重试。");}System.Threading.Thread.Sleep(100);}
    if(Sha(Safe("resources/install-manifest.json"))!=plan.baseManifest)throw new IOException("安装版本已改变。");CheckBase(false);
    foreach(var e in plan.changed)if(e.path!="resources/install-manifest.json"&&!plan.@base.files.Any(b=>b.path==e.path)&&File.Exists(Safe(e.path)))throw new IOException("新增文件与已有文件冲突。");
    File.WriteAllText(Path.Combine(transaction,"applying"),"1");mutating=true;
    for(int i=0;i<all.Count;i++){
#if UPDATE_HELPER_TESTS
     if(Environment.GetEnvironmentVariable("STAR_PATCH_TEST_FAIL_AFTER")==i.ToString())throw new IOException("Injected native write failure");
#endif
     var e=all[i];string dest=Safe(e.path);Progress("apply",i,all.Count,"正在更新程序文件 "+(i+1)+" / "+all.Count);if(File.Exists(dest))File.Move(dest,Path.Combine(transaction,"old-"+i));if(e.stage!=null){Directory.CreateDirectory(Path.GetDirectoryName(dest));File.Move(Path.Combine(transaction,"new-"+e.stage),dest);}}
    CheckTarget();File.WriteAllText(Path.Combine(transaction,"committed"),"1");success=true;
   }
   if(success){Progress("complete",1,1,"更新完成，正在重新打开星译官");canRestart=true;
    foreach(var hive in new[]{Registry.CurrentUser,Registry.LocalMachine})try{using(var key=hive.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\40dcc9aa-3b67-5e68-9a54-dc7e46ccf86d",true)){if(key!=null&&String.Equals((key.GetValue("InstallLocation") as string??"").TrimEnd('\\'),root,StringComparison.OrdinalIgnoreCase))key.SetValue("DisplayVersion",plan.to);}}catch{}
   }
   Write("result.json",new{complete=success,rolledBack=!success});bool recoveryRemoved=false;try{RemoveRecovery();recoveryRemoved=true;}catch{Write("cleanup.txt","更新已完成，恢复登记清理待重试。");}
   if(success&&recoveryRemoved)try{Directory.Delete(transaction,true);}catch{}
  }catch(Exception error){
   string message=error.Message;
   if(mutating){try{Restore();CheckBase(false);canRestart=true;message="更新失败，原程序已恢复。"+message;}catch(Exception rollback){canRestart=false;message="自动恢复未完成，请使用完整安装包修复。"+message+" "+rollback.Message;}}
   else if(closed&&!conflict)canRestart=true;
   if(Cancelled())canRestart=false;
   if(canRestart)try{RemoveRecovery();}catch{}
   Write("error.txt",message);Write("result.json",new{complete=false,requiresFull=mutating&&!canRestart});
   if(plan.showProgress&&closed&&!Cancelled())MessageBox.Show("更新未完成，原程序已保留或恢复。\n"+message,"星译官 · 更新未完成");
  }finally{if(form!=null){form.Close();form.Dispose();}if(locked!=null)locked.Dispose();Restart();}
 }
 [STAThread] static int Main(string[] args){
  try{
   for(int i=0;i<args.Length;i++){if(args[i]=="--plan"&&i+1<args.Length)planFile=Path.GetFullPath(args[++i]);else if(args[i]=="--sha"&&i+1<args.Length)planHash=args[++i];}
   if(planFile==null)planFile=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"plan.json");
   if(!Regex.IsMatch(planHash??"",@"^[a-f0-9]{64}$")||Sha(planFile)!=planHash)throw new IOException("更新计划校验失败。");
   folder=Path.GetDirectoryName(planFile);plan=json.Deserialize<Plan>(File.ReadAllText(planFile,Encoding.UTF8));Run(args.Contains("--recover"));return 0;
  }catch(Exception e){try{if(folder!=null)Write("error.txt","原生更新辅助程序："+e.Message);}catch{}return 1;}
 }
}
