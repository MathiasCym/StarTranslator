// Real Chromium pagination of prepared OfficeCLI HTML; never contacts a model.
const runtime=require('electron'),fs=require('node:fs'),path=require('node:path');
const inputs=process.argv.slice(2).map(p=>path.resolve(p));
const runKey=require('node:crypto').createHash('sha256').update(JSON.stringify(inputs)).digest('hex').slice(0,12);
const resultPath=path.resolve('dist/qa/word-table/render-'+runKey+'-private.json');
if(typeof runtime==='string'){
 fs.rmSync(resultPath,{force:true});
 const r=require('node:child_process').spawnSync(runtime,[__filename,...inputs],{windowsHide:true,timeout:60000,encoding:'utf8'});
 if(fs.existsSync(resultPath)){
  const value=JSON.parse(fs.readFileSync(resultPath));console.log(Array.isArray(value)?JSON.stringify(value.map(({text,...v})=>v)):JSON.stringify(value));
 }else console.error(r.error?.message||r.stdout||r.stderr||'Preview worker did not write a result');
 process.exit(r.status??1);
}
const {app,BrowserWindow}=runtime,assert=require('node:assert/strict');
app.on('window-all-closed',()=>{});
app.setPath('userData',path.resolve('dist/qa/word-table/electron-profile'));
const wait=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 const results=[];
 try{
  for(const file of inputs){
   const win=new BrowserWindow({show:false,width:950,height:1250,webPreferences:{sandbox:true,backgroundThrottling:false}});
   win.webContents.session.webRequest.onBeforeRequest((d,cb)=>cb({cancel:!d.url.startsWith('file:')&&!d.url.startsWith('data:')}));
   await win.loadFile(file);await wait(3500);
   const run=s=>win.webContents.executeJavaScript(s,true);
   for(let i=0;i<80&&await run('!!window._starWordPaginating');i++)await wait(100);
   assert(!await run('!!window._starWordPaginating'),'Pagination did not settle');
   const original=JSON.stringify(fs.readFileSync(file,'utf8'));
   const info=await run(`(()=>{const p=[...document.querySelectorAll('.page-wrapper')];
    const normalize=s=>[...s].filter(c=>c.trim()).join('');
    const text=d=>[...d.querySelectorAll('.page-body')].map(b=>{b=b.cloneNode(true);b.querySelectorAll('[data-tbl-header="1"]').forEach(r=>r.remove());return b.textContent}).join('');
    const before=new DOMParser().parseFromString(${original},'text/html');
    return {pages:p.length,texts:p.map(w=>w.querySelector('.page-body').textContent),heights:p.map(w=>{const page=w.querySelector('.page');return [page.scrollHeight,parseFloat(getComputedStyle(page).minHeight)]}),preserved:normalize(text(before))===normalize(text(document)),colgroups:[...document.querySelectorAll('.page-body>table')].map(t=>t.querySelectorAll(':scope>colgroup').length)}})()`);
   assert(info.preserved,'Pagination changed or lost document text');
   assert(info.texts.every(t=>t.trim().length>0),'Preview contains an empty page');
   assert(info.colgroups.every(n=>n===1),'Table continuation lost its column grid');
   win.webContents.setZoomFactor(.55);await wait(250);
   info.heights=[];const grids=new Map();
   for(let i=1;i<=info.pages;i++){
    await run(`window.postMessage({channel:'star-page-preview',token:null,type:'goto',page:${i}},'*')`);await wait(200);
    const height=await run("(()=>{const p=[...document.querySelectorAll('.page-wrapper')].find(w=>!w.hidden).querySelector('.page');return [p.scrollHeight,parseFloat(getComputedStyle(p).minHeight)]})()");
    info.heights.push(height);assert(height[0]>0&&height[0]<=height[1]+6,'A visible preview page overflows its paper height: '+JSON.stringify(height));
    const columns=await run("[...document.querySelector('.page-wrapper:not([hidden]) .page-body').querySelectorAll(':scope>table')].map((t,i)=>{const s=t.getBoundingClientRect().width/t.offsetWidth||1;return {key:t.dataset.path||String(i),widths:[...t.querySelectorAll(':scope>colgroup>col')].map(c=>c.getBoundingClientRect().width/s)}})");
    for(const grid of columns){const before=grids.get(grid.key);if(before)assert(before.length===grid.widths.length&&before.every((w,j)=>Math.abs(w-grid.widths[j])<2),'Continuation column widths changed');else grids.set(grid.key,grid.widths);}
    const image=file.replace(/\.html$/,`-page-${i}.png`);fs.writeFileSync(image,(await win.webContents.capturePage()).toPNG());
   }
   results.push({file,pages:info.pages,text:info.texts.join(''),colgroups:info.colgroups,heights:info.heights,passed:true});win.destroy();
  }
  fs.writeFileSync(resultPath,JSON.stringify(results,null,2));
  console.log(JSON.stringify(results.map(({text,...r})=>r)));app.exit(0);
 }catch(e){fs.writeFileSync(resultPath,JSON.stringify({passed:false,error:e.stack,completed:results.map(({text,...v})=>v)},null,2));app.exit(1);}
});
