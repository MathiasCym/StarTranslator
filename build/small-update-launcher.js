// The one-time small updater runs under the already installed Electron runtime.
// It repairs old ConsoleHost launch behavior without downloading another runtime.
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto')
async function run(){
  const metadata=JSON.parse(await fs.readFile(path.join(__dirname,'update.json'),'utf8'))
  const root=path.resolve(process.argv[2]),userData=process.argv[3]?path.resolve(process.argv[3]):require('./lib/user-data-path').resolveExisting(process.env.APPDATA)
  const manifest=JSON.parse(await fs.readFile(path.join(root,'resources/install-manifest.json'),'utf8'))
  if(manifest.version!==metadata.from)throw Error('此小包仅适用于 '+metadata.from+'，当前安装为 '+manifest.version+'。')
  if(!/^StarTranslator-Patch-\d+\.\d+\.\d+-to-\d+\.\d+\.\d+\.stpatch$/.test(metadata.filename))throw Error('更新包名称无效。')
  const bytes=await fs.readFile(path.join(__dirname,metadata.filename))
  if(bytes.length!==metadata.size||crypto.createHash('sha256').update(bytes).digest('hex')!==metadata.sha256)throw Error('小包校验未通过，原程序未修改。')
  const folder=path.join(userData,'updates');await fs.mkdir(folder,{recursive:true})
  const file=path.join(folder,metadata.filename);await fs.writeFile(file,bytes)
  await fs.writeFile(path.join(folder,'ready.json'),JSON.stringify({...metadata,version:metadata.to,kind:'patch',source:'atomgit'}))
  // Do not pass Node mode to PowerShell or the restarted desktop application.
  delete process.env.ELECTRON_RUN_AS_NODE
  await require('./lib/patch-worker').launchPatch({file,root,currentVersion:metadata.from,userData,
    restart:!process.argv.includes('--no-restart'),showProgress:!process.argv.includes('--no-progress')})
}
run().catch(error=>{process.stderr.write(String(error.message)+'\n');process.exitCode=1})
