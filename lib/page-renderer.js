// Runs in a separate hidden Electron process, with no application/backend session.
const { app, BrowserWindow, session } = require('electron')
const fs = require('fs'), path = require('path')
async function run() {
  const at = process.argv.indexOf('--star-render-pages')
  const input = path.resolve(process.argv[at+1]), folder = path.resolve(process.argv[at+2])
  fs.mkdirSync(path.join(folder,'chromium'),{recursive:true});app.setPath('userData',path.join(folder,'chromium'))
  app.commandLine.appendSwitch('force-device-scale-factor','1')
  await app.whenReady()
  const isolated = session.fromPartition('page-render-'+process.pid)
  isolated.webRequest.onBeforeRequest((details,callback) => {
    callback({ cancel: !details.url.startsWith('data:') && details.url !== require('url').pathToFileURL(input).href })
  })
  const window = new BrowserWindow({show:false,width:1280,height:720,webPreferences:{offscreen:true,session:isolated,
    nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}})
  try {
    await window.loadFile(input)
    const count = await window.webContents.executeJavaScript(`(async()=>{
      await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode().catch(()=>{})));
      return document.querySelectorAll('.slide').length;
    })()`)
    if (!count) throw Error('No pages rendered')
    const pages=[]
    for(let i=0;i<count;i++) {
      if(fs.existsSync(path.join(folder,'cancel')))throw Error('Cancelled')
      const size = await window.webContents.executeJavaScript(`(()=>{
        const slides=[...document.querySelectorAll('.slide')],page=slides[${i}];
        page.style.display='block';const w=page.offsetWidth,h=page.offsetHeight;
        slides.forEach(s=>s.style.display='none');page.style.display='block';
        document.body.replaceChildren(page);document.body.style.cssText='margin:0;padding:0;overflow:hidden;background:white';
        window.__starPages=window.__starPages||slides;
        page.style.cssText+=';position:absolute;left:0;top:0;margin:0;transform-origin:0 0;transform:scale('+1280/w+')';
        return {height:Math.round(1280*h/w)};
      })()`)
      window.setContentSize(1280,size.height)
      await new Promise(resolve=>setTimeout(resolve,100))
      const file=`page-${i+1}.png`
      fs.writeFileSync(path.join(folder,file),(await window.webContents.capturePage()).toPNG())
      pages.push({file,shapes:[]})
      // Reattach all retained page nodes before selecting the next page.
      await window.webContents.executeJavaScript(`document.body.replaceChildren(...window.__starPages)`)
    }
    fs.writeFileSync(path.join(folder,'manifest.json'),JSON.stringify({pages,native:false}))
  } finally {window.destroy()}
  app.quit()
}
module.exports={run}
