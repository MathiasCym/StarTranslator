const {filename}=require('./incremental-update')
function validateIndex(value,version){
 if(value?.schema!==1||value.version!==version||value.platform!=='win32'||value.architecture!=='x64'||!Array.isArray(value.patches)||value.patches.length>5)throw Error('增量更新发布信息无效。')
 const seen=new Set()
 for(const p of value.patches){if(!/^\d+\.\d+\.\d+$/.test(p.from||'')||p.version!==version||p.from===version||p.filename!==filename(p.from,version)||!Number.isSafeInteger(p.size)||p.size<13||p.size>512*1024*1024||!/^[a-f0-9]{64}$/.test(p.sha256||'')||!/^[a-f0-9]{64}$/.test(p.baseManifest||'')||seen.has(p.from))throw Error('增量更新发布信息无效。');seen.add(p.from)}
 return value
}
function patchCandidate(release,current,source,index,baseManifest){
 if(!release||release.draft||release.prerelease||release.release_status==='pre')return null
 const v=String(release.tag_name).replace(/^v/,'');validateIndex(index,v)
 const item=index.patches.find(p=>p.from===current&&p.baseManifest===baseManifest)
 if(!item)return null
 const assets=(release.assets||[]).filter(a=>a.name===item.filename)
 if(assets.length!==1||assets[0].size!==undefined&&assets[0].size!==item.size||assets[0].digest&&assets[0].digest!=='sha256:'+item.sha256)throw Error('增量更新附件与发布记录不一致。')
 return {...item,kind:'patch',url:source.assetUrl(assets[0].browser_download_url,release.tag_name,item.filename),notes:String(release.body||'').slice(0,20000),releaseUrl:source.web+'/releases/'+(source.provider==='github'?'tag/':'')+release.tag_name,source:source.id,sourceName:source.name}
}
module.exports={validateIndex,patchCandidate}
