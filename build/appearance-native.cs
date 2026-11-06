using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

// Shared paint for the two native update windows; update behavior is unchanged.
static class AppearancePaint {
    public class Preference { public string theme; }
    [DllImport("uxtheme.dll", CharSet=CharSet.Unicode)] static extern int SetWindowTheme(IntPtr handle,string app,string id);
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr handle,int message,IntPtr w,IntPtr l);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr handle,int attribute,ref int value,int size);
    public static bool Light(string data) {
        try {
            if(String.IsNullOrEmpty(data))return false;
            string file=Path.Combine(data,"appearance.json");if(!File.Exists(file)||new FileInfo(file).Length>16384)return false;
            Preference preference=new JavaScriptSerializer().Deserialize<Preference>(File.ReadAllText(file));
            return preference!=null&&preference.theme=="light";
        } catch { return false; }
    }
    public static void Apply(Form form,ProgressBar bar,string data) {
        if(!Light(data))return;
        form.BackColor=Color.White;form.ForeColor=Color.Black;
        try {int dark=0;DwmSetWindowAttribute(form.Handle,20,ref dark,4);} catch {}
        bar.BackColor=Color.FromArgb(249,244,230);bar.ForeColor=Color.FromArgb(194,157,72);
        try {SetWindowTheme(bar.Handle,"","");SendMessage(bar.Handle,0x409,IntPtr.Zero,(IntPtr)ColorTranslator.ToWin32(bar.ForeColor));SendMessage(bar.Handle,0x2001,IntPtr.Zero,(IntPtr)ColorTranslator.ToWin32(bar.BackColor));} catch {}
    }
}
