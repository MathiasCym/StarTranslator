const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),vm=require('node:vm'),{pathToFileURL}=require('node:url')
function fixture(t,preference){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'star-theme-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}))
 if(preference!==undefined)fs.writeFileSync(path.join(dir,'appearance.json'),preference)
 delete require.cache[require.resolve('../lib/appearance')];const appearance=require('../lib/appearance'),handlers={},sync={}
 const sender={getURL:()=>pathToFileURL(path.resolve(__dirname,'../renderer/index.html')).href},events=[]
 const window={isDestroyed:()=>false,webContents:{...sender,send:(...args)=>events.push(args)},setBackgroundColor:value=>events.push(['background',value])}
 appearance.install({app:{getPath:()=>dir},ipcMain:{on:(name,fn)=>sync[name]=fn,handle:(name,fn)=>handlers[name]=fn},BrowserWindow:{getAllWindows:()=>[window]}})
 return {dir,appearance,handlers,sync,sender,events}
}
test('appearance defaults to dark and does not create a preference on read',t=>{
 const f=fixture(t);assert.equal(f.appearance.get(),'dark');const event={sender:f.sender};f.sync['appearance-theme'](event);assert.equal(event.returnValue,'dark');assert(!fs.existsSync(path.join(f.dir,'appearance.json')))
})
test('appearance persists light mode and broadcasts to app-owned windows',async t=>{
 const f=fixture(t);await f.handlers['set-appearance-theme']({sender:f.sender},'light');assert.equal(f.appearance.get(),'light');assert.equal(JSON.parse(fs.readFileSync(path.join(f.dir,'appearance.json'))).theme,'light');assert(f.events.some(e=>e[0]==='appearance-theme-changed'&&e[1]==='light'));assert.equal(f.appearance.background(),'#FFFFFF')
})
test('saved light mode is restored before windows are created',t=>{
 const f=fixture(t,'{"theme":"light"}');assert.equal(f.appearance.get(),'light');assert.equal(f.appearance.background(),'#FFFFFF')
})
test('invalid or corrupt stored appearance retains the dark default',t=>{
 const f=fixture(t,'invalid json');assert.equal(f.appearance.get(),'dark')
})
test('external and comparison frames cannot change local preferences',async t=>{
 const f=fixture(t);for(const url of ['https://example.com','file:///tmp/index.html','file:///preview.html']){
  const sender={getURL:()=>url};await assert.rejects(f.handlers['set-appearance-theme']({sender},'light'))
 }await assert.rejects(f.handlers['set-appearance-theme']({sender:f.sender,senderFrame:{url:'http://127.0.0.1/document-preview'}},'light'))
 await assert.rejects(f.handlers['set-appearance-theme']({sender:f.sender},'../../bad'));assert.equal(f.appearance.get(),'dark');assert(!fs.existsSync(path.join(f.dir,'appearance.json')))
})
test('unwritable preference does not change the active mode',async t=>{
 const f=fixture(t);fs.mkdirSync(path.join(f.dir,'appearance.json'));await assert.rejects(f.handlers['set-appearance-theme']({sender:f.sender},'light'));assert.equal(f.appearance.get(),'dark');assert(!fs.existsSync(path.join(f.dir,'appearance.json.tmp')))
})
test('browser theme remains local, validates input, and preserves data on toggle',async()=>{
 const memory=new Map(),listeners={},button={setAttribute(){},addEventListener:(name,fn)=>listeners[name]=fn},root={dataset:{},classList:{add(){},remove(){}}},node={value:'untouched translation'}
 const context={requestAnimationFrame:fn=>fn(),location:{search:''},URLSearchParams,localStorage:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)},document:{documentElement:root,querySelectorAll:selector=>selector==='[data-theme-toggle]'?[button]:[],addEventListener:(event,fn)=>listeners[event]=fn},window:{addEventListener(){}}}
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../renderer/shared/appearance.js'),'utf8'),context)
 assert.equal(root.dataset.theme,'dark');listeners.DOMContentLoaded();await listeners.click();assert.equal(root.dataset.theme,'light');assert.equal(node.value,'untouched translation');assert.equal(memory.get('startranslator-appearance'),'light');context.window.StarAppearance.apply('invalid');assert.equal(root.dataset.theme,'light')
})
test('every app entry loads the same theme with explicit surface scope',()=>{
 for(const [name,surface] of [['index.html','desktop'],['file-picker.html','picker'],['shared/index.html','shared']]){
  const html=fs.readFileSync(path.join(__dirname,'../renderer',name),'utf8');assert(html.includes('data-surface="'+surface+'"'));assert(html.includes('appearance.js'));assert(html.includes('appearance-light.css'));assert(html.includes('data-theme-toggle'))
 }
 const setup=fs.readFileSync(path.join(__dirname,'../renderer/setup.html'),'utf8');assert(!setup.includes('appearance-light.css'));assert(!setup.includes('data-theme-toggle'))
 const sources=JSON.parse(fs.readFileSync(path.join(__dirname,'../renderer/shared/appearance-sources.json'))),crypto=require('node:crypto')
 for(const [name,sha] of Object.entries(sources))assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.resolve(__dirname,'..',name),'utf8').replace(/\r\n/g,'\n')).digest('hex'),sha,'Uncovered changed style '+name)
})

test('shared-window initial theme hint is consumed so reload preserves the browser choice',async()=>{
 const memory=new Map();let url=new URL('http://127.0.0.1:8765/?star-theme=dark&other=keep')
 function visit(){
  const root={dataset:{},classList:{add(){},remove(){}}},listeners={}
  const context={requestAnimationFrame:fn=>fn(),location:{search:url.search,href:url.href},URL,URLSearchParams,
   localStorage:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)},
   document:{documentElement:root,querySelectorAll:()=>[],addEventListener:(name,fn)=>listeners[name]=fn},
   window:{history:{replaceState:(_a,_b,value)=>url=new URL(value)},addEventListener(){}}}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../renderer/shared/appearance.js'),'utf8'),context);listeners.DOMContentLoaded()
  return {root,api:context.window.StarAppearance}
 }
 const first=visit();assert.equal(first.root.dataset.theme,'dark');assert(!url.searchParams.has('star-theme'));assert.equal(url.searchParams.get('other'),'keep')
 await first.api.set('light');assert.equal(visit().root.dataset.theme,'light')
})
