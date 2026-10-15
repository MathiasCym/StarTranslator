// Run with Node; the worker uses a hidden offscreen Electron window and isolated data.
const runtime=require('electron')
if(typeof runtime==='string') {
 const path=require('node:path'),fs=require('node:fs'),{spawnSync}=require('node:child_process')
 const task=spawnSync(runtime,[__filename],{cwd:path.resolve(__dirname,'..'),windowsHide:true,timeout:150000,encoding:'utf8'})
 const file=path.resolve(__dirname,'../dist/qa/readability/readable-206-result.json')
 if(task.error)console.error(task.error.message)
 if(fs.existsSync(file)){const value=JSON.parse(fs.readFileSync(file));console.log(value.passed?'Desktop readability and dialog checks passed':value.error||'UI checks did not finish')}
 process.exit(task.status??1)
}
const {app,BrowserWindow,ipcMain}=require('electron'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict')
const root=path.resolve(__dirname,'..'),qaDir=path.join(root,'dist','qa','readability'),wait=ms=>new Promise(r=>setTimeout(r,ms)),result={passed:false,checks:[],screenshots:[],companyDocumentsSent:false}
fs.mkdirSync(qaDir,{recursive:true})
app.setPath('userData',path.join(qaDir,'readable-206-profile'));BrowserWindow.prototype.show=function(){}
app.getVersion=()=>JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version
app.commandLine.appendSwitch('disable-renderer-backgrounding')
app.on('browser-window-created',(_event,win)=>win.webContents.setBackgroundThrottling(false))
let notices=0,ignored=[],updateChecks=0
let sharedJobs=[],sharedResumes=0
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost').pathname
 res.setHeader('Content-Type',url.endsWith('.css')?'text/css':url.endsWith('.js')?'text/javascript':url.endsWith('.png')?'image/png':'text/html')
 if(url==='/v1/models')return res.end(JSON.stringify({data:[{id:'ui-only'}]}))
 if(url==='/shared/session')return res.end(JSON.stringify({csrf:'ui-only'}))
 if(url==='/shared/jobs')return res.end(JSON.stringify({jobs:sharedJobs}))
 if(url==='/shared/jobs/shared-resume-fixture/resume'){
  sharedResumes++;const restored={id:'shared-restored-fixture',kind:'translate',status:'running',message:'继续翻译',percent:60,downloads:[]}
  sharedJobs=[restored];return res.end(JSON.stringify(restored))
 }
 const file=url==='/'?path.join(root,'renderer/shared/index.html'):url.startsWith('/assets/')?path.join(root,'renderer',url.slice(1)):path.join(root,'renderer/shared',path.basename(url))
 if(fs.existsSync(file))res.end(fs.readFileSync(file));else{res.statusCode=404;res.end('unavailable')}
})
const timeout=setTimeout(()=>app.exit(2),120000)
server.listen(0,'127.0.0.1',async()=>{
 try{
  const port=server.address().port;process.env.NOVATERM_LLM_PROVIDER='compatible';process.env.NOVATERM_LLM_BASE_URL=`http://127.0.0.1:${port}/v1`;process.env.NOVATERM_LLM_MODEL='ui-only';process.env.NOVATERM_LLM_API_KEY=''
  require(path.join(root,'main.js'))
  ipcMain.removeHandler('startup-update-notice');ipcMain.handle('startup-update-notice',()=>{notices++;return {version:'2.0.7',highlights:['放大文字并优化布局','<img src=x onerror=alert(1)>']}})
  ipcMain.removeHandler('ignore-update-notice');ipcMain.handle('ignore-update-notice',(_e,v)=>ignored.push(v))
  ipcMain.removeHandler('check-updates');ipcMain.handle('check-updates',()=>{updateChecks++;return {currentVersion:'2.0.6',newVersion:'2.0.7',phase:'available',canDownload:true,message:'发现新版本',notes:'测试说明'}})
  await app.whenReady()
  const desktop=new BrowserWindow({show:false,width:1600,height:998,frame:false,webPreferences:{preload:path.join(root,'preload.js'),offscreen:true,contextIsolation:true,nodeIntegration:false}})
  let frame
  desktop.webContents.on('paint',(_event,_dirty,image)=>{frame=image})
  await desktop.loadFile(path.join(root,'renderer/index.html'))
  for(const win of BrowserWindow.getAllWindows())if(win!==desktop)win.destroy()
  for(let i=0;i<240;i++){if(!desktop.webContents.isLoading()&&await desktop.webContents.executeJavaScript('typeof initialized!=="undefined"&&initialized'))break;await wait(100)}
  const run=code=>desktop.webContents.executeJavaScript(code),snap=async(name)=>{desktop.webContents.invalidate();await wait(350);const target=path.join(qaDir,`${name}.png`);assert(frame,'offscreen frame missing');fs.writeFileSync(target,frame.toPNG());result.screenshots.push(target)}
  const layout=()=>run(`(()=>{const main=document.querySelector('body>main'),aside=document.querySelector('.task-options'),r=$('runBtn').getBoundingClientRect(),top=document.querySelector('.topbar').getBoundingClientRect();return {width:innerWidth,height:innerHeight,mainScroll:main.scrollHeight-main.clientHeight,asideScroll:aside.scrollHeight-aside.clientHeight,run:{top:r.top,bottom:r.bottom},horizontal:document.documentElement.scrollWidth-innerWidth,topbar:top.height}})()`)
  await run("Object.defineProperty(document,'hidden',{get:()=>false});document.hasFocus=()=>true;$('modelModal').hidden=false")
  await wait(2300);assert.equal(await run("$('updateNoticeDialog').open"),false)
  await run("$('modelModal').hidden=true");await wait(200)
  assert.equal(await run("$('updateNoticeDialog').open"),true)
  assert.equal(await run("!!$('updateNoticeHighlights').querySelector('img')"),false)
  await snap('update-notice-206');await run("$('ignoreUpdateVersion').checked=true;$('laterUpdateNotice').click()");await wait(150)
  assert.deepEqual(ignored,['2.0.7']);assert.equal(notices,1);assert.equal(await run("$('updateNoticeDialog').open"),false);result.checks.push('daily notice deferred behind modal; plain text; version opt-out')
  await run("state.files=[];state.references=[];setMode('translate')")
  for(const [w,h] of [[1600,998],[1440,900],[1298,698],[1024,700],[972,698]]){
   desktop.setMinimumSize(600,500);desktop.setContentSize(w,h);await wait(230)
   await run("state.files=[];renderFiles();$('referencesPanel').open=false")
   const empty=await layout();result.checks.push({empty});assert.equal(empty.horizontal,0,JSON.stringify(empty));assert(empty.mainScroll<3,JSON.stringify(empty))
   await run("state.files=Array.from({length:12},(_,i)=>'C:/qa/多文件布局测试文档'+(i+1)+'.pptx');state.references=['C:/qa/参考材料.docx'];renderFiles();$('referencesPanel').open=true")
   await wait(100);const loaded=await layout();result.checks.push({loaded});assert.equal(loaded.horizontal,0,JSON.stringify(loaded));assert(loaded.mainScroll<3,JSON.stringify(loaded));assert(loaded.run.bottom<=loaded.height,JSON.stringify(loaded));assert(loaded.asideScroll<3,JSON.stringify(loaded))
   const before=await run("$('runBtn').getBoundingClientRect().top")
   await run("$('translationHelpButton').focus();$('translationHelpButton').click()");await wait(100)
   assert.equal(await run("$('translationHelp').open"),true);assert.equal(await run("$('runBtn').getBoundingClientRect().top"),before)
   const help=await run("(()=>{const r=$('translationHelp').getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,display:getComputedStyle($('translationHelp')).display,hit:document.elementFromPoint(r.left+50,r.top+50)?.outerHTML.slice(0,200)}})()");result.checks.push({help});assert(help.bottom-help.top>100&&help.bottom-help.top<600&&help.top>=0&&help.bottom<=h,JSON.stringify(help))
   if(w===1298)await snap('help-206')
   desktop.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});desktop.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});await wait(100)
   assert.equal(await run("$('translationHelp').open"),false);assert.equal(await run("document.activeElement.id"),'translationHelpButton')
   await snap('home-206-'+w)
  }
  desktop.setContentSize(1024,700);await run("$('openModel').click()");await wait(300)
  const model=await run("(()=>{const e=document.querySelector('.model-editor'),r=$('modelUse').getBoundingClientRect();return {scroll:e.scrollHeight-e.clientHeight,footer:r.bottom,height:innerHeight}})()")
  result.checks.push({model});assert(model.footer<=model.height,JSON.stringify(model));assert(model.scroll<3,JSON.stringify(model))
  await snap('models-compact-206');await run("$('modelClose').click()");await wait(150)
  desktop.setContentSize(1440,900)
  await run("$('openLexicon').click()");await wait(500);await snap('glossary-206');await run("$('closeLexicon').click()");await wait(150)
  await run("$('translationHelpButton').click();state.files=['C:/qa/sample.pdf'];renderFiles()");await wait(150);assert.equal(await run("$('translationHelp').open"),false)
  const resumeOptions={kind:'check',paths:['C:/qa/unfinished.docx'],references:[],pairs:{},workers:3,use_llm:false,combined_output:'final',translation_mode:'faithful'}
  let resumedRequest
  ipcMain.removeHandler('api');ipcMain.handle('api',(_event,{method,path:apiPath,body})=>{
   if(apiPath.startsWith('/api/history?'))return {records:[{id:'resume-fixture',kind:'check',status:'interrupted',started_at:new Date().toISOString(),paths:resumeOptions.paths,outputs:[],errors:[],counts:{},resume_options:resumeOptions}],total:1,page:0,page_size:30}
   if(apiPath==='/api/history/resume-fixture/resume')return resumeOptions
   if(apiPath==='/api/jobs'&&method==='POST'){resumedRequest=body;return {id:'restored-fixture',kind:'check',status:'complete',result:{report_id:'restored-fixture',files:[],findings:[],stats:{model_status:'not_requested',segments:1},errors:[]}}}
   return {}
  })
  await run("$('openHistory').click()");await wait(180)
  assert.equal(await run("[...$('historyRows').querySelectorAll('button')].some(b=>b.textContent==='继续未完成任务')"),true)
  await snap('history-resume-207')
  await run("[...$('historyRows').querySelectorAll('button')].find(b=>b.textContent==='继续未完成任务').click()");await wait(200)
  assert.deepEqual(resumedRequest,resumeOptions);assert.equal(await run("$('historyModal').hidden"),true);assert.equal(await run('state.job.id'),'restored-fixture')
  await run("state.report=null;state.job={id:'resume-fixture',status:'failed'};showTaskFailure(new Error('模型连接中断'))")
  assert.equal(await run("$('failureResume').hidden"),false);await snap('failure-resume-207')
  await run("state.job={id:'resume-fixture',status:'running'};showTaskFailure(new Error('连接暂时中断'))")
  assert.equal(await run("$('failureResume').hidden"),true)
  result.checks.push('history resumes exact saved options; failure action visible; running task cannot duplicate')
  sharedJobs=[{id:'shared-resume-fixture',kind:'translate',status:'interrupted',message:'任务已中断',downloads:[],can_resume:true,percent:50}]
  const shared=new BrowserWindow({show:false,width:900,height:850,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});await shared.loadURL(`http://127.0.0.1:${port}/`)
  const sr=code=>shared.webContents.executeJavaScript(code)
  await wait(200);assert.equal(await sr("[...$('jobs').querySelectorAll('button')].some(b=>b.textContent==='继续未完成任务')"),true)
  await sr("[...$('jobs').querySelectorAll('button')].find(b=>b.textContent==='继续未完成任务').click()");await wait(200)
  assert.equal(sharedResumes,1);assert.equal(await sr('selected'),'shared-restored-fixture')
  result.checks.push('shared resume button submits owned task and displays resumed progress')
  await sr("(()=>{const d=new DataTransfer();d.items.add(new File([''],'demo.pptx'));$('files').files=d.files;$('files').dispatchEvent(new Event('change'));$('translationHelpButton').click()})()")
  for(const w of [900,480]){shared.setContentSize(w,850);await wait(100);const rect=await sr("(()=>{const r=$('translationHelp').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth}})()");assert(rect.left>=0&&rect.right<=rect.width&&rect.bottom<=850,JSON.stringify(rect))}
  result.checks.push('floating help geometry; Escape focus; source file changes close modal; shared 480/900px')
  result.passed=true
 }catch(error){result.error=error.stack}
 finally{fs.writeFileSync(path.join(qaDir,'readable-206-result.json'),JSON.stringify(result,null,2));clearTimeout(timeout);server.closeAllConnections();server.close();app.emit('will-quit');app.exit(result.passed?0:1)}
})
