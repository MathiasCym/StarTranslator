// Public releases from configured owned mirrors, with GitHub as a fallback.
const fs=require('node:fs'),io=fs.promises,path=require('node:path'),crypto=require('node:crypto')
const {GITHUB,mirrors,manifest}=require('./distribution-sources')
function version(value){const match=/^v?(\d+)\.(\d+)\.(\d+)$/.exec(value||'');if(!match)throw Error('发布版本号无效。');const parts=match.slice(1).map(Number);if(parts.some(n=>!Number.isSafeInteger(n)||n>65535))throw Error('发布版本号无效。');return parts}
function newer(a,b){const x=version(a),y=version(b);for(let i=0;i<3;i++)if(x[i]!==y[i])return x[i]>y[i];return false}
function trusted(url){return GITHUB.trusted(url)}
async function fetchTrusted(fetcher,url,options={},validateUrl=trusted){
  let current=validateUrl(url)
  for(let i=0;i<6;i++){
    const response=await fetcher(current,{...options,validateUrl,redirect:'manual',credentials:'omit'})
    if([301,302,303,307,308].includes(response.status)){
      const location=response.headers.get('location');await response.body?.cancel();if(!location)throw Error('更新下载地址无效。');current=validateUrl(new URL(location,current).href);continue
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
function candidate(release,current,source=GITHUB){
  if(!release||release.draft||release.prerelease)return null
  const v=version(release.tag_name).join('.');if(!newer(v,current))return null
  const filename='StarTranslator-Setup-'+v+'.exe'
  const asset=(release.assets||[]).find(a=>a.name===filename&&a.state==='uploaded')
  if(!asset||!Number.isSafeInteger(asset.size)||asset.size<256*1024||asset.size>1024*1024*1024)throw Error('新版本尚未提供完整的 Windows 安装包。')
  if(!/^sha256:[a-f0-9]{64}$/.test(asset.digest||''))throw Error('发布包缺少文件校验信息，暂不能自动更新。')
  const url=source.assetUrl(asset.browser_download_url,release.tag_name,filename)
  return {version:v,filename,url,size:asset.size,sha256:asset.digest.slice(7),notes:String(release.body||'').slice(0,20000),releaseUrl:source.web+'/releases/tag/'+release.tag_name,source:source.id,sourceName:source.name}
}
async function digest(file){const hash=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(file))hash.update(chunk);return hash.digest('hex')}
async function executable(file){const handle=await io.open(file,'r');try{const dos=Buffer.alloc(64);await handle.read(dos,0,64,0);if(dos.toString('ascii',0,2)!=='MZ')throw Error('下载的文件不是有效安装程序。');const offset=dos.readUInt32LE(60),pe=Buffer.alloc(4);if(offset>4*1024*1024)throw Error('安装程序结构无效。');await handle.read(pe,0,4,offset);if(!pe.equals(Buffer.from([80,69,0,0])))throw Error('安装程序结构无效。')}finally{await handle.close()}}
class GitHubUpdates{
  constructor({currentVersion,userData,fetcher=globalThis.fetch,onStatus=()=>{},distribution={schema:1,mirrors:[]}}){
    version(currentVersion);this.currentVersion=currentVersion;this.folder=path.join(userData,'updates');this.fetcher=fetcher;this.onStatus=onStatus;this.available=null;this.controller=null;this.downloadPromise=null
    this.sources=[...mirrors(distribution),GITHUB]
    this.state={phase:'idle',currentVersion,progress:0,sourceName:this.sources[0].name,message:'点击检查更新，获取已发布的新版本。'}
    try{const ready=JSON.parse(fs.readFileSync(path.join(this.folder,'ready.json'),'utf8'));if(newer(ready.version,currentVersion)&&ready.filename==='StarTranslator-Setup-'+ready.version+'.exe'&&/^[a-f0-9]{64}$/.test(ready.sha256)){this.ready=ready;this.update({phase:'ready',newVersion:ready.version,message:'更新包已下载，可关闭并安装。'})}}catch{}
  }
  update(value){Object.assign(this.state,value);this.onStatus(this.snapshot());return this.snapshot()}
  snapshot(){return {...this.state,canDownload:!!this.available}}
  get isDownloading(){return !!this.downloadPromise}
  async release(tag,source=GITHUB,signal){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),source.provider==='github'?30000:12000)
    const abort=()=>controller.abort();if(signal?.aborted)controller.abort();signal?.addEventListener('abort',abort,{once:true})
    const options={signal:controller.signal,headers:{Accept:source.provider==='github'?'application/vnd.github+json':'application/json','User-Agent':'StarTranslator-Updates'}}
    if(source.provider==='github')options.headers['X-GitHub-Api-Version']='2022-11-28'
    const read=url=>fetchTrusted(this.fetcher,url,options,source.trusted).then(jsonResponse)
    try{
      const response=await fetchTrusted(this.fetcher,source.api+'releases/'+(tag?'tags/'+encodeURIComponent(tag):'latest'),options,source.trusted)
      let release
      if(response.status===400&&source.provider!=='github'){
        await response.body?.cancel()
        const list=await read(source.api+'releases?per_page=100&page=1&direction=desc')
        if(!Array.isArray(list))throw Error('镜像发行版列表无法读取。')
        release=tag?list.find(r=>r.tag_name===tag):list.filter(r=>r&&!r.draft&&!r.prerelease&&r.release_status!=='pre'&&/^v?\d+\.\d+\.\d+$/.test(r.tag_name||'')).sort((a,b)=>newer(a.tag_name,b.tag_name)?-1:newer(b.tag_name,a.tag_name)?1:0)[0]
        release??=null
      }else release=await jsonResponse(response)
      if(source.provider!=='github'&&release?.release_status==='pre')return {...release,prerelease:true}
      if(!release||release.draft||release.prerelease||source.provider==='github')return release
      const v=version(release.tag_name).join('.');if(tag&&release.tag_name!==tag)throw Error('发布包地址与版本不一致。')
      if(!newer(v,this.currentVersion))return release
      const filename='StarTranslator-Setup-'+v+'.exe',assets=release.assets
      if(!Array.isArray(assets))throw Error('镜像尚未提供完整的发布文件。')
      const installer=assets.filter(a=>a.name===filename),metadata=assets.filter(a=>a.name==='update.json')
      if(installer.length!==1||metadata.length!==1)throw Error('镜像尚未提供完整的发布文件。')
      const url=source.assetUrl(installer[0].browser_download_url,release.tag_name,filename)
      const details=manifest(await read(source.assetUrl(metadata[0].browser_download_url,release.tag_name,'update.json')),v,filename)
      return {...release,assets:[{name:filename,state:'uploaded',size:details.size,digest:'sha256:'+details.sha256,browser_download_url:url}]}
    }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort)}
  }
  async findUpdate(){
    let firstError,responded=false
    for(const source of this.sources){
      try{const release=await this.release(undefined,source),value=candidate(release,this.currentVersion,source);responded=true;if(value)return value}
      catch(error){firstError??=error}
    }
    if(!responded)throw firstError||Error('未能连接更新服务，请稍后重试。')
    return null
  }
  async check(){
    if(this.isDownloading)throw Error('更新包正在下载。')
    if(this.state.phase==='checking')return this.snapshot()
    this.update({phase:'checking',message:'正在检查已发布的更新…'})
    try{
      this.available=await this.findUpdate()
      if(!this.available){this.ready=null;return this.update({phase:'current',newVersion:'',message:'当前没有可安装的更新。'})}
      const a=this.available
      if(this.ready?.version===a.version&&this.ready.sha256===a.sha256&&fs.existsSync(path.join(this.folder,a.filename))&&(await io.stat(path.join(this.folder,a.filename))).size===a.size&&await digest(path.join(this.folder,a.filename))===a.sha256){this.ready={...this.ready,source:a.source};await io.writeFile(path.join(this.folder,'ready.json'),JSON.stringify(this.ready));return this.update({phase:'ready',sourceName:a.sourceName,newVersion:a.version,notes:a.notes,releaseUrl:a.releaseUrl,message:'更新包已下载，可关闭并安装。'})}
      this.ready=null;return this.update({phase:'available',sourceName:a.sourceName,newVersion:a.version,notes:a.notes,releaseUrl:a.releaseUrl,progress:0,message:'发现新版本 v'+a.version+'。'})
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
    const original={...this.available},controller=this.controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20*60*1000)
    let firstError
    try{
      await this.cleanupPartial()
      for(const source of [...this.sources.filter(s=>s.id===original.source),...this.sources.filter(s=>s.id!==original.source)]){
        try{
          if(controller.signal.aborted)throw Error('cancelled')
          let a=original
          if(source.id!==original.source){
            this.update({phase:'downloading',bytes:0,progress:0,message:'当前来源下载未完成，正在核对备用来源…'})
            a=candidate(await this.release('v'+original.version,source,controller.signal),this.currentVersion,source)
            if(!a||a.version!==original.version||a.size!==original.size||a.sha256!==original.sha256)throw Error('备用来源与原发布文件不一致，未使用该文件。')
          }
          let routeError
          for(const networkMode of source.provider==='github'?['system']:['direct','system']){
            try{return await this.downloadCandidate(a,controller,networkMode)}
            catch(error){if(controller.signal.aborted)throw error;if(error.code&&!['ECONNRESET','ENOTFOUND','ETIMEDOUT'].includes(error.code))throw error;routeError=error}
          }
          throw routeError
        }catch(error){if(controller.signal.aborted)throw error;firstError??=error;if(error.code&&!['ECONNRESET','ENOTFOUND','ETIMEDOUT'].includes(error.code))throw error}
      }
      throw firstError||Error('更新包下载失败，请稍后重试。')
    }catch(error){
      if(controller.signal.aborted)return this.update({phase:'cancelled',message:'下载已取消，临时文件已清理。',progress:0})
      this.update({phase:'error',message:error.message});throw error
    }finally{clearTimeout(timeout)}
  }
  async downloadCandidate(a,controller,networkMode='system'){
    const temporary=path.join(this.folder,a.filename+'.'+crypto.randomUUID()+'.part'),target=path.join(this.folder,a.filename)
    let handle,reader,bytes=0,last=0,idleTimer
    const transfer=new AbortController(),abort=()=>transfer.abort()
    controller.signal.addEventListener('abort',abort,{once:true});if(controller.signal.aborted)abort()
    const heartbeat=()=>{clearTimeout(idleTimer);idleTimer=setTimeout(()=>transfer.abort(),30000)}
    this.update({phase:'downloading',sourceName:a.sourceName,newVersion:a.version,bytes:0,total:a.size,progress:0,message:'正在下载更新包，可继续使用星译官。'})
    try{
      const source=this.sources.find(s=>s.id===a.source);if(!source)throw Error('发布来源已变化，请重新检查更新。')
      heartbeat()
      const response=await fetchTrusted(this.fetcher,a.url,{signal:transfer.signal,networkMode,onRoute:value=>this.update({networkRoute:value.route,downloadHost:value.host,message:'正在从 '+a.sourceName+(value.route==='direct'?' 直连':'')+'下载更新包，可继续使用星译官。'})},source.trusted)
      if(!response.ok)throw Error('更新包下载失败，请稍后重试。')
      const declared=response.headers.get('content-length');if(declared&&Number(declared)!==a.size)throw Error('更新包大小与发布记录不一致。')
      handle=await io.open(temporary,'wx');reader=response.body.getReader();const hash=crypto.createHash('sha256')
      for(;;){
        if(controller.signal.aborted)throw Error('cancelled')
        const {done,value}=await reader.read();if(done)break
        bytes+=value.length;if(bytes>a.size)throw Error('更新包大小与发布记录不一致。')
        heartbeat()
        hash.update(value);let offset=0;while(offset<value.length){const written=await handle.write(value,offset,value.length-offset);if(!written.bytesWritten)throw Error('更新包无法写入磁盘。');offset+=written.bytesWritten}
        if(Date.now()-last>150){last=Date.now();this.update({bytes,progress:Math.floor(bytes/a.size*100)})}
      }
      await handle.close();handle=null
      if(controller.signal.aborted)throw Error('cancelled')
      if(bytes!==a.size||hash.digest('hex')!==a.sha256)throw Error('更新包校验未通过，已清除下载内容，请重新下载。')
      await executable(temporary);await io.unlink(target).catch(error=>{if(error.code!=='ENOENT')throw error});await io.rename(temporary,target)
      this.ready={version:a.version,filename:a.filename,size:a.size,sha256:a.sha256,source:a.source}
      await io.writeFile(path.join(this.folder,'ready.json'),JSON.stringify(this.ready))
      return this.update({phase:'ready',bytes,progress:100,message:'更新包已通过校验，可关闭并安装。'})
    }finally{clearTimeout(idleTimer);controller.signal.removeEventListener('abort',abort);await reader?.cancel().catch(()=>{});reader?.releaseLock();await handle?.close().catch(()=>{});await io.unlink(temporary).catch(()=>{})}
  }
  async cancel(){this.controller?.abort();if(this.downloadPromise)await this.downloadPromise.catch(()=>{});return this.snapshot()}
  async prepareInstall(){
    if(this.isDownloading)throw Error('请等待下载与校验完成。')
    if(!this.ready)throw Error('请先下载并校验更新包。')
    const source=this.sources.find(s=>s.id===(this.ready.source||GITHUB.id));if(!source)throw Error('发布来源已变化，请重新检查更新。')
    const remote=candidate(await this.release('v'+this.ready.version,source),this.currentVersion,source)
    if(!remote||remote.sha256!==this.ready.sha256||remote.filename!==this.ready.filename||remote.size!==this.ready.size)throw Error('更新发布记录已变化，请重新检查并下载。')
    const file=path.join(this.folder,remote.filename)
    try{if((await io.stat(file)).size!==remote.size||await digest(file)!==remote.sha256)throw Error('更新包已损坏，请重新下载。');await executable(file)}
    catch(error){this.ready=null;this.available=remote;await io.unlink(path.join(this.folder,'ready.json')).catch(()=>{});this.update({phase:'available',message:'更新包已损坏，请重新下载。'});throw error}
    return file
  }
}
module.exports={GitHubUpdates,version,newer,candidate,trusted,fetchTrusted}
