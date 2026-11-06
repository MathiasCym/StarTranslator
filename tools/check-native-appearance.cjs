// Draw the production native paint in isolation, without running an updater.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process')
if(process.platform!=='win32')throw Error('Native appearance acceptance requires Windows')
const root=path.resolve(__dirname,'..'),qa=path.join(root,'dist/qa/native-appearance');fs.mkdirSync(qa,{recursive:true})
const source=path.join(qa,'paint.cs'),exe=path.join(qa,'paint.exe')
fs.writeFileSync(source,`using System;using System.IO;using System.Drawing;using System.Windows.Forms;
class PaintQA {
 [STAThread] static void Main(string[] args){Application.EnableVisualStyles();
  foreach(string mode in new[]{"dark","light"}){
   string data=Path.Combine(args[0],mode);Directory.CreateDirectory(data);File.WriteAllText(Path.Combine(data,"appearance.json"),"{\\"theme\\":\\""+mode+"\\"}");
   using(Form form=new Form()){form.Text="星译官 · 更新";form.Width=520;form.Height=185;form.BackColor=Color.FromArgb(12,29,46);form.ForeColor=Color.FromArgb(220,237,250);form.Font=new Font("Microsoft YaHei UI",10);
    ProgressBar bar=new ProgressBar(){Left=24,Top=88,Width=460,Height=16,Value=65};Label label=new Label(){Left=24,Top=24,Width=460,Height=48,Text="正在应用已校验的小更新，完成后自动重启…"};form.Controls.Add(label);form.Controls.Add(bar);
    AppearancePaint.Apply(form,bar,data);form.Show();Application.DoEvents();
    if(mode=="light"&&(form.BackColor!=Color.White||label.ForeColor!=Color.Black))throw new Exception("Native light colors do not propagate");
    if(mode=="dark"&&form.BackColor!=Color.FromArgb(12,29,46))throw new Exception("Dark default changed");
    using(Bitmap bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,bitmap.Size));bitmap.Save(Path.Combine(args[0],mode+".png"));}
    form.Close();
   }
  }
  File.WriteAllText(Path.Combine(args[0],"appearance.json"),"invalid");if(AppearancePaint.Light(args[0]))throw new Exception("Corrupt preference must default dark");
 }
}`)
const compiler=path.join(process.env.SystemRoot,'Microsoft.NET/Framework64/v4.0.30319/csc.exe')
execFileSync(compiler,['/nologo','/target:winexe','/out:'+exe,'/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',source,path.join(root,'build/appearance-native.cs')],{windowsHide:true})
execFileSync(exe,[qa],{windowsHide:true,timeout:15000})
for(const theme of ['dark','light'])assert(fs.statSync(path.join(qa,theme+'.png')).size>1000)
fs.writeFileSync(path.join(qa,'result.json'),JSON.stringify({passed:true,productionPaint:true,installationModified:false,checks:['Dark unchanged','Light form, labels and progress','Corrupt preference defaults dark']},null,2))
console.log('Native appearance checks passed')
