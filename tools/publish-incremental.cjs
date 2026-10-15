// Domestic routine updates mirror only small, hash-verified GitHub artifacts.
// The full installer remains available on GitHub for initial install/recovery.
const {validateIndex}=require('../lib/incremental-source'),{hash}=require('../lib/incremental-update'),{GITHUB}=require('../lib/distribution-sources')
const {fetchTrusted,candidate}=require('../lib/github-updates')
async function publishIncremental(publisher,release,{readBody}){
 const a=candidate(release,'0.0.0'),tag='v'+a.version,s=publisher.source
 async function readAsset(source,asset,name,max){
   const response=await fetchTrusted(publisher.fetcher,source.assetUrl(asset.browser_download_url,tag,name),{signal:AbortSignal.timeout(120000)},source.trusted)
   if(!response.ok)throw Error('更新附件无法匿名读取。')
   return readBody(response,max)
 }
 const metadata=(release.assets||[]).filter(a=>a.name==='incremental.json');if(metadata.length!==1)throw Error('GitHub 增量发布信息不完整。')
 const indexBytes=await readAsset(GITHUB,metadata[0],'incremental.json',2*1024*1024)
 if(metadata[0].digest!=='sha256:'+hash(indexBytes))throw Error('GitHub 增量清单摘要不符。')
 const index=validateIndex(JSON.parse(indexBytes),a.version)
 const files=[]
 for(const p of index.patches){
   const assets=(release.assets||[]).filter(a=>a.name===p.filename)
   if(assets.length!==1||assets[0].digest!=='sha256:'+p.sha256||assets[0].size!==p.size)throw Error('GitHub 增量附件信息不符。')
   const bytes=await readAsset(GITHUB,assets[0],p.filename,p.size)
   if(bytes.length!==p.size||hash(bytes)!==p.sha256)throw Error('国内增量包必须与 GitHub 原附件逐字节一致。')
   files.push([p.filename,bytes])
 }
 files.unshift(['SHA256SUMS.incremental.txt',Buffer.from(index.patches.map(p=>p.sha256+'  '+p.filename+'\n').join(''))]);files.push(['incremental.json',indexBytes])
 let existing=await publisher.call('GET','releases/tags/'+tag)
 if(existing&&existing.release_status!=='pre'&&!existing.prerelease){
   for(const [name,bytes] of files){const matches=(existing.assets||[]).filter(a=>a.name===name);if(matches.length!==1||!(await readAsset(s,matches[0],name,bytes.length)).equals(bytes))throw Error('国内已有正式增量版不同，未修改。')}
   return {retained:true,version:a.version,incremental:true}
 }
 if(!existing)existing=await publisher.call('POST','releases',{tag_name:tag,name:'星译官 '+tag,body:a.notes,release_status:'pre',prerelease:true})
 for(const [name,bytes] of files){
   const matches=(existing.assets||[]).filter(a=>a.name===name)
   if(matches.length){if(matches.length!==1||!(await readAsset(s,matches[0],name,bytes.length)).equals(bytes))throw Error('国内现有附件与 GitHub 不同，未覆盖。')}
   else await publisher.upload(tag,name,bytes)
 }
 const ready=await publisher.call('GET','releases/tags/'+tag)
 for(const [name,bytes] of files){const matches=(ready?.assets||[]).filter(a=>a.name===name);if(matches.length!==1||!(await readAsset(s,matches[0],name,bytes.length)).equals(bytes))throw Error('国内增量附件匿名复核未通过，保持预发布。')}
 await publisher.call('PATCH','releases/'+tag,{name:'星译官 '+tag,body:a.notes,release_status:'latest',prerelease:false})
 const final=await publisher.call('GET','releases/tags/'+tag)
 if(!final||final.release_status==='pre'||final.prerelease)throw Error('国内正式增量版状态未确认。')
 return {published:true,incremental:true,version:a.version,bytes:files.reduce((n,[,b])=>n+b.length,0),fullInstallerUploaded:false}
}
module.exports={publishIncremental}
