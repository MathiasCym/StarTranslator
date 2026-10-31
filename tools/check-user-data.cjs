// Exercise startup migration through the real Electron entry and Python API.
const runtime=require('electron')
if(typeof runtime==='string'){
 const {spawnSync}=require('node:child_process'),path=require('node:path')
 const run=spawnSync(runtime,[__filename,process.argv[2]||path.resolve(__dirname,'..')],{windowsHide:true,encoding:'utf8',timeout:70000})
 process.stdout.write(run.stdout||'');process.stderr.write(run.stderr||'');if(run.error)console.error(run.error.message);process.exit(run.status??1)
}
const {app,BrowserWindow,ipcMain}=runtime,fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process')
const target=path.resolve(process.argv[2]),root=path.resolve(__dirname,'..')
fs.mkdirSync(path.join(root,'dist/qa'),{recursive:true})
const qa=fs.mkdtempSync(path.join(root,'dist/qa','data-migration-'))
const legacy=path.join(qa,'novaterm-checker'),current=path.join(qa,'StarTranslator'),result={passed:false,target,companyDocumentsSent:false,existingProfileModified:false}
fs.mkdirSync(legacy);fs.mkdirSync(current) // Actual upgrades may already have an empty branded directory.
app.setPath('appData',qa);app.setPath('userData',current)
BrowserWindow.prototype.show=function(){}
app.getVersion=()=>JSON.parse(fs.readFileSync(path.join(target,'package.json'))).version
if(target.endsWith('.asar'))Object.defineProperty(process,'resourcesPath',{value:path.dirname(target),configurable:true})
const python=target.endsWith('.asar')?path.join(process.resourcesPath,'python-runtime/python.exe'):path.join(root,'python-runtime/python.exe')
const backendRoot=target.endsWith('.asar')?target.replace('app.asar','app.asar.unpacked'):target
const env={...process.env,NOVATERM_DATA_DIR:legacy,PYTHONDONTWRITEBYTECODE:'1'}
execFileSync(python,['-X','utf8','-B','-c',`import sys;sys.path.insert(0,${JSON.stringify(backendRoot)});from backend.glossary import store;store.read()`],{env,windowsHide:true})
const wait=ms=>new Promise(r=>setTimeout(r,ms)),timeout=setTimeout(()=>app.exit(2),60000)
const server=http.createServer((_req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({data:[{id:'ui-only'}]}))})
server.listen(0,'127.0.0.1',async()=>{
 try{
  const base=`http://127.0.0.1:${server.address().port}/v1`
  env.NOVATERM_LLM_BASE_URL=base
  execFileSync(python,['-X','utf8','-B','-c',`import sys,os;sys.path.insert(0,${JSON.stringify(backendRoot)});from backend import model_profiles;p=model_profiles.save_profile(dict(name='Migration fixture',provider='compatible',base_url=os.environ['NOVATERM_LLM_BASE_URL'],model='ui-only',api_key='migration-fixture-key'));model_profiles.activate(p['profile']['id'])`],{env,windowsHide:true})
  fs.mkdirSync(path.join(legacy,'comparisons'));fs.writeFileSync(path.join(legacy,'comparisons/saved.json'),'retained comparison')
  fs.writeFileSync(path.join(legacy,'history-fixture.json'),JSON.stringify({path:path.join(legacy,'comparisons/saved.json')}))
  fs.writeFileSync(path.join(legacy,'lexicon-settings.json'),JSON.stringify({path:path.join(legacy,'lexicon.json')}))
  const files=['lexicon.json','model-profiles.json','model-settings.json','history-fixture.json'],before=Object.fromEntries(files.map(name=>[name,fs.readFileSync(path.join(legacy,name))]))
  require(path.join(target,'main.js'))
  ipcMain.removeHandler('startup-update-notice');ipcMain.handle('startup-update-notice',()=>null)
  await app.whenReady()
  let win
  for(let i=0;i<250;i++){win=BrowserWindow.getAllWindows().find(w=>w.webContents.getURL().endsWith('/renderer/index.html'));if(win&&await win.webContents.executeJavaScript('typeof initialized!=="undefined"&&initialized').catch(()=>false))break;await wait(100)}
  assert(win,'Actual main window must open');const run=code=>win.webContents.executeJavaScript(code)
  assert.equal(app.getPath('userData'),current);assert(fs.lstatSync(legacy).isSymbolicLink())
  for(const name of files)assert.deepEqual(fs.readFileSync(path.join(current,name)),before[name],name+' must retain exact bytes')
  const library=await run("callApi('GET','/api/lexicon')");assert.equal(library.path,path.join(current,'lexicon.json'));assert.equal(library.entries.length,2515)
  const profiles=await run("callApi('GET','/api/model/profiles')");assert.equal(profiles.profiles.length,1);assert(profiles.profiles[0].has_key)
  assert.equal(fs.readFileSync(JSON.parse(fs.readFileSync(path.join(current,'history-fixture.json'))).path,'utf8'),'retained comparison')
  result.profileCount=profiles.profiles.length;result.termCount=library.entries.length;result.migratedPath=library.path;result.exactFiles=files;result.passed=true
 }catch(error){result.error=error.stack}
 finally{fs.writeFileSync(path.join(qa,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));clearTimeout(timeout);server.closeAllConnections();server.close();app.emit('will-quit');app.exit(result.passed?0:1)}
})
