// Exercise the shipped comparison component against a real native window.
const runtime=require('electron'),path=require('node:path'),fs=require('node:fs')
const root=path.resolve(__dirname,'..'),target=path.resolve(process.argv[2]||root),label=process.argv[3]||'source'
if(!/^[a-z0-9-]+$/.test(label))throw Error('Invalid QA label')
const out=path.join(root,'dist/qa/comparison'),file=path.join(out,label+'-result.json')
if(typeof runtime==='string') {
 fs.mkdirSync(out,{recursive:true});fs.rmSync(file,{force:true})
 const task=require('node:child_process').spawnSync(runtime,[__filename,target,label],{cwd:root,windowsHide:true,timeout:60000,encoding:'utf8'})
 if(fs.existsSync(file)){const r=JSON.parse(fs.readFileSync(file));console.log(r.passed?'Native comparison fullscreen checks passed':r.error)}
 else console.error(task.error?.message||'Comparison worker did not finish: '+(task.stderr||'').slice(-1200))
 process.exit(task.status??1)
}
const {app,BrowserWindow,screen}=runtime,assert=require('node:assert/strict'),http=require('node:http')
const result={passed:false,target,companyDocumentsSent:false,existingInstallationModified:false,checks:[],screenshots:[]}
fs.mkdirSync(out,{recursive:true});app.setPath('userData',path.join(out,label+'-profile'))
const wait=ms=>new Promise(r=>setTimeout(r,ms))
const styles=fs.readFileSync(path.join(target,'renderer/index.html'),'utf8').match(/<link rel="stylesheet"[^>]+>/g).join('').replaceAll('href="','href="/')
const server=http.createServer((req,res)=>{
 const name=new URL(req.url,'http://localhost').pathname
 if(name==='/')return res.end(`<html><head><meta charset="UTF-8">${styles}</head><body><dialog id="comparisonDialog" class="shared-dialog comparison-dialog"><div class="panel-head"><h3>原文与译文</h3><button id="close" class="btn ghost">关闭</button></div><p id="comparisonNote">原稿 → 最新译文</p><div class="comparison-filters"><input placeholder="搜索原文或译文"></div><div class="comparison-scroll"><table><tr><td>中文原稿</td><td>Corrected English</td></tr></table></div></dialog><script src="/shared/comparison-view.js"></script><script>const d=document.querySelector('dialog');document.querySelector('#close').onclick=()=>d.close();function openViewer(){PageComparison.open(d,document.querySelector('.comparison-filters'),document.querySelector('.comparison-scroll'),{source_name:'source.pptx',output_name:'checked.pptx'},{source:'/frame',output:'/frame'})}openViewer()</script></body></html>`)
 if(name==='/frame')return res.end('<html><body style="background:white;color:black">Complete document page</body></html>')
 const resource=path.join(target,'renderer',name.slice(1))
 if(!resource.startsWith(path.join(target,'renderer')+path.sep)||!fs.existsSync(resource)){res.statusCode=404;return res.end()}
 res.setHeader('Content-Type',name.endsWith('.css')?'text/css; charset=utf-8':'text/javascript; charset=utf-8');res.end(fs.readFileSync(resource))
})
const timer=setTimeout(()=>app.exit(2),50000)
server.listen(0,'127.0.0.1',async()=>{
 let win
 try {
  await app.whenReady()
  win=new BrowserWindow({show:false,width:1000,height:700,frame:false,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,backgroundThrottling:false}})
  await win.loadURL(`http://127.0.0.1:${server.address().port}/`)
  const run=code=>win.webContents.executeJavaScript(code,true)
  const until=async predicate=>{for(let i=0;i<80;i++){if(await predicate())return;await wait(75)}throw Error('Fullscreen transition timed out')}
  const enter=async()=>{await run("document.querySelector('[data-expand]').click()");await until(()=>run("!!document.fullscreenElement&&document.querySelector('dialog').classList.contains('pc-expanded')"))}
  const leave=async()=>{await run("document.querySelector('[data-expand]').click()");await until(()=>run("!document.fullscreenElement"))}
  const original=win.getBounds(),display=screen.getDisplayMatching(original)
  await enter();await wait(450)
  assert(win.isFullScreen(),'CSS expansion must also enter actual native fullscreen')
  const full=win.getBounds();assert.deepEqual(full,display.bounds)
  result.window={original,fullscreen:full,display:display.bounds,dpi:display.scaleFactor}
  const frameURL=await run("document.querySelector('iframe').src")
  await run("document.querySelector('[data-mode=text]').click()");await wait(200)
  assert.equal(await run("document.querySelector('.comparison-filters').hidden"),false)
  assert.equal(await run("getComputedStyle(document.querySelector('.pc-panes')).display"),'none')
  assert.equal(await run("document.querySelector('[data-mode=text]').getAttribute('aria-pressed')"),'true')
  assert(await run("(()=>{const a=document.querySelector('.pc-toolbar').getBoundingClientRect(),b=document.querySelector('.comparison-filters').getBoundingClientRect();return b.top>=a.bottom})()"),'Search must not overlap mode controls')
  const image=path.join(out,label+'-fullscreen.png');fs.writeFileSync(image,(await win.webContents.capturePage()).toPNG());result.screenshots.push(image)
  await leave();await wait(450);assert(!win.isFullScreen());assert.deepEqual(win.getBounds(),original)
  assert.equal(await run("document.querySelector('iframe').src"),frameURL)
  assert.equal(await run("document.querySelector('dialog').open"),true)
  result.checks.push('Native fullscreen covers monitor and restores bounds without reloading panes; text/search controls remain separate')
  await enter();win.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});win.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'})
  await until(()=>run("!document.fullscreenElement"));assert.equal(await run("document.querySelector('dialog').open"),true)
  result.checks.push('Escape exits fullscreen and keeps comparison open')
  await enter();await run("document.querySelector('#close').click()")
  await until(()=>!win.isFullScreen());assert.equal(await run("document.querySelector('dialog').open"),false)
  await run('openViewer()');assert.equal(await run("document.querySelector('[data-expand]').getAttribute('aria-pressed')"),'false')
  result.checks.push('Closing fullscreen restores native window; reopened viewer starts in normal mode')
  win.maximize();await wait(350);await enter();await leave();await wait(350);assert(win.isMaximized())
  result.checks.push('Previously maximized window remains maximized after fullscreen')
  await run("document.querySelector('dialog').close()")
  win.unmaximize();await wait(200);win.setFullScreen(true);await wait(350);await run('openViewer()');await enter();await leave()
  assert(win.isFullScreen(),'Do not exit fullscreen that was already active before opening comparison')
  result.checks.push('Pre-existing fullscreen is preserved')
  result.passed=true
 }catch(error){result.error=error.stack}
 finally{clearTimeout(timer);fs.writeFileSync(file,JSON.stringify(result,null,2));if(win&&!win.isDestroyed())win.destroy();server.closeAllConnections();server.close();app.exit(result.passed?0:1)}
})
