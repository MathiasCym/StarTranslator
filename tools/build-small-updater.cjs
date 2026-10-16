// One-time bridge for releases whose Windows helper used DETACHED_PROCESS.
const fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process')
const {hash}=require('../lib/incremental-update')
async function buildSmallUpdater(patch,{root=path.resolve(__dirname,'..'),output=path.join(root,'dist/incremental')}={}){
 patch={...patch,to:patch.version||patch.to}
 await fs.mkdir(path.join(root,'dist/qa'),{recursive:true})
 const folder=await fs.mkdtemp(path.join(root,'dist/qa','small-updater-'))
 try{
  const payload=path.join(folder,'payload');await fs.mkdir(payload)
  await fs.copyFile(path.join(root,'build/small-update-launcher.js'),path.join(payload,'launch.js'))
  await fs.cp(path.join(root,'lib'),path.join(payload,'lib'),{recursive:true})
  await fs.copyFile(path.join(output,patch.filename),path.join(payload,patch.filename))
  await fs.writeFile(path.join(payload,'update.json'),JSON.stringify(patch))
  const zip=path.join(folder,'payload.zip'),seven=path.join(process.env.ProgramFiles,'7-Zip/7z.exe')
  execFileSync(seven,['a','-tzip',zip,'.','-mx=9'],{cwd:payload,windowsHide:true,stdio:'ignore'})
  const filename=`StarTranslator-SmallUpdate-${patch.from}-to-${patch.to}.exe`,file=path.join(output,filename)
  const compiler=path.join(process.env.SystemRoot,'Microsoft.NET/Framework64/v4.0.30319/csc.exe')
  execFileSync(compiler,['/nologo','/target:winexe','/platform:x64','/optimize+',`/out:${file}`,`/resource:${zip},payload.zip`,'/win32icon:'+path.join(root,'build/icon.ico'),
   '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',path.join(root,'build/small-update-launcher.cs')],{windowsHide:true,encoding:'utf8'})
  const bytes=await fs.readFile(file);return {filename,size:bytes.length,sha256:hash(bytes),from:patch.from,to:patch.to}
 }finally{
  if(path.dirname(folder)!==path.join(root,'dist/qa'))throw Error('Unsafe small-updater build cleanup')
  await fs.rm(folder,{recursive:true,force:true})
 }
}
module.exports={buildSmallUpdater}
