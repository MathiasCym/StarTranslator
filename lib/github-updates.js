// Public GitHub Releases transport; no account, Git executable or write token.
const fs=require('node:fs'),io=fs.promises,path=require('node:path'),crypto=require('node:crypto')
const REPOSITORY='MathiasCym/StarTranslator'
const ALLOWED_HOSTS=new Set(['api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com'])
function version(value){const match=/^v?(\d+)\.(\d+)\.(\d+)$/.exec(value||'');if(!match)throw Error('发布版本号无效。');const parts=match.slice(1).map(Number);if(parts.some(n=>!Number.isSafeInteger(n)||n>65535))throw Error('发布版本号无效。');return parts}
function newer(a,b){const x=version(a),y=version(b);for(let i=0;i<3;i++)if(x[i]!==y[i])return x[i]>y[i];return false}
function trusted(url){const value=new URL(url);if(value.protocol!=='https:'||!ALLOWED_HOSTS.has(value.hostname)||value.username||value.password||value.port)throw Error('更新下载地址不属于可信发布服务。');return value.href}
async function fetchTrusted(fetcher,url,options={}){
  let current=trusted(url)
  for(let i=0;i<6;i++){
    const response=await fetcher(current,{...options,redirect:'manual',credentials:'omit'})
    if([301,302,303,307,308].includes(response.status)){
      const location=response.headers.get('location');await response.body?.cancel();if(!location)throw Error('更新下载地址无效。');current=trusted(new URL(location,current).href);continue
    }
    return response
  }
  throw Error('更新下载地址跳转过多。')
}
async function jsonResponse(response){
  if(response.status===404)return null
  if(!response.ok)throw Error(response.status===403?'更新服务访问受限，请稍后重试。':'未能连接更新服务，请稍后重试。')
  const reader=response.body.getReader();let total=0,chunks=[]
  try{for(;;){const {done,value}=await reader.read();if(done)break;total+=value.length;if(total>2*1024*1024)throw Error('发布信息过大。');chunks.push(Buffer.from(value))}}
  finally{reader.releaseLock()}
  try{return JSON.parse(Buffer.concat(chunks).toString('utf8'))}catch{throw Error('发布信息无法读取。')}
}
function candidate(release,current){
  if(!release||release.draft||release.prerelease)return null
  const v=version(release.tag_name).join('.');if(!newer(v,current))return null
  const filename='StarTranslator-Setup-'+v+'.exe'
  const asset=(release.assets||[]).find(a=>a.name===filename&&a.state==='uploaded')
  if(!asset||!Number.isSafeInteger(asset.size)||asset.size<256*1024||asset.size>1024*1024*1024)throw Error('新版本尚未提供完整的 Windows 安装包。')
  if(!/^sha256:[a-f0-9]{64}$/.test(asset.digest||''))throw Error('发布包缺少文件校验信息，暂不能自动更新。')
  const url=new URL(trusted(asset.browser_download_url))
  if(url.hostname!=='github.com'||decodeURIComponent(url.pathname)!=='/'+REPOSITORY+'/releases/download/'+release.tag_name+'/'+filename||url.search||url.hash)throw Error('发布包地址与版本不一致。')
  return {version:v,filename,url:url.href,size:asset.size,sha256:asset.digest.slice(7),notes:String(release.body||'').slice(0,20000),releaseUrl:'https://github.com/'+REPOSITORY+'/releases/tag/'+release.tag_name}
}
async function digest(file){const hash=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(file))hash.update(chunk);return hash.digest('hex')}
async function executable(file){const handle=await io.open(file,'r');try{const dos=Buffer.alloc(64);await handle.read(dos,0,64,0);if(dos.toString('ascii',0,2)!=='MZ')throw Error('下载的文件不是有效安装程序。');const offset=dos.readUInt32LE(60),pe=Buffer.alloc(4);if(offset>4*1024*1024)throw Error('安装程序结构无效。');await handle.read(pe,0,4,offset);if(!pe.equals(Buffer.from([80,69,0,0])))throw Error('安装程序结构无效。')}finally{await handle.close()}}
class GitHubUpdates{
  constructor({currentVersion,userData,fetcher=globalThis.fetch,onStatus=()=>{}}){
    version(currentVersion);this.currentVersion=currentVersion;this.folder=path.join(userData,'updates');this.fetcher=fetcher;this.onStatus=onStatus;this.available=null;this.controller=null;this.downloadPromise=null
    this.state={phase:'idle',currentVersion,progress:0,message:'点击检查更新，获取已发布的新版本。'}
    try{const ready=JSON.parse(fs.readFileSync(path.join(this.folder,'ready.json'),'utf8'));if(newer(ready.version,currentVersion)&&ready.filename==='StarTranslator-Setup-'+ready.version+'.exe'&&/^[a-f0-9]{64}$/.test(ready.sha256)){this.ready=ready;this.update({phase:'ready',newVersion:ready.version,message:'更新包已下载，可关闭并安装。'})}}catch{}
  }
  update(value){Object.assign(this.state,value);this.onStatus(this.snapshot());return this.snapshot()}
  snapshot(){return {...this.state,canDownload:!!this.available}}
  get isDownloading(){return !!this.downloadPromise}
  async release(tag){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);try{return await jsonResponse(await fetchTrusted(this.fetcher,'https://api.github.com/repos/'+REPOSITORY+'/releases/'+(tag?'tags/'+encodeURIComponent(tag):'latest'),{signal:controller.signal,headers:{Accept:'application/vnd.github+json','User-Agent':'StarTranslator-Updates','X-GitHub-Api-Version':'2022-11-28'}}))}finally{clearTimeout(timer)}}
  async check(){
    if(this.isDownloading)throw Error('更新包正在下载。')
    if(this.state.phase==='checking')return this.snapshot()
    this.update({phase:'checking',message:'正在检查已发布的更新…'})
    try{
      this.available=candidate(await this.release(),this.currentVersion)
      if(!this.available){this.ready=null;return this.update({phase:'current',newVersion:'',message:'当前没有可安装的更新。'})}
      const a=this.available
      if(this.ready?.version===a.version&&this.ready.sha256===a.sha256&&fs.existsSync(path.join(this.folder,a.filename))&&(await io.stat(path.join(this.folder,a.filename))).size===a.size&&await digest(path.join(this.folder,a.filename))===a.sha256)return this.update({phase:'ready',newVersion:a.version,notes:a.notes,releaseUrl:a.releaseUrl,message:'更新包已下载，可关闭并安装。'})
      this.ready=null;return this.update({phase:'available',newVersion:a.version,notes:a.notes,releaseUrl:a.releaseUrl,progress:0,message:'发现新版本 v'+a.version+'。'})
    }catch(error){this.update({phase:'error',message:error.message});throw error}
  }
  async cleanupPartial(){await io.mkdir(this.folder,{recursive:true});for(const name of await io.readdir(this.folder))if(/^StarTranslator-Setup-\d+\.\d+\.\d+\.exe\.[a-f0-9-]+\.part$/.test(name))await io.unlink(path.join(this.folder,name)).catch(()=>{})}
  download(){
    if(this.downloadPromise)return this.downloadPromise
    if(!this.available)throw Error('请先检查更新。')
    this.downloadPromise=this.performDownload().finally(()=>{this.downloadPromise=null;this.controller=null})
    return this.downloadPromise
  }
  async performDownload(){
    const a={...this.available},controller=this.controller=new AbortController();await this.cleanupPartial();const temporary=path.join(this.folder,a.filename+'.'+crypto.randomUUID()+'.part'),target=path.join(this.folder,a.filename)
    let handle,reader,bytes=0,last=0
    const timeout=setTimeout(()=>controller.abort(),20*60*1000)
    this.update({phase:'downloading',newVersion:a.version,bytes:0,total:a.size,progress:0,message:'正在下载更新包，可继续使用星译官。'})
    try{
      const response=await fetchTrusted(this.fetcher,a.url,{signal:controller.signal})
      if(!response.ok)throw Error('更新包下载失败，请稍后重试。')
      const declared=response.headers.get('content-length');if(declared&&Number(declared)!==a.size)throw Error('更新包大小与发布记录不一致。')
      handle=await io.open(temporary,'wx');reader=response.body.getReader();const hash=crypto.createHash('sha256')
      for(;;){
        if(controller.signal.aborted)throw Error('cancelled')
        const {done,value}=await reader.read();if(done)break
        bytes+=value.length;if(bytes>a.size)throw Error('更新包大小与发布记录不一致。')
        hash.update(value);let offset=0;while(offset<value.length){const written=await handle.write(value,offset,value.length-offset);if(!written.bytesWritten)throw Error('更新包无法写入磁盘。');offset+=written.bytesWritten}
        if(Date.now()-last>150){last=Date.now();this.update({bytes,progress:Math.floor(bytes/a.size*100)})}
      }
      await handle.close();handle=null
      if(controller.signal.aborted)throw Error('cancelled')
      if(bytes!==a.size||hash.digest('hex')!==a.sha256)throw Error('更新包校验未通过，已清除下载内容，请重新下载。')
      await executable(temporary);await io.unlink(target).catch(error=>{if(error.code!=='ENOENT')throw error});await io.rename(temporary,target)
      this.ready={version:a.version,filename:a.filename,size:a.size,sha256:a.sha256}
      await io.writeFile(path.join(this.folder,'ready.json'),JSON.stringify(this.ready))
      return this.update({phase:'ready',bytes,progress:100,message:'更新包已通过校验，可关闭并安装。'})
    }catch(error){
      if(controller.signal.aborted)return this.update({phase:'cancelled',message:'下载已取消，临时文件已清理。',progress:0})
      this.update({phase:'error',message:error.message});throw error
    }finally{clearTimeout(timeout);await reader?.cancel().catch(()=>{});reader?.releaseLock();await handle?.close().catch(()=>{});await io.unlink(temporary).catch(()=>{})}
  }
  async cancel(){this.controller?.abort();if(this.downloadPromise)await this.downloadPromise.catch(()=>{});return this.snapshot()}
  async prepareInstall(){
    if(this.isDownloading)throw Error('请等待下载与校验完成。')
    if(!this.ready)throw Error('请先下载并校验更新包。')
    const remote=candidate(await this.release('v'+this.ready.version),this.currentVersion)
    if(!remote||remote.sha256!==this.ready.sha256||remote.filename!==this.ready.filename||remote.size!==this.ready.size)throw Error('更新发布记录已变化，请重新检查并下载。')
    const file=path.join(this.folder,remote.filename)
    try{if((await io.stat(file)).size!==remote.size||await digest(file)!==remote.sha256)throw Error('更新包已损坏，请重新下载。');await executable(file)}
    catch(error){this.ready=null;this.available=remote;await io.unlink(path.join(this.folder,'ready.json')).catch(()=>{});this.update({phase:'available',message:'更新包已损坏，请重新下载。'});throw error}
    return file
  }
}
module.exports={GitHubUpdates,version,newer,candidate,trusted,fetchTrusted}
