// Independent picker, install/uninstall, shared-browser and theme persistence QA.
const runtime=require('electron'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict'),http=require('node:http')
const root=path.resolve(__dirname,'..'),qa=path.join(root,'dist/qa/appearance-windows'),result={passed:false,checks:[],screenshots:[],companyDocumentsSent:false,installationModified:false}
if(typeof runtime==='string'){
 const task=require('node:child_process').spawnSync(runtime,[__filename],{cwd:root,windowsHide:true,encoding:'utf8',timeout:90000});if(task.stdout)process.stdout.write(task.stdout);if(task.status!==0)console.error(task.stderr);process.exit(task.status??1)
}
const {app,BrowserWindow,ipcMain}=runtime,wait=ms=>new Promise(r=>setTimeout(r,ms))
fs.mkdirSync(qa,{recursive:true});app.setPath('userData',fs.mkdtempSync(path.join(qa,'profile-')))
let mode='open',uninstall=false,service
const timeout=setTimeout(()=>app.exit(2),80000)
app.whenReady().then(async()=>{
 try{
 ipcMain.handle('picker-options',()=>({title:'主题测试 · 选择文件',mode,multiple:true,name:'output.docx',directory:'C:/qa',extensions:['docx','pptx','pdf'],locations:[{name:'测试目录',path:'C:/qa'}]}))
 ipcMain.handle('picker-list',()=>({directory:'C:/qa',parent:'C:/',files:[{name:'参考材料',path:'C:/qa/folder',directory:true},{name:'sample.pptx',path:'C:/qa/sample.pptx',size:10000,type:'PPTX',modified:Date.now(),directory:false},{name:'sample.docx',path:'C:/qa/sample.docx',size:20000,type:'DOCX',modified:Date.now(),directory:false}]}))
 ipcMain.handle('setup-info',()=>({version:require('../package.json').version,directory:'C:/Program Files/StarTranslator',scope:'current',uninstall,upgrade:false}))
 let writes=0;for(const route of ['picker-confirm','setup-start','setup-launch'])ipcMain.handle(route,()=>{writes++;throw Error('No installation or file writes are permitted in visual QA')})
 const window=new BrowserWindow({show:false,width:1250,height:850,webPreferences:{preload:path.join(root,'picker-preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true,offscreen:true}})
 window.webContents.setBackgroundThrottling(false)
 const run=code=>window.webContents.executeJavaScript(code)
 async function shot(win, name) {
  win.webContents.setBackgroundThrottling(false)
  await win.webContents.capturePage()
  await wait(220)
  const inspect = code => win.webContents.executeJavaScript(code)
  assert.equal(await inspect("!!document.querySelector('[data-theme-toggle]')"), false)
  if (/^(install|uninstall)/.test(name)) {
    assert.equal(await inspect("getComputedStyle(document.documentElement).colorScheme"), 'dark')
    assert.match(await inspect("getComputedStyle(document.querySelector('#setupAction')).backgroundImage"), /linear-gradient/)
  } else if (name==='setup-picker') {
    assert.equal(await inspect("getComputedStyle(document.body).colorScheme"), 'dark')
  } else {
    assert.equal(await inspect("getComputedStyle(document.documentElement).colorScheme"), 'light')
    assert.equal(await inspect('document.documentElement.scrollWidth <= innerWidth'), true)
  }
  const file = path.join(qa,name+'.png')
  fs.writeFileSync(file,(await win.webContents.capturePage()).toPNG())
  result.screenshots.push(file)
 }
 for(mode of ['open','save','directory']){
  await window.loadFile(path.join(root,'renderer/file-picker.html'));await wait(100);await shot(window,'picker-'+mode)
  await run("document.querySelector('#pickerList [role=option]')?.click();document.getElementById('pickerNew').click();document.getElementById('pickerSearch').focus()");await shot(window,'picker-'+mode+'-selected')
 }
 await window.reload(); await wait(100); await shot(window,'picker-reloaded')
 mode='directory';await window.loadFile(path.join(root,'renderer/file-picker.html'),{query:{setup:'1'}});await wait(100);await shot(window,'setup-picker')
 result.checks.push('Open, save and directory picker with selection, search focus and new folder controls')
 const setup=new BrowserWindow({show:false,width:980,height:660,useContentSize:true,webPreferences:{preload:path.join(root,'setup-preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true,offscreen:true}})
 for(uninstall of [false,true]){
  await setup.loadFile(path.join(root,'renderer/setup.html'));await wait(100);await shot(setup,uninstall?'uninstall':'install')
  const phases=[{phase:'checking'},{phase:'files'},{phase:'registering'},...(uninstall?[]:[{phase:'verifying',percent:60,checked:60,total:100}]),{phase:'complete',directory:'C:/qa/StarTranslator'},{phase:'error',message:uninstall?'星译官仍在运行，请关闭后重试。':'此文件夹不可写，请选择另一个安装位置。'}]
  for(const state of phases){
   setup.webContents.send('setup-status',state);await shot(setup,(uninstall?'uninstall-':'install-')+state.phase)
  }
 }
 result.checks.push('Actual setup preload: install/uninstall, options/progress/verifying/complete/error, fixed dark surroundings; no installer started')
 const jobs=[{id:'demo',kind:'translate_review',status:'complete',message:'校对完成',percent:100,downloads:[],result:{outputs:[],report:{files:[],stats:{model_status:'complete'},findings:[]}}}]
 service=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://localhost').pathname
  if(name==='/shared/session'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({csrf:'appearance-only'}))}
  if(name==='/shared/jobs'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({jobs}))}
  if(name==='/shared/text/languages'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({languages:JSON.parse(fs.readFileSync(path.join(root,'glossary/multilingual.json'))).languages}))}
  if(name.startsWith('/frame')){res.setHeader('Content-Type','text/html');return res.end('<html><body style="background:white;color:#153a55">Original document colors stay intact.</body></html>')}
  const file=name==='/'?path.join(root,'renderer/shared/index.html'):name.startsWith('/assets/')?path.join(root,'renderer',name.slice(1)):path.join(root,'renderer/shared',path.basename(name))
  if(!fs.existsSync(file)){res.statusCode=404;return res.end()};res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':file.endsWith('.png')?'image/png':'text/html');res.end(fs.readFileSync(file))
 })
 await new Promise(resolve=>service.listen(0,'127.0.0.1',resolve))
 const shared=new BrowserWindow({show:false,width:1280,height:900,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,offscreen:true}}),sr=code=>shared.webContents.executeJavaScript(code)
 await shared.loadURL('http://127.0.0.1:'+service.address().port+'/');await wait(200);await shot(shared,'shared-home')
 await sr("(()=>{const d=new DataTransfer();d.items.add(new File(['fixture'],'sample.pptx'));document.getElementById('files').files=d.files;document.getElementById('files').dispatchEvent(new Event('change'));document.querySelector('.translation-choice input').focus()})()");await shot(shared,'shared-selected')
 const directionChecks=await sr(`(async()=>{
  const names=StarDocumentLanguages.names,codes=Object.keys(names),requests=[],original=window.XMLHttpRequest;
  window.XMLHttpRequest=class{constructor(){this.upload={}}open(){}setRequestHeader(){}send(data){requests.push(JSON.parse(data.get('options')));this.onerror()}};
  try {
   for(const source of codes)for(const target of codes.filter(code=>code!==source)){
    $('documentSource').value=source;$('documentSource').onchange();$('documentTarget').value=target;$('documentTarget').onchange();
    await $('form').onsubmit({preventDefault(){}});
    const request=requests[requests.length-1];if(request.direction!==StarDocumentLanguages.direction(source,target))throw Error('Incorrect submitted direction '+request.direction);
   }
   $('documentSource').value='ko';$('documentSource').onchange();$('documentTarget').value='ja-JP';$('documentTarget').onchange();
   document.querySelector('[name=kind][value=check]').checked=true;mode();
   if(!$('documentTranslationLanguages').hidden||$('documentCheckLanguage').hidden||$('documentDirection').options.length!==5)throw Error('Incorrect check controls');
   $('documentDirection').value='en-zh';$('documentDirection').onchange();await $('form').onsubmit({preventDefault(){}});
   if(requests.at(-1).direction!=='en-zh')throw Error('Check submitted translation pair');
   document.querySelector('[name=kind][value=translate_review]').checked=true;mode();await $('form').onsubmit({preventDefault(){}});
   if(requests.at(-1).direction!=='ko>ja-JP')throw Error('Check selection changed translation pair');
   $('swapDocumentLanguages').click();if($('documentSource').value!=='ja-JP'||$('documentTarget').value!=='ko')throw Error('Swap failed');
   $('documentSource').value='ko';$('documentSource').onchange();if($('documentTarget').value==='ko')throw Error('Same-language pair not prevented');
   $('error').hidden=true;
   return {translationPairs:20,checkAndCombined:true,swap:true,sourceOptions:[...$('documentSource').options].map(o=>o.textContent)};
  }finally{window.XMLHttpRequest=original}
 })()`)
 assert.equal(directionChecks.translationPairs,20);assert.equal(directionChecks.sourceOptions.length,5);assert(directionChecks.sourceOptions.every(v=>!v.includes('→')))
 await shot(shared,'shared-language-pair');shared.setContentSize(600,850);await wait(100)
 assert.equal(await sr("document.documentElement.scrollWidth<=innerWidth"),true);await shot(shared,'shared-language-pair-narrow');shared.setContentSize(1280,900)
 await shared.reload();await wait(150);assert.equal(await sr("$('documentSource').value"),'ko');assert.equal(await sr("$('documentTarget').value"),'ja-JP')
 await sr("(()=>{const d=new DataTransfer();d.items.add(new File(['fixture'],'sample.pptx'));$('files').files=d.files;$('files').dispatchEvent(new Event('change'))})()")
 result.checks.push(directionChecks)
 await sr("document.getElementById('openTextTranslation').click()");await wait(100);await shot(shared,'shared-text');await sr("document.querySelector('.text-translator [data-source]').value='保留编辑中的内容。'");assert.equal(await sr("document.querySelector('.text-translator [data-source]').value"),'保留编辑中的内容。');await sr("document.getElementById('sharedWork').click()")
 const dialogs=await sr("[...document.querySelectorAll('dialog')].map(e=>e.id)")
 for(const id of dialogs){await sr("(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());const d=document.getElementById("+JSON.stringify(id)+");d.hidden=false;d.showModal()})()");await shot(shared,'shared-'+id)}
 await sr("document.querySelectorAll('dialog[open]').forEach(d=>d.close())");await shared.reload();await wait(100);await shot(shared,'shared-reloaded')
 result.checks.push({sharedDialogs:dialogs,selectionAndTextRetained:true,reloadLayout:true})
 assert.equal(writes,0);result.passed=true
 }catch(error){result.error=error.stack}
 finally{fs.writeFileSync(path.join(qa,'result.json'),JSON.stringify(result,null,2));clearTimeout(timeout);if(service){service.closeAllConnections();service.close()}console.log(result.passed?'Additional appearance windows passed':result.error);app.exit(result.passed?0:1)}
})
