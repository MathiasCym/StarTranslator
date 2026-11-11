// App-owned appearance only. Never change Windows or document colors.
const fs=require('node:fs'),path=require('node:path'),{pathToFileURL}=require('node:url')
let installed=false,current='dark',electron,location
const remote=new Set()
function valid(value){return value==='dark'||value==='light'}
function trusted(sender,frame){
 const url=sender?.getURL?.()
 if(frame?.url&&frame.url!==url)return false
 return ['index.html','file-picker.html'].some(name=>url===pathToFileURL(path.join(__dirname,'../renderer',name)).href)
}
function get(){return current}
function background(){return current==='light'?'#FFFFFF':'#081320'}
function install(api=require('electron')){
 if(installed)return;installed=true;electron=api
 location=path.join(api.app.getPath('userData'),'appearance.json')
 try{const data=JSON.parse(fs.readFileSync(location,'utf8'));if(valid(data.theme))current=data.theme}catch{}
 api.ipcMain.on('appearance-theme',event=>{event.returnValue=trusted(event.sender,event.senderFrame)?current:'dark'})
 api.ipcMain.handle('set-appearance-theme',async(event,value)=>{
  if(!trusted(event.sender,event.senderFrame)||!valid(value))throw Error('界面模式不正确。')
  fs.mkdirSync(path.dirname(location),{recursive:true});const temporary=location+'.tmp'
  try{fs.writeFileSync(temporary,JSON.stringify({theme:value})+'\n',{mode:0o600});fs.renameSync(temporary,location)}
  finally{try{fs.unlinkSync(temporary)}catch{}}
  current=value
  for(const window of api.BrowserWindow.getAllWindows()){
   if(window.isDestroyed())continue
   if(trusted(window.webContents)){window.setBackgroundColor(background());window.webContents.send('appearance-theme-changed',value)}
   else if(remote.has(window.webContents)){
    window.setBackgroundColor(background())
    window.webContents.executeJavaScript('window.StarAppearance?.apply('+JSON.stringify(value)+',false)').catch(()=>{})
   }
  }
  return value
 })
}
function shared(window){const contents=window.webContents;remote.add(contents);window.once('closed',()=>remote.delete(contents))}
module.exports={install,get,background,shared,valid,trusted}
