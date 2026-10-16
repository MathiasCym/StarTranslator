using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;
using Microsoft.Win32;

class SmallUpdate {
    static string FindRoot() {
        foreach(RegistryKey hive in new[]{Registry.CurrentUser,Registry.LocalMachine}) {
            using(RegistryKey key=hive.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\40dcc9aa-3b67-5e68-9a54-dc7e46ccf86d")) {
                string value=key==null?null:key.GetValue("InstallLocation") as string;
                if(Valid(value))return value;
            }
        }
        string desktop=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"StarTranslator");
        if(Valid(desktop))return desktop;
        using(FolderBrowserDialog dialog=new FolderBrowserDialog()) {
            dialog.Description="请选择星译官的安装文件夹";
            if(dialog.ShowDialog()==DialogResult.OK&&Valid(dialog.SelectedPath))return dialog.SelectedPath;
        }
        throw new Exception("未找到有效的星译官安装。原程序未修改。");
    }
    static bool Valid(string path) {return !String.IsNullOrEmpty(path)&&File.Exists(Path.Combine(path,"星译官.exe"))&&File.Exists(Path.Combine(path,@"resources\install-manifest.json"));}
    static bool Busy(string root) {
        foreach(Process process in Process.GetProcessesByName("星译官")) {
            try {if(String.Equals(Path.GetDirectoryName(process.MainModule.FileName).TrimEnd('\\'),root.TrimEnd('\\'),StringComparison.OrdinalIgnoreCase))return true;}catch{return true;}finally{process.Dispose();}
        }
        return false;
    }
    [STAThread] static int Main(string[] args) {
        string folder=null;
        try{Console.OutputEncoding=new System.Text.UTF8Encoding(false);}catch{}
        Application.EnableVisualStyles();
        try {
            string root=Path.GetFullPath(args.Length>0?args[0]:FindRoot());
            if(!Valid(root))throw new Exception("所选文件夹不是有效的星译官安装。");
            while(Busy(root)) {
                if(Array.IndexOf(args,"--no-progress")>=0)throw new Exception("The test installation is still in use");
                if(MessageBox.Show("请先退出星译官，再点击“重试”。已下载的小包会继续使用，无需完整安装包。","星译官 · 小包更新",MessageBoxButtons.RetryCancel,MessageBoxIcon.Information)!=DialogResult.Retry)return 1;
            }
            folder=Path.Combine(Path.GetTempPath(),"StarTranslatorSmallUpdate-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);
            using(Stream stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))using(ZipArchive archive=new ZipArchive(stream)) {
                foreach(ZipArchiveEntry entry in archive.Entries) {
                    string dest=Path.GetFullPath(Path.Combine(folder,entry.FullName));
                    if(!dest.StartsWith(folder+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("更新资源路径无效。");
                    if(String.IsNullOrEmpty(entry.Name)){Directory.CreateDirectory(dest);continue;}
                    Directory.CreateDirectory(Path.GetDirectoryName(dest));entry.ExtractToFile(dest);
                }
            }
            using(Form form=new Form())using(Label label=new Label())using(ProgressBar bar=new ProgressBar()) {
                form.Text="星译官 · 小包更新";form.ClientSize=new Size(490,135);form.StartPosition=FormStartPosition.CenterScreen;form.FormBorderStyle=FormBorderStyle.FixedDialog;form.ControlBox=false;
                form.Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
                form.BackColor=Color.FromArgb(12,29,46);form.ForeColor=Color.FromArgb(220,237,250);form.Font=new Font("Microsoft YaHei UI",10);
                if(Array.IndexOf(args,"--no-progress")>=0){form.Opacity=0;form.ShowInTaskbar=false;}
                label.Text="正在校验并合成小包更新，请稍候…\r\n更新完成后将自动重新打开星译官。";label.SetBounds(24,22,450,54);bar.Style=ProgressBarStyle.Marquee;bar.SetBounds(24,92,442,14);form.Controls.Add(label);form.Controls.Add(bar);
                ProcessStartInfo info=new ProcessStartInfo(Path.Combine(root,"星译官.exe"),"\""+Path.Combine(folder,"launch.js")+"\" \""+root+"\""+(args.Length>1?" \""+args[1]+"\"":"")+(Array.IndexOf(args,"--no-restart")>=0?" --no-restart":"")+(Array.IndexOf(args,"--no-progress")>=0?" --no-progress":""));
                info.UseShellExecute=false;info.CreateNoWindow=true;info.WorkingDirectory=folder;info.RedirectStandardError=true;info.EnvironmentVariables["ELECTRON_RUN_AS_NODE"]="1";
                using(Process child=new Process()) {
                    child.StartInfo=info;child.Start();string error="";
                    child.ErrorDataReceived+=(sender,eventArgs)=>{if(eventArgs.Data!=null)error=(error+eventArgs.Data+"\n");};child.BeginErrorReadLine();
                    Timer timer=new Timer();timer.Interval=200;timer.Tick+=(sender,eventArgs)=>{if(child.HasExited)form.Close();};timer.Start();Application.Run(form);timer.Dispose();child.WaitForExit();
                    if(child.ExitCode!=0)throw new Exception(String.IsNullOrWhiteSpace(error)?"小包更新未能启动，原程序未修改。":error.Substring(Math.Max(0,error.Length-900)));
                }
            }
            return 0;
        } catch(Exception error) {if(Array.IndexOf(args,"--no-progress")>=0)Console.Error.WriteLine(error.Message);else MessageBox.Show(error.Message,"星译官 · 更新未完成",MessageBoxButtons.OK,MessageBoxIcon.Warning);return 1;}
        finally {if(folder!=null&&Path.GetDirectoryName(folder)==Path.GetTempPath().TrimEnd(Path.DirectorySeparatorChar)&&Path.GetFileName(folder).StartsWith("StarTranslatorSmallUpdate-"))try{Directory.Delete(folder,true);}catch{}}
    }
}
