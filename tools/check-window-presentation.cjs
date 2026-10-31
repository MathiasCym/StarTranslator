// Measure the application's own default window. Never replace it with a test-sized window.
const runtime=require('electron')
const scenarios={
 'compact':{width:1280,height:800,dpi:1},
 '1080p':{width:1920,height:1080,dpi:1},
 '2240-150':{width:2240,height:1400,dpi:1.5},
 '4k-150':{width:3840,height:2160,dpi:1.5},
 '4k-200':{width:3840,height:2160,dpi:2}
}
const scenarioKey=process.argv.find(a=>a.startsWith('--display='))?.slice(10),scenario=scenarios[scenarioKey]
if(scenarioKey&&!scenario)throw Error('Unknown display scenario')
if(typeof runtime==='string'){
 const path=require('node:path'),fs=require('node:fs'),{spawnSync}=require('node:child_process')
 const root=path.resolve(__dirname,'..'),label=process.argv[3]||'source',out=path.join(root,'dist/qa/presentation',label+'-result.json')
 if(!/^[a-z0-9-]+$/.test(label))throw Error('Invalid QA label')
 fs.rmSync(out,{force:true})
 const task=spawnSync(runtime,[__filename,process.argv[2]||root,label,...process.argv.slice(4),...(scenario?['--force-device-scale-factor='+scenario.dpi]:[])],{cwd:root,windowsHide:true,timeout:90000,encoding:'utf8'})
 if(fs.existsSync(out)){const r=JSON.parse(fs.readFileSync(out));console.log(r.passed?'Default window presentation passed: '+JSON.stringify(r.default):r.error)}
 else console.error(task.error?.message||'Default window presentation did not finish: '+(task.stderr||'').slice(-1500))
 process.exit(task.status??1)
}
const {app,BrowserWindow,screen,ipcMain}=runtime,fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict')
const root=path.resolve(__dirname,'..'),target=path.resolve(process.argv[2]),label=process.argv[3],measure=process.argv.includes('--measure')
const out=path.join(root,'dist/qa/presentation'),result={passed:false,target,companyDocumentsSent:false,existingInstallationModified:false,screenshots:[]},wait=ms=>new Promise(r=>setTimeout(r,ms))
fs.mkdirSync(out,{recursive:true});app.setPath('userData',path.join(out,label+'-profile'))
app.getVersion=()=>JSON.parse(fs.readFileSync(path.join(target,'package.json'))).version
BrowserWindow.prototype.show=function(){}
if(target.endsWith('.asar'))Object.defineProperty(process,'resourcesPath',{value:path.dirname(target),configurable:true})
const server=http.createServer((_req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({data:[{id:'ui-only'}]}))})
const timeout=setTimeout(()=>app.exit(2),70000)
server.listen(0,'127.0.0.1',async()=>{
 try{
  process.env.NOVATERM_LLM_PROVIDER='compatible';process.env.NOVATERM_LLM_BASE_URL=`http://127.0.0.1:${server.address().port}/v1`;process.env.NOVATERM_LLM_MODEL='ui-only';process.env.NOVATERM_LLM_API_KEY=''
  if(scenario){
   await app.whenReady()
   const actual=screen.getPrimaryDisplay(),display={...actual,scaleFactor:scenario.dpi,bounds:{x:0,y:0,width:Math.round(scenario.width/scenario.dpi),height:Math.round(scenario.height/scenario.dpi)},workArea:{x:0,y:0,width:Math.round(scenario.width/scenario.dpi),height:Math.round(scenario.height/scenario.dpi)-48}}
   display.workAreaSize={width:display.workArea.width,height:display.workArea.height}
   screen.getDisplayNearestPoint=screen.getDisplayMatching=()=>display
   result.simulatedDisplay={name:scenarioKey,...scenario}
  }
  require(path.join(target,'main.js'))
  ipcMain.removeHandler('startup-update-notice');ipcMain.handle('startup-update-notice',()=>null)
  await app.whenReady()
  let win
  for(let i=0;i<250;i++){
   win=BrowserWindow.getAllWindows().find(w=>w.webContents.getURL().endsWith('/renderer/index.html'))
   if(win&&!win.webContents.isLoading()&&await win.webContents.executeJavaScript('typeof initialized!=="undefined"&&initialized').catch(()=>false))break
   await wait(100)
  }
  assert(win,'The real main window was not created')
  result.runtimeResources=process.resourcesPath
  result.backendPort=await win.webContents.executeJavaScript('window.api.backendPort()')
  assert(result.backendPort,'The actual backend must start before checking packaged dialogs')
  win.webContents.setBackgroundThrottling(false)
  const run=code=>win.webContents.executeJavaScript(code),display=screen.getDisplayMatching(win.getBounds()),dpi=display.scaleFactor,zoom=win.webContents.getZoomFactor(),bounds=win.getBounds()
  win.webContents.debugger.attach('1.3')
  await win.webContents.debugger.sendCommand('Emulation.setFocusEmulationEnabled',{enabled:true})
  result.version=app.getVersion();result.default={bounds,scaleFactor:dpi,zoomFactor:zoom,screenPixels:{width:bounds.width*dpi,height:bounds.height*dpi},workArea:display.workArea}
  const layout=()=>run(`(()=>{const main=document.querySelector('body>main'),aside=document.querySelector('.task-options'),button=$('runBtn').getBoundingClientRect();return {width:innerWidth,height:innerHeight,bodyFont:parseFloat(getComputedStyle(document.body).fontSize),buttonFont:parseFloat(getComputedStyle($('runBtn')).fontSize),mainScroll:main.scrollHeight-main.clientHeight,asideScroll:aside.scrollHeight-aside.clientHeight,horizontal:document.documentElement.scrollWidth-innerWidth,buttonBottom:button.bottom}})()`)
  const capture=async name=>{await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});await wait(1100);const image=await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true}),bytes=image.toPNG(),file=path.join(out,label+'-'+name+'.png');fs.writeFileSync(file,bytes);result.screenshots.push({file,pixelWidth:bytes.readUInt32BE(16),pixelHeight:bytes.readUInt32BE(20)});assert(bytes.length>15000,'Missing real window image')}
  const checkFocus=async(selector,name)=>{
   await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'rawKeyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9})
   await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9})
   await run(`document.querySelector(${JSON.stringify(selector)}).focus()`);await wait(180)
   await capture(name)
   const value=await run(`(()=>{const e=document.querySelector(${JSON.stringify(selector)}),r=e.getBoundingClientRect(),s=getComputedStyle(e),outset=Math.max(0,parseFloat(s.outlineWidth)+parseFloat(s.outlineOffset)),clipped=[];for(let a=e.parentElement;a;a=a.parentElement){const t=getComputedStyle(a),b=a.getBoundingClientRect(),left=b.left+a.clientLeft,top=b.top+a.clientTop;if(/auto|scroll|hidden|clip/.test(t.overflowX)&&(r.left-outset<left-.75||r.right+outset>left+a.clientWidth+.75))clipped.push({parent:a.id||a.className,axis:'x'});if(/auto|scroll|hidden|clip/.test(t.overflowY)&&(r.top-outset<top-.75||r.bottom+outset>top+a.clientHeight+.75))clipped.push({parent:a.id||a.className,axis:'y'})}return {selector:${JSON.stringify(selector)},focusVisible:e.matches(':focus-visible'),outline:s.outlineWidth,outset,clipped}})()`)
   ;(result.focusChecks||=[]).push(value)
   if(!measure){assert(value.focusVisible,'Keyboard focus must remain visible: '+selector);assert.equal(value.clipped.length,0,JSON.stringify(value))}
  }
  await run("state.files=[];state.references=[];setMode('translate');renderFiles()")
  result.empty=await layout();await capture('empty')
  result.dropzone=await run(`(()=>{const zone=$('dropzone'),style=getComputedStyle(zone,'::before'),portrait=zone.querySelector('img');return {animation:style.animationName,duration:style.animationDuration,imageLoaded:portrait.complete&&portrait.naturalWidth>0,portrait:portrait.getBoundingClientRect().width,glass:getComputedStyle(zone).backdropFilter,titleDrag:getComputedStyle(document.querySelector('.topbar')).webkitAppRegion}})()`)
  assert(result.dropzone.imageLoaded&&result.dropzone.titleDrag==='drag',JSON.stringify(result.dropzone))
  assert(result.dropzone.animation==='sheen'||await run("matchMedia('(prefers-reduced-motion:reduce)').matches"),JSON.stringify(result.dropzone))
  if(!measure)assert(result.dropzone.portrait>=(result.empty.height>740?140:75),JSON.stringify(result.dropzone))
  await run("state.files=Array.from({length:12},(_,i)=>'C:/qa/多文件布局测试文档'+(i+1)+'.pptx');state.references=['C:/qa/参考材料.docx'];renderFiles();$('referencesPanel').open=true")
  result.loaded=await layout();result.default.bodyScreenPixels=result.loaded.bodyFont*zoom*dpi;await capture('home')
  result.compact=await run(`(()=>{const zone=$('dropzone'),rect=zone.getBoundingClientRect(),portrait=zone.querySelector('img').getBoundingClientRect();return {height:rect.height,portrait:portrait.width,animation:getComputedStyle(zone,'::before').animationName}})()`)
  if(!measure)assert(result.compact.height<85&&result.compact.portrait>=39,JSON.stringify(result.compact))
  if(!measure){
   // Windows can round the outer frame up by two DIP at fractional scaling.
   assert(result.default.screenPixels.width<=1520+2*dpi&&result.default.screenPixels.height<=980+2*dpi,JSON.stringify(result.default))
   assert(result.default.bodyScreenPixels>=15.9&&result.default.bodyScreenPixels<=19.01,JSON.stringify(result.default))
   assert(result.loaded.mainScroll<3&&result.loaded.asideScroll<3&&result.loaded.horizontal===0&&result.loaded.buttonBottom<=result.loaded.height,JSON.stringify(result.loaded))
   assert(Math.abs(result.screenshots[1].pixelWidth-win.getContentBounds().width*dpi)<=3,'Screenshot must retain actual screen pixels')
  }
  await run("$('openModel').onclick()");await wait(200);await capture('model')
  assert.equal(await run("$('modelModal').hidden"),false,'The actual model dialog must open')
  await checkFocus('#modelProfileName','model-name-focus')
  await checkFocus('#modelPreset','model-provider-focus')
  await checkFocus('#modelKey','model-key-focus')
  await run("profileState={...profileState,active:'qa-model',editing:'qa-model',encryption:'dpapi',profiles:[{id:'qa-model',name:'团队模型',model:'ui-only'},{id:'qa-spare',name:'备用模型',model:'ui-only'}]};renderProfiles();updateProfileControls()")
  await checkFocus('#profileList [data-profile]','model-profile-focus')
  await run("$('modelClose').click()")
  await run('showLan()')
  result.lan=await run("(()=>{const d=$('lanDialog'),r=d.getBoundingClientRect(),b=$('closeLan'),c=b.getBoundingClientRect();return {width:r.width,height:r.height,horizontal:d.scrollWidth-d.clientWidth,centerOffset:Math.abs(r.left+r.width/2-innerWidth/2),closeVisible:c.top>=0&&c.bottom<=innerHeight&&b.contains(document.elementFromPoint(c.left+c.width/2,c.top+c.height/2))}})()")
  result.lan.screenWidth=result.lan.width*zoom*dpi
  if(!measure){assert(result.lan.width<=681&&result.lan.width>400,JSON.stringify(result.lan));assert(result.lan.centerOffset<2&&result.lan.horizontal<2&&result.lan.closeVisible,JSON.stringify(result.lan))}
  await checkFocus('#lanPort','lan-port-focus')
  await checkFocus('#lanToggle','lan-toggle-focus')
  await run("lanStatus={enabled:true,port:8765,addresses:['http://192.168.1.10:8765','http://10.0.0.10:8765','http://127.0.0.1:8765']};renderLan()")
  result.lan.enabled=await run("(()=>{const d=$('lanDialog'),b=d.querySelector('.lan-dialog-body');return {bodyHeight:b.clientHeight,bodyScroll:b.scrollHeight-b.clientHeight,horizontal:b.scrollWidth-b.clientWidth,dialogHeight:d.getBoundingClientRect().height}})()")
  await capture('lan-enabled')
  if(!measure&&result.loaded.height>=740)assert(result.lan.enabled.bodyScroll<2&&result.lan.enabled.horizontal<2,JSON.stringify(result.lan.enabled))
  await checkFocus('#lanAddresses input','lan-address-focus')
  await checkFocus('#lanRemote','lan-remote-focus')
  await run("$('closeLan').click()")
  await run("$('openLexicon').click()");await wait(200);await capture('glossary');await run("$('closeLexicon').click()")
  await run(`loadReport({report_id:'presentation',kind:'check',files:[{path:'C:/qa/sample.pptx',name:'sample.pptx'}],stats:{model_status:'complete',segments:10,judged:10,rule_hits:0,llm_hits:10},findings:Array.from({length:10},(_,i)=>({file:'sample.pptx',file_path:'C:/qa/sample.pptx',slide:i+1,method:'llm',editable:true,found_text:'Second half strategy',suggested:'H2 strategy',reason:'统一全文用语',context:'Example context'}))});openReport()`)
  await capture('report');result.passed=true
 }catch(error){result.error=error.stack}
 finally{fs.writeFileSync(path.join(out,label+'-result.json'),JSON.stringify(result,null,2));clearTimeout(timeout);server.closeAllConnections();server.close();app.emit('will-quit');app.exit(result.passed?0:1)}
})
