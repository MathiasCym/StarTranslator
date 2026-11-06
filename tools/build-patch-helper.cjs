const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process')
function build({output=path.resolve(__dirname,'../vendor/update-helper/StarTranslator.Update.exe'),testing=false}={}){
 fs.mkdirSync(path.dirname(output),{recursive:true})
 execFileSync(path.join(process.env.SystemRoot,'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),['/nologo','/target:winexe','/platform:x64','/optimize+','/out:'+output,...(testing?['/define:UPDATE_HELPER_TESTS']:[]),'/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',path.resolve(__dirname,'../build/patch-helper.cs'),path.resolve(__dirname,'../build/appearance-native.cs')],{windowsHide:true,stdio:'pipe'})
 return output
}
if(require.main===module){try{console.log(build())}catch(e){console.error(e.stdout?.toString()||e.message);process.exitCode=1}}
module.exports={build}
