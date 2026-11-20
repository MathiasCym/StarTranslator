// Draw the production native paint in isolation, without running an updater.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process')
if(process.platform!=='win32')throw Error('Native appearance acceptance requires Windows')
const root=path.resolve(__dirname,'..'),qa=path.join(root,'dist/qa/native-appearance');fs.mkdirSync(qa,{recursive:true})
const source=path.join(qa,'paint.cs'),exe=path.join(qa,'paint.exe')
fs.writeFileSync(source,`using System;using System.IO;using System.Drawing;using System.Windows.Forms;
class PaintQA {
 [STAThread] static void Main(string[] args){Application.EnableVisualStyles();
  using(var form=new UpdateProgressWindow(null,"v2.4.9 → v2.5.0",true)){
    form.Report("正在更新程序文件 7 / 9",73);
    Capture(form,Path.Combine(args[0],"update.png"));
    form.Report("正在重新打开星译官",100);
    Capture(form,Path.Combine(args[0],"update-complete.png"));
  }
  using(var form=new UpdateProgressWindow(null,"",true)){
    form.Report("正在校验并准备小包更新",null);
    Capture(form,Path.Combine(args[0],"update-prepare.png"));
  }
 }
 static void Capture(Form form,string target){
   form.Opacity=0;
   form.Show();
   Application.DoEvents();
   foreach(Control control in form.Controls)
    if(control.Visible&&!form.ClientRectangle.Contains(control.Bounds))throw new Exception("Update control outside window: "+control.Text);
   using(Bitmap bitmap=new Bitmap(form.ClientSize.Width,form.ClientSize.Height)){
    // Keep the renderer off the desktop and trim the OS-owned title frame.
    using(Bitmap window=new Bitmap(form.Width,form.Height)){
     form.DrawToBitmap(window,new Rectangle(Point.Empty,window.Size));
     using(Graphics g=Graphics.FromImage(bitmap)){
      int x=(form.Width-form.ClientSize.Width)/2;
      int y=form.Height-form.ClientSize.Height-x;
      g.DrawImage(window,new Rectangle(Point.Empty,bitmap.Size),new Rectangle(x,y,bitmap.Width,bitmap.Height),GraphicsUnit.Pixel);
     }
    }
    bool accentVisible=false;
    for(int y=0;y<bitmap.Height&&!accentVisible;y++)
     for(int x=0;x<bitmap.Width&&!accentVisible;x++)
      accentVisible=bitmap.GetPixel(x,y).ToArgb()==Color.FromArgb(241,183,67).ToArgb();
    if(!accentVisible)throw new Exception("The update window did not paint its controls");
    bitmap.Save(target);
   }
 }
}`)
const compiler=path.join(process.env.SystemRoot,'Microsoft.NET/Framework64/v4.0.30319/csc.exe')
execFileSync(compiler,['/nologo','/target:winexe','/out:'+exe,'/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',source,path.join(root,'build/appearance-native.cs')],{windowsHide:true})
execFileSync(exe,[qa],{windowsHide:true,timeout:15000})
for(const name of ['update.png','update-complete.png','update-prepare.png']) assert(fs.statSync(path.join(qa,name)).size>1000)
fs.writeFileSync(path.join(qa,'result.json'),JSON.stringify({passed:true,productionPaint:true,installationModified:false,checks:['Dark native update, completion and preparation views']},null,2))
console.log('Native appearance checks passed')
