// Run with Node; the worker uses a hidden offscreen Electron window and isolated data.
const runtime=require('electron')
if(typeof runtime==='string') {
 const path=require('node:path'),fs=require('node:fs'),{spawnSync}=require('node:child_process')
 const file=path.resolve(__dirname,'../dist/qa/readability/readable-result.json')
 fs.rmSync(file,{force:true})
 const task=spawnSync(runtime,[__filename],{cwd:path.resolve(__dirname,'..'),windowsHide:true,timeout:150000,encoding:'utf8'})
 if(task.error)console.error(task.error.message)
 if(fs.existsSync(file)){const value=JSON.parse(fs.readFileSync(file));console.log(value.passed?'Desktop readability and dialog checks passed':value.error||'UI checks did not finish')}
 else if(task.status!==0)console.error('Hidden UI worker did not produce results. '+(task.stderr||'').slice(-1800))
 process.exit(task.status??1)
}
const {app,BrowserWindow,ipcMain}=require('electron'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict')
const root=path.resolve(__dirname,'..'),qaDir=path.join(root,'dist','qa','readability'),wait=ms=>new Promise(r=>setTimeout(r,ms)),result={passed:false,checks:[],screenshots:[],companyDocumentsSent:false}
fs.mkdirSync(qaDir,{recursive:true})
app.setPath('userData',path.join(qaDir,'readable-ui-profile'));BrowserWindow.prototype.show=function(){}
app.getVersion=()=>JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version
app.commandLine.appendSwitch('disable-renderer-backgrounding')
app.on('browser-window-created',(_event,win)=>win.webContents.setBackgroundThrottling(false))
let notices=0,ignored=[],updateChecks=0
let sharedJobs=[],sharedResumes=0
const previewRequests=[]
const sharedComparisonOpens=[]
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost').pathname
 res.setHeader('Content-Type',url.endsWith('.css')?'text/css':url.endsWith('.js')?'text/javascript':url.endsWith('.png')?'image/png':'text/html')
 if(url==='/v1/models')return res.end(JSON.stringify({data:[{id:'ui-only'}]}))
 if(url==='/shared/session'){res.setHeader('Set-Cookie','preview-test=owned; HttpOnly; SameSite=Strict; Path=/');return res.end(JSON.stringify({csrf:'ui-only'}))}
 if(url.startsWith('/preview-fixture/preview/')){
  const page=Number(new URL(req.url,'http://localhost').searchParams.get('page')||1),owned=String(req.headers.cookie||'').includes('preview-test=owned')
  previewRequests.push({page,side:url.split('/').at(-1),owned})
  const script=fs.readFileSync(path.join(root,'backend/document_preview.py'),'utf8').match(/FRAME_SCRIPT=r'''([\s\S]*?)'''/)[1]
  return res.end(`<html><head><style>.slide{width:900px;height:500px;background:white}.slide-container{width:900px;height:500px}</style></head><body data-star-page="${page}" data-star-total="3"><div class="slide-container"><div class="slide">${owned?'Page '+page:'Ownership cookie missing'}</div></div><script>${script}</script></body></html>`)
 }
 if(url==='/shared/jobs')return res.end(JSON.stringify({jobs:sharedJobs}))
 if(/^\/shared\/jobs\/shared-comparison\/comparison\/\d+$/.test(url)){
  sharedComparisonOpens.push(url);return res.end(JSON.stringify({source_name:'source.pptx',output_name:sharedJobs[0].result.outputs[Number(url.split('/').at(-1))].path,rows:[]}))
 }
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
  const display=require('electron').screen.getPrimaryDisplay(),{defaultWindowSize,referenceZoom}=require('../lib/window-size'),size=defaultWindowSize(display.workArea,display.scaleFactor),zoom=referenceZoom(display.scaleFactor,display.workArea)
  result.displays=require('electron').screen.getAllDisplays().map(({workArea,scaleFactor})=>({workArea,scaleFactor}))
  const desktop=new BrowserWindow({show:false,...size,frame:false,webPreferences:{zoomFactor:zoom,preload:path.join(root,'preload.js'),offscreen:true,contextIsolation:true,nodeIntegration:false}})
  const setViewport=(w,h)=>desktop.setContentSize(Math.round(w*zoom),Math.round(h*zoom))
  let frame
  desktop.webContents.on('paint',(_event,_dirty,image)=>{frame=image})
  await desktop.loadFile(path.join(root,'renderer/index.html'))
  for(const win of BrowserWindow.getAllWindows())if(win!==desktop)win.destroy()
  for(let i=0;i<240;i++){if(!desktop.webContents.isLoading()&&await desktop.webContents.executeJavaScript('typeof initialized!=="undefined"&&initialized'))break;await wait(100)}
  const run=code=>desktop.webContents.executeJavaScript(code),snap=async(name)=>{desktop.webContents.invalidate();await wait(350);const target=path.join(qaDir,`${name}.png`);assert(frame,'offscreen frame missing');fs.writeFileSync(target,frame.toPNG());result.screenshots.push(target)}
  const layout=()=>run(`(()=>{const main=document.querySelector('body>main'),aside=document.querySelector('.task-options'),r=$('runBtn').getBoundingClientRect(),top=document.querySelector('.topbar').getBoundingClientRect(),list=$('filelist'),row=list.querySelector('li');return {width:innerWidth,height:innerHeight,mainScroll:main.scrollHeight-main.clientHeight,asideScroll:aside.scrollHeight-aside.clientHeight,run:{top:r.top,bottom:r.bottom},horizontal:document.documentElement.scrollWidth-innerWidth,topbar:top.height,topbarScroll:document.querySelector('.topbar').scrollWidth-innerWidth,bodyFont:parseFloat(getComputedStyle(document.body).fontSize),buttonFont:parseFloat(getComputedStyle($('runBtn')).fontSize),fileRows:row?list.clientHeight/row.getBoundingClientRect().height:0}})()`)
  await run("Object.defineProperty(document,'hidden',{get:()=>false});document.hasFocus=()=>true;$('modelModal').hidden=false")
  await wait(2300);assert.equal(await run("$('updateNoticeDialog').open"),false)
  await run("$('modelModal').hidden=true");await wait(200)
  assert.equal(await run("$('updateNoticeDialog').open"),true)
  assert.equal(await run("!!$('updateNoticeHighlights').querySelector('img')"),false)
  await snap('update-notice');await run("$('ignoreUpdateVersion').checked=true;$('laterUpdateNotice').click()");await wait(150)
  assert.deepEqual(ignored,['2.0.7']);assert.equal(notices,1);assert.equal(await run("$('updateNoticeDialog').open"),false);result.checks.push('daily notice deferred behind modal; plain text; version opt-out')
  await run("state.files=[];state.references=[];setMode('translate')")
  assert.equal(desktop.webContents.getZoomFactor(),zoom)
  for(const [w,h] of [[1280,820],[Math.round(size.width/zoom),Math.round(size.height/zoom)],[1600,998],[1175,626],[1101,585],[1024,700],[942,655],[972,560]]){
   desktop.setMinimumSize(Math.floor(600*zoom),Math.floor(500*zoom));setViewport(w,h);await wait(230)
   await run("state.files=[];renderFiles();$('referencesPanel').open=false")
   const empty=await layout();result.checks.push({empty});assert.equal(empty.horizontal,0,JSON.stringify(empty));assert(empty.mainScroll<3,JSON.stringify(empty));assert(empty.topbarScroll<3,JSON.stringify(empty));assert(empty.bodyFont>=16&&empty.bodyFont<=16.5&&empty.buttonFont<=16.5,JSON.stringify(empty));assert(empty.run.bottom<=h,JSON.stringify(empty))
   if(w===1280){
    const flow=await run("(()=>{const reduced=matchMedia('(prefers-reduced-motion:reduce)').matches,a=document.getAnimations().find(a=>a.animationName==='sheen');return {reduced,name:getComputedStyle($('dropzone'),'::before').animationName,state:a?.playState,duration:a?.effect.getTiming().duration}})()")
    // Headless Windows runners may request reduced motion or pause rendering.
    if(flow.reduced)assert.equal(flow.name,'none')
    else assert(flow.name==='sheen'&&flow.state==='running'&&flow.duration===6000,JSON.stringify(flow))
    assert.equal(await run("$('dropzone').querySelector('img').naturalWidth>0"),true)
    assert.equal(await run("getComputedStyle($('dropzone').querySelector('img')).width"),'144px')
    await run("$('dropzone').dispatchEvent(new Event('dragover',{cancelable:true}))")
    assert.equal(await run("$('dropzone').classList.contains('over')"),true)
    await run("$('dropzone').dispatchEvent(new Event('dragleave'))")
    assert.equal(await run("$('dropzone').classList.contains('over')"),false)
    result.checks.push('original 144px portrait, moving six-second sheen and drag highlight preserved')
    await snap('home-empty-208')
   }
   await run("state.files=Array.from({length:12},(_,i)=>'C:/qa/多文件布局测试文档'+(i+1)+'.pptx');state.references=['C:/qa/参考材料.docx'];renderFiles();$('referencesPanel').open=true")
   await wait(100);const loaded=await layout();result.checks.push({loaded});assert.equal(loaded.horizontal,0,JSON.stringify(loaded));assert(loaded.mainScroll<3,JSON.stringify(loaded));assert(loaded.run.bottom<=loaded.height,JSON.stringify(loaded));assert(loaded.asideScroll<3,JSON.stringify(loaded))
   const before=await run("$('runBtn').getBoundingClientRect().top")
   await run("$('translationHelpButton').focus();$('translationHelpButton').click()");await wait(100)
   assert.equal(await run("$('translationHelp').open"),true);assert.equal(await run("$('runBtn').getBoundingClientRect().top"),before)
   const help=await run("(()=>{const r=$('translationHelp').getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,display:getComputedStyle($('translationHelp')).display,hit:document.elementFromPoint(r.left+50,r.top+50)?.outerHTML.slice(0,200)}})()");result.checks.push({help});assert(help.bottom-help.top>100&&help.bottom-help.top<600&&help.top>=0&&help.bottom<=h,JSON.stringify(help))
   if(w===1280)await snap('help-208')
   desktop.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});desktop.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});await wait(100)
   assert.equal(await run("$('translationHelp').open"),false);assert.equal(await run("document.activeElement.id"),'translationHelpButton')
   await snap('home-208-'+w)
  }
  setViewport(1024,700);await run("$('openModel').click()");await wait(300)
  const model=await run("(()=>{const e=document.querySelector('.model-editor'),r=$('modelUse').getBoundingClientRect();return {scroll:e.scrollHeight-e.clientHeight,footer:r.bottom,height:innerHeight}})()")
  result.checks.push({model});assert(model.footer<=model.height,JSON.stringify(model));assert(model.scroll<3,JSON.stringify(model))
  await snap('models-compact-208');await run("$('modelClose').click()");await wait(150)
  setViewport(1280,820)
  await run("$('openLexicon').click()");await wait(500)
  const lexicon=await run("(()=>{const list=$('termRows'),row=list.querySelector('.term-card'),close=$('closeLexicon').getBoundingClientRect();return {visibleRows:list.clientHeight/row.getBoundingClientRect().height,font:parseFloat(getComputedStyle(row).fontSize),right:close.right,bottom:close.bottom}})()")
  result.checks.push({lexicon});assert(lexicon.visibleRows>=10,JSON.stringify(lexicon));assert(lexicon.right<=1280&&lexicon.bottom<=820,JSON.stringify(lexicon))
  await snap('glossary-208')
  await run("window._personCategoryFixture='示例姓名'+Date.now();$('addTerm').click();$('termZh').value=window._personCategoryFixture;$('termZh').dispatchEvent(new Event('input'));$('termEn').value='Example Name';$('termEn').dispatchEvent(new Event('input'));$('termCategory').value='person';$('termCategory').dispatchEvent(new Event('input'));$('termSearch').value=window._personCategoryFixture;$('termCategoryFilter').value='person';$('termCategoryFilter').dispatchEvent(new Event('change'))")
  assert.equal(await run("$('termRows').querySelectorAll('.term-card').length"),1)
  assert.equal(await run("$('termRows').textContent.includes('人名')"),true)
  await run("$('saveLexicon').click()")
  for(let i=0;i<60&&!await run("$('lexiconStatus').textContent.startsWith('已保存 ')");i++)await wait(100)
  assert.equal(await run("$('lexiconStatus').textContent.startsWith('已保存 ')"),true)
  await run("$('closeLexicon').click()");await wait(100)
  await run("$('openLexicon').click()");await wait(500)
  assert.equal(await run("$('lexiconModal').hidden"),false)
  await run("$('termSearch').value=window._personCategoryFixture;$('termCategoryFilter').value='person';$('termCategoryFilter').dispatchEvent(new Event('change'))")
  assert.equal(await run("$('termCategory').value"),'person')
  await run("$('lexiconGridView').click()")
  assert.equal(await run("$('tableBody').querySelector('select[aria-label=分类]').value"),'person')
  const categories=await run("(()=>{const t=$('termCategoryFilter').getBoundingClientRect(),v=$('lexiconListView').getBoundingClientRect();return {right:t.right,next:v.left,toolbar:document.querySelector('.lexicon-toolbar').scrollWidth-document.querySelector('.lexicon-toolbar').clientWidth}})()")
  assert(categories.right>0&&categories.right<=categories.next&&categories.toolbar<3,JSON.stringify(categories))
  result.checks.push({personCategory:true,categories});await snap('glossary-person-category')
  await run("$('lexiconListView').click()");setViewport(1024,700);await wait(150)
  const categoryDetail=await run("(()=>{const a=$('termCategory').getBoundingClientRect(),d=$('deleteTerm').getBoundingClientRect(),p=document.querySelector('.term-detail').getBoundingClientRect();return {left:a.left,right:d.right,panelLeft:p.left,panelRight:p.right,bottom:d.bottom,height:innerHeight}})()")
  assert(categoryDetail.panelRight>0&&categoryDetail.left>=categoryDetail.panelLeft&&categoryDetail.right<=categoryDetail.panelRight&&categoryDetail.bottom<=categoryDetail.height,JSON.stringify(categoryDetail))
  await snap('glossary-person-detail-compact');await run("$('closeLexicon').click()");await wait(150)
  await run(`loadReport({report_id:'layout-fixture',kind:'check',files:[{path:'C:/qa/sample.pptx',name:'sample.pptx'}],stats:{model_status:'complete',segments:10,judged:10,rule_hits:0,llm_hits:10},findings:Array.from({length:10},(_,i)=>({file:'sample.pptx',file_path:'C:/qa/sample.pptx',slide:i+1,method:'llm',editable:true,found_text:'Second half strategy',suggested:'H2 strategy',reason:'统一全文用语',context:'Example context'}))});openReport()`)
  for(const [w,h] of [[1280,820],[942,655]]){
   setViewport(w,h);await wait(100)
   const report=await run("(()=>{const card=$('reportPanel').getBoundingClientRect(),button=$('applyBtn').getBoundingClientRect(),toolbar=document.querySelector('.result-toolbar');return {width:innerWidth,height:innerHeight,right:card.right,bottom:card.bottom,applyBottom:button.bottom,toolbarOverflow:toolbar.scrollWidth-toolbar.clientWidth}})()")
   result.checks.push({report});assert(report.right<=report.width&&report.bottom<=report.height&&report.applyBottom<=report.height&&report.toolbarOverflow<3,JSON.stringify(report))
   if(w===1280)await snap('report-208')
  }
  await run(`state.report.findings=Array.from({length:364},(_,i)=>({file:'sample.pptx',file_path:'C:/qa/sample.pptx',segment_id:'segment'+i,slide:1,method:'llm',editable:i<340,applied:i>=330&&i<340,found_text:'Old '+i,suggested:i<320?'New '+i:'',reason:'Fixture'}));state.selected.clear();renderReport();$('selectAll').click()`)
  assert.equal(await run('state.selected.size'),320)
  assert.equal(await run("$('selectAll').checked"),true)
  await run("$('reportBody').querySelector('[data-index]').click()")
  assert.equal(await run("$('selectAll').indeterminate"),true)
  await run("state.edits[320]='Manual replacement';renderReport();$('selectAll').click()")
  assert.equal(await run('state.selected.size'),321)
  assert.equal(await run("$('reportBody').querySelector('[data-edit=\"320\"]').readOnly"),false)
  result.checks.push('select all handles 364 suggestions, blank edits, applied states and mixed selection')
  await run("$('exportProgressBox').hidden=false;$('exportProgressText').textContent='sample.pptx · 正在逐页检查版式（3/8）';$('exportProgress').value=37.5")
  const saving=await run("(()=>{const a=$('applyBtn').getBoundingClientRect(),p=$('exportProgressBox').getBoundingClientRect();return {progressTop:p.top,progressBottom:p.bottom,buttonBottom:a.bottom,height:innerHeight}})()")
  assert(saving.progressTop>=0&&saving.progressBottom<=saving.height&&saving.buttonBottom<=saving.height,JSON.stringify(saving));await snap('report-save-progress')
  await run("$('exportProgressBox').hidden=true")
  await run("$('reportModal').hidden=true;state.report=null;state.selected.clear()")
  for(const name of ['picker-options','picker-list','picker-mkdir','picker-confirm','picker-cancel'])ipcMain.removeHandler(name)
  const fixture=path.join(qaDir,'picker-fixture');fs.mkdirSync(fixture,{recursive:true})
  for(let i=1;i<=40;i++)fs.writeFileSync(path.join(fixture,`示例文档${i}.pptx`),'')
  const choose=require('../lib/file-picker').installFilePicker(()=>desktop,()=>path.join(root,'build/icon.png'))
  const chosen=choose({mode:'open',directory:fixture,extensions:['pptx'],multiple:true,title:'选择文档'})
  const picker=BrowserWindow.getAllWindows().find(win=>win!==desktop)
  for(let i=0;i<50;i++){if(await picker.webContents.executeJavaScript("!!document.querySelector('.picker-entry')").catch(()=>false))break;await wait(100)}
  for(const [w,h] of [[1120,760],[942,655]]){
   picker.setContentSize(Math.round(w*zoom),Math.round(h*zoom));await wait(100)
   const filePicker=await picker.webContents.executeJavaScript("(()=>{const list=document.getElementById('pickerList'),row=list.querySelector('.picker-entry'),button=document.getElementById('pickerAccept').getBoundingClientRect();return {width:innerWidth,height:innerHeight,rows:list.clientHeight/row.getBoundingClientRect().height,rowFont:parseFloat(getComputedStyle(row).fontSize),buttonBottom:button.bottom,horizontal:document.documentElement.scrollWidth-innerWidth}})()")
   result.checks.push({filePicker});assert(filePicker.rows>=8&&filePicker.rowFont===16&&filePicker.buttonBottom<=filePicker.height&&filePicker.horizontal===0,JSON.stringify(filePicker))
  }
  await picker.webContents.executeJavaScript("document.getElementById('pickerCancel').click()");await chosen
  result.checks.push('report controls fit compact windows; file picker keeps at least eight visible rows')
  setViewport(1280,820)
  await run("$('translationHelpButton').click();state.files=['C:/qa/sample.pdf'];renderFiles()");await wait(150);assert.equal(await run("$('translationHelp').open"),false)
  const progressCases=[
   {done:61,total:173,detail:'等待模型响应 3 处'},
   {done:2,total:173,detail:'等待模型响应 1 处'},
   {done:80,total:173,detail:'核对可用断点 1 处'},
   {done:81,total:173,detail:'保留成果，准备重试 1 处'},
   {done:82,total:173,detail:'校验模型返回内容 2 处'},
   {done:173,total:173,detail:'正在整理已验证译文与样式'}
  ]
  await run("busy(true);$('workspace').hidden=true;$('jobStages').hidden=false;$('jobMessage').textContent='处理 1/1：progress-fixture.docx'")
  for(const value of progressCases){
   await run(`renderJobPhase(${JSON.stringify({...value,phase:'translate',status:'running'})})`)
   const text=await run("$('jobDetail').textContent")
   assert.equal(text,`翻译：${value.done} / ${value.total} 段 · ${value.detail}`)
   assert.equal((text.match(/\d+ \/ \d+/g)||[]).length,1)
  }
  await run(`renderJobPhase(${JSON.stringify({...progressCases[0],phase:'translate',status:'running'})})`)
  await snap('progress-count-once');await run("busy(false);$('workspace').hidden=false")
  result.checks.push('desktop progress shows one completed count and retains sequential/concurrent/resume/retry/validation activity')
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
  await run(`state.job={id:'resume-fixture',status:'partial',can_resume:true};state.outputs=[{path:'C:/qa/draft.pptx',staged:true,target_dir:'C:/qa',translated:222,review_items:[{reason:'剩余翻译尚未完成'}]}];loadReport({report_id:'resume-fixture',kind:'translate_review',output_mode:'final',files:[{path:'C:/qa/draft.pptx',name:'draft.pptx',review_available:false}],stats:{model_status:'not_started',segments:0,judged:0},errors:[{error:'翻译尚未完成，已保存可恢复的进度；未将未译中文交给校对。恢复任务后会继续翻译。'}],findings:[]},state.outputs);showCheckCompletion()`)
  assert.equal(await run("$('completionResume').hidden"),false)
  assert((await run("$('reviewCompleteTitle').textContent")).includes('校对尚未开始'))
  assert.equal(await run("$('completionIssue').hidden"),false)
  await snap('incomplete-translation-resume')
  result.checks.push('incomplete translation explains why proofreading has not started and offers direct resume')
  await run(`state.job={id:'complete-fixture',status:'complete',can_resume:true};state.outputs=[];loadReport({report_id:'complete-fixture',kind:'translate_review',files:[{path:'C:/qa/final.pptx',name:'final.pptx'}],stats:{model_status:'complete',segments:278,judged:278},errors:[],findings:[{found_text:'typo',suggested:'type',method:'llm',editable:true}]},[]);showCheckCompletion()`)
  assert.equal(await run("$('reviewCompleteTitle').textContent"),'翻译并校对完成')
  assert.equal(await run("$('completionResume').hidden&&$('completionExportLog').hidden&&$('completionIssue').hidden"),true)
  await snap('completion-success')
  await run(`state.job={id:'manual-fixture',status:'partial',can_resume:true};loadReport({report_id:'manual-fixture',kind:'translate_review',files:[{path:'C:/qa/final.pptx',name:'final.pptx'}],stats:{model_status:'partial',segments:278,judged:274,unreviewed:4,errors:0},errors:[],findings:Array.from({length:4},(_,i)=>({found_text:'English '+i,suggested:'',reason:'翻译待核对：请确认日期。',method:'rule',editable:true,applied:false}))},[]);showCheckCompletion()`)
  assert((await run("$('reviewCompleteTitle').textContent")).includes('4 处待人工核对'))
  assert.equal(await run("$('completionResume').hidden&&$('completionExportLog').hidden&&$('completionIssue').hidden"),true)
  await snap('completion-manual-review')
  await run("state.report.findings.forEach(f=>f.applied=true);renderCheckCompletion()")
  assert.equal(await run("$('reviewCompleteTitle').textContent"),'翻译并校对完成')
  assert(!(await run("$('completionDetails').textContent")).includes('待人工核对'))
  await run("state.report.stats={model_status:'partial',review_processing_status:'partial',segments:278,judged:277,unreviewed:1,errors:1};state.report.findings=[];renderCheckCompletion()")
  assert.equal(await run("$('completionResume').hidden||$('completionExportLog').hidden||$('completionIssue').hidden"),false)
  assert((await run("$('completionIssue').textContent")).includes('1 段'))
  await snap('completion-model-interruption')
  await run("state.report.stats={model_status:'complete',segments:278,judged:278};state.outputs=[{path:'C:/qa/final.pptx',needs_review:100,layout_warnings:[{reason:'请核对版式'}]}];renderCheckCompletion()")
  assert.equal(await run("$('reviewCompleteTitle').textContent"),'翻译并校对完成')
  assert.equal(await run("$('completionResume').hidden&&$('completionExportLog').hidden"),true)
  await run("state.report.stats={model_status:'partial',review_processing_status:'complete',manual_review:1,segments:1,judged:0,unreviewed:1};state.report.findings=[{found_text:'显示屏',reason:'翻译待核对：补译未完成。',applied:false}];renderCheckCompletion()")
  assert.equal(await run("$('completionResume').hidden"),false)
  assert.equal(await run("$('completionResume').textContent"),'继续未完成翻译')
  assert((await run("$('reviewCompleteNotice').textContent")).includes('1 处未译中文'))
  result.checks.push('completion separates successful review, manual decisions, layout advice and genuine model interruptions; resolved manual items refresh immediately')
  const comparisonOpens=[]
  ipcMain.removeHandler('api');ipcMain.handle('api',(_event,{method,path:apiPath,body})=>{
   if(apiPath==='/api/reports/exports')return {id:'save-'+body.path,status:'complete',result:{output:body.path.replace('draft','checked'),comparison_id:body.path.includes('first')?'first-id':'second-id',applied_count:0,failed:[],finding_updates:[]}}
   if(apiPath.startsWith('/api/comparisons/')){comparisonOpens.push(apiPath);return {source_name:'source.pptx',output_name:'latest-checked.pptx',rows:[]}}
   return {}
  })
  await run(`state.outputs=[{path:'C:/qa/first-draft.pptx',comparison_id:'first-id',staged:true,target_dir:'C:/qa'},{path:'C:/qa/second-draft.pptx',comparison_id:'second-id',staged:true,target_dir:'C:/qa'}];loadReport({report_id:'comparison-save',kind:'translate_review',output_mode:'final',files:state.outputs.map(o=>({path:o.path,name:basename(o.path)})),stats:{model_status:'complete',segments:2,judged:2,rule_hits:0,llm_hits:0},errors:[],findings:[]},state.outputs);renderReport();$('reportModal').hidden=false`)
  assert.equal(await run("$('reportCompare').hidden"),false)
  await run('renderCheckCompletion()')
  assert((await run("$('completionCompare').textContent")).includes('初稿'))
  await run('exportReport(false,true)')
  assert.equal(await run("$('reportCompare').hidden||$('reportCompare').disabled"),false)
  assert.equal(await run("$('reportCompare').dataset.comparison"),'second-id')
  assert((await run("$('reportOutputPath').textContent")).endsWith('second-checked.pptx'))
  await run("$('reportOutput').value='0';$('reportOutput').dispatchEvent(new Event('change'));$('reportCompare').click()")
  await wait(200);assert.equal(comparisonOpens.at(-1),'/api/comparisons/first-id')
  assert.equal(await run("$('comparisonDialog').open"),true)
  await run("$('closeComparison').click()");await wait(50);await snap('report-saved-comparison')
  await run('showCheckCompletion()')
  assert((await run("$('completionPath').textContent")).endsWith('second-checked.pptx'))
  assert.equal(await run("$('completionCompare').dataset.comparison"),'second-id')
  assert((await run("$('completionCompare').textContent")).includes('已保存稿'))
  assert.equal(await run("$('completionFiles').querySelectorAll('[data-comparison]').length"),0)
  await run("$('completionCompare').click()");await wait(100)
  assert.equal(comparisonOpens.at(-1),'/api/comparisons/second-id')
  await run("$('closeComparison').click();$('completionOutput').value='0';$('completionOutput').dispatchEvent(new Event('change'));$('completionCompare').click()")
  await wait(100);assert.equal(comparisonOpens.at(-1),'/api/comparisons/first-id')
  await run("$('closeComparison').click();openReport();exportReport(false,true)");await wait(100)
  assert.equal(await run('state.exportRecords.length'),2)
  assert.equal(await run("state.outputs.every(o=>o.path.endsWith('-checked.pptx')&&o.review_exported)"),true)
  await run('showCheckCompletion()');await snap('completion-saved-comparison')
  await run("loadReport({report_id:'standalone',kind:'check',files:[],stats:{},findings:[]});renderReport()")
  assert.equal(await run("$('reportCompare').hidden"),true)
  result.checks.push('Report comparison remains enabled after final-only save, switches with selected document, opens latest comparison and clears between tasks')
  result.checks.push('Completion comparison follows selected saved output, distinguishes drafts, refreshes after repeated saves and removes stale draft buttons')
  sharedJobs=[{id:'shared-resume-fixture',kind:'translate',status:'interrupted',message:'任务已中断',downloads:[],can_resume:true,percent:50}]
  const shared=new BrowserWindow({show:false,width:900,height:850,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});await shared.loadURL(`http://127.0.0.1:${port}/`)
  const sr=code=>shared.webContents.executeJavaScript(code)
  await wait(200);assert.equal(await sr("[...$('jobs').querySelectorAll('button')].some(b=>b.textContent==='继续未完成任务')"),true)
  await sr("[...$('jobs').querySelectorAll('button')].find(b=>b.textContent==='继续未完成任务').click()");await wait(200)
  assert.equal(sharedResumes,1);assert.equal(await sr('selected'),'shared-restored-fixture')
  result.checks.push('shared resume button submits owned task and displays resumed progress')
  sharedJobs=[{id:'shared-resume-fixture',kind:'translate_review',status:'complete',message:'已完成，报告可恢复',downloads:[],can_resume:false,can_restore_report:true,percent:100}]
  await sr('refresh()');await wait(100)
  assert((await sr("$('jobs').textContent")).includes('恢复校对报告'))
  assert(!(await sr("$('jobs').textContent")).includes('继续未完成任务'))
  await sr("[...$('jobs').querySelectorAll('button')].find(b=>b.textContent==='恢复校对报告').click()");await wait(200)
  assert.equal(sharedResumes,2)
  result.checks.push('shared report restoration remains available after restart without presenting completed work as interrupted')
  for(const value of progressCases){
   sharedJobs=[{...value,id:'progress-fixture',kind:'translate',phase:'translate',status:'running',message:'处理 1/1：progress-fixture.docx',percent:30,downloads:[]}]
   await sr('refresh()')
   const text=await sr("$('jobs').querySelector('.hint').textContent")
   assert.equal(text,`${value.detail} · ${value.done} / ${value.total} 段`)
   assert.equal((text.match(/\d+ \/ \d+/g)||[]).length,1)
  }
  result.checks.push('shared progress shows one completed count and preserves all translation activity states')
  await sr("(()=>{const d=new DataTransfer();d.items.add(new File([''],'demo.pptx'));$('files').files=d.files;$('files').dispatchEvent(new Event('change'));$('translationHelpButton').click()})()")
  for(const w of [900,480]){shared.setContentSize(w,850);await wait(100);const rect=await sr("(()=>{const r=$('translationHelp').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth}})()");assert(rect.left>=0&&rect.right<=rect.width&&rect.bottom<=850,JSON.stringify(rect))}
  result.checks.push('floating help geometry; Escape focus; source file changes close modal; shared 480/900px')
  await sr("if($('translationHelp').open)$('translationHelp').close();comparison={source_name:'source.pptx',output_name:'output.pptx',rows:[]};comparisonBase='/preview-fixture';openComparison()")
  await wait(1500)
  await sr("document.querySelector('#comparison [data-side=source] [data-next]').click()")
  await wait(1500)
  assert.equal(await sr("document.querySelector('#comparison [data-side=source] input').value"),'2')
  assert.equal(await sr("document.querySelector('#comparison [data-side=output] input').value"),'2')
  assert(previewRequests.some(p=>p.page===2&&p.side==='source')&&previewRequests.some(p=>p.page===2&&p.side==='output'))
  assert(previewRequests.every(p=>p.owned),JSON.stringify(previewRequests))
  result.checks.push('sandboxed full-page preview flips both panes and retains LAN ownership cookies')
  await sr("$('comparison').close()")
  sharedJobs=[{id:'shared-comparison',kind:'translate_review',status:'complete',message:'完成',percent:100,downloads:[],result:{outputs:[{path:'first-draft.pptx',comparison_id:'first-id',draft:true},{path:'second-draft.pptx',comparison_id:'second-id',draft:true}],report:{files:[{name:'first',comparison_index:0},{name:'second',comparison_index:1}],stats:{model_status:'complete'},findings:[]}}}]
  await sr("selected='shared-comparison';lastDetail='';refresh()");await wait(100)
  assert.equal(await sr("$('reportCompare').hidden"),false)
  assert((await sr("$('reportCompare').textContent")).includes('初稿'))
  await sr("$('reportFile').value='1';$('reportFile').dispatchEvent(new Event('change'));$('reportCompare').click()");await wait(100)
  assert(sharedComparisonOpens.at(-1).endsWith('/1'))
  await sr("$('comparison').close()")
  // Metadata alone must invalidate the rendered detail, even with no new downloads.
  sharedJobs[0].result.outputs[1].draft=false
  await sr('refresh()');await wait(100)
  assert((await sr("document.querySelector('[data-compare=\"1\"]').textContent")).includes('当前文件'))
  sharedJobs[0].result.outputs[1].path='second-checked.pptx';sharedJobs[0].downloads=[{index:0,name:'second-checked.pptx'}]
  await sr('refresh()');await wait(100);await sr("$('reportCompare').click()");await wait(100)
  assert.equal(await sr("$('comparisonNote').textContent"),'source.pptx → second-checked.pptx')
  await sr("$('comparison').close()")
  result.checks.push('Shared report comparison follows selected document and latest saved output after refresh')
  desktop.webContents.debugger.attach('1.3')
  await desktop.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]})
  assert.equal(await run("getComputedStyle($('dropzone'),'::before').animationName"),'none')
  desktop.webContents.debugger.detach()
  result.checks.push('system reduced-motion preference preserved')
  result.passed=true
 }catch(error){result.error=error.stack}
 finally{fs.writeFileSync(path.join(qaDir,'readable-result.json'),JSON.stringify(result,null,2));clearTimeout(timeout);server.closeAllConnections();server.close();app.emit('will-quit');app.exit(result.passed?0:1)}
})
