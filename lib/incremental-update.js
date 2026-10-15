// Version-bound binary deltas. No Git, external patch program or model access.
let fs;try{fs=require('original-fs')}catch{fs=require('node:fs')}
const io=fs.promises,path=require('node:path'),crypto=require('node:crypto'),zlib=require('node:zlib'),{promisify}=require('node:util')
const {MANIFEST,digest,targetPath,validateManifest,verifyInstallation}=require('./install-integrity')
const gzip=promisify(zlib.gzip),gunzip=promisify(zlib.gunzip),MAGIC=Buffer.from('STARDEL1'),MAX_HEADER=8*1024*1024,MAX_FILE=512*1024*1024
const hash=b=>crypto.createHash('sha256').update(b).digest('hex')
const UNINSTALLER='Uninstall 星译官.exe'
const validVersion=v=>/^\d+\.\d+\.\d+$/.test(v||'')
const filename=(from,to)=>`StarTranslator-Patch-${from}-to-${to}.stpatch`
function owned(p){return p==='星译官.exe'||/^(resources|locales)\//.test(p)||/^[A-Za-z0-9_.-]+\.(dll|pak|bin|dat|json|txt|html)$/.test(p)}
function entries(manifest){return new Map(manifest.files.map(e=>[e.path,e]))}
function same(a,b){return !!a&&!!b&&a.size===b.size&&a.sha256===b.sha256}
// Gear boundaries recover after insertions, unlike fixed-offset blocks. SHA-256
// identifies reusable bytes; the rolling value only chooses cut positions.
const gear=Array.from({length:256},(_,i)=>crypto.createHash('sha256').update('StarTranslator/chunk/'+i).digest().readUInt32LE(0))
function chunks(bytes){const out=[];let start=0,rolling=0;for(let i=0;i<bytes.length;i++){rolling=((rolling<<1)+gear[bytes[i]])>>>0;if(i-start>=8191&&((rolling&32767)===0||i-start>=131071)){out.push([start,i+1-start]);start=i+1;rolling=0}}if(start<bytes.length)out.push([start,bytes.length-start]);return out}
async function manifestAt(root){const bytes=await io.readFile(targetPath(root,MANIFEST)),value=JSON.parse(bytes);validateManifest(root,value,value.version);return {bytes,value}}
async function buildPatch(baseRoot,targetRoot,destination){
  const base=await manifestAt(baseRoot),target=await manifestAt(targetRoot)
  if(!validVersion(base.value.version)||!validVersion(target.value.version)||base.value.version===target.value.version)throw Error('更新包版本无效。')
  for(const [root,m] of [[baseRoot,base],[targetRoot,target]])if(!(await verifyInstallation(root,m.value,m.value.version)).complete)throw Error('构建增量包前安装文件校验失败。')
  const aux=[]
  for(const [root,m] of [[baseRoot,base],[targetRoot,target]]){const file=path.join(root,UNINSTALLER);try{aux.push({path:UNINSTALLER,size:(await io.stat(file)).size,sha256:await digest(file)})}catch(error){if(error.code!=='ENOENT')throw error;aux.push(null)}}
  if(!!aux[0]!==!!aux[1])throw Error('增量更新需要匹配的完整卸载程序。')
  const before=entries({files:[...base.value.files,...(aux[0]?[aux[0]]:[])]}),after=entries({files:[...target.value.files,...(aux[1]?[aux[1]]:[])]}),changed=[],payload=[];let offset=0
  // Include the exact install manifest from the full installer, never fabricate
  // a second variant of an already released version.
  const targets=[...target.value.files,...(aux[1]?[aux[1]]:[]),{path:MANIFEST,size:target.bytes.length,sha256:hash(target.bytes)}]
  for(const entry of targets){
    if(!owned(entry.path)&&entry.path!==UNINSTALLER)throw Error('增量包包含不支持的程序路径。')
    if(same(before.get(entry.path),entry))continue
    const original=before.has(entry.path)?await io.readFile(targetPath(baseRoot,entry.path)):entry.path===MANIFEST?base.bytes:Buffer.alloc(0)
    const current=await io.readFile(targetPath(targetRoot,entry.path)),index=new Map()
    for(const [start,length] of chunks(original))index.set(hash(original.subarray(start,start+length)),[start,length])
    const operations=[],literals=[]
    for(const [start,length] of chunks(current)){
      const bytes=current.subarray(start,start+length),copy=index.get(hash(bytes))
      if(copy)operations.push({copy:copy[0],length})
      else{operations.push({length});literals.push(bytes)}
    }
    const packed=await gzip(Buffer.concat(literals),{level:6});payload.push(packed)
    changed.push({...entry,operations,offset,length:packed.length});offset+=packed.length
  }
  const header={schema:1,from:base.value.version,to:target.value.version,baseManifest:hash(base.bytes),targetManifest:hash(target.bytes),base:base.value,target:target.value,aux,changed,removed:base.value.files.filter(e=>!after.has(e.path)).map(e=>e.path),payloadSize:offset}
  const json=Buffer.from(JSON.stringify(header)),size=Buffer.alloc(4);if(json.length>MAX_HEADER)throw Error('增量清单过大。');size.writeUInt32LE(json.length)
  await io.mkdir(path.dirname(destination),{recursive:true});await io.writeFile(destination,Buffer.concat([MAGIC,size,json,...payload]))
  return {from:header.from,version:header.to,filename:path.basename(destination),size:(await io.stat(destination)).size,sha256:await digest(destination),baseManifest:header.baseManifest}
}
function validateHeader(h,root,payloadSize){
  if(h?.schema!==1||!validVersion(h.from)||!validVersion(h.to)||h.from===h.to||!Array.isArray(h.changed)||!Array.isArray(h.removed)||!h.changed.length||h.changed.length>10000||h.payloadSize!==payloadSize||!Number.isSafeInteger(payloadSize)||payloadSize<0||payloadSize>MAX_FILE)throw Error('增量更新清单无效。')
  validateManifest(root,h.base,h.from);validateManifest(root,h.target,h.to)
  if(!/^[a-f0-9]{64}$/.test(h.baseManifest)||!/^[a-f0-9]{64}$/.test(h.targetManifest))throw Error('增量更新清单摘要无效。')
  if(!Array.isArray(h.aux)||h.aux.length!==2||!!h.aux[0]!==!!h.aux[1]||h.aux.some(e=>e&&(e.path!==UNINSTALLER||!Number.isSafeInteger(e.size)||e.size<1||e.size>MAX_FILE||!/^[a-f0-9]{64}$/.test(e.sha256))))throw Error('卸载组件清单无效。')
  const before=entries({files:[...h.base.files,...(h.aux[0]?[h.aux[0]]:[])]}),after=entries({files:[...h.target.files,...(h.aux[1]?[h.aux[1]]:[])]}),seen=new Set();let offset=0,total=0
  for(const e of h.changed){
    targetPath(root,e.path)
    const expected=after.get(e.path)
    if(!owned(e.path)&&e.path!==UNINSTALLER||seen.has(e.path.toLowerCase())||e.path!==MANIFEST&&!same(e,expected)||e.path===MANIFEST&&e.sha256!==h.targetManifest||!Number.isSafeInteger(e.size)||e.size<0||e.size>MAX_FILE||!Array.isArray(e.operations)||e.operations.length>100000||e.offset!==offset||!Number.isSafeInteger(e.length)||e.length<1||offset+e.length>payloadSize)throw Error('增量更新文件清单无效。')
    let written=0
    for(const op of e.operations){if(!Number.isSafeInteger(op.length)||op.length<1||op.copy!==undefined&&(!Number.isSafeInteger(op.copy)||op.copy<0||op.copy+op.length>(e.path===MANIFEST?MAX_HEADER:before.get(e.path)?.size??0)))throw Error('增量更新引用无效。');written+=op.length}
    if(written!==e.size)throw Error('增量更新文件长度不符。')
    seen.add(e.path.toLowerCase());offset+=e.length;total+=e.size
  }
  if(total>2*1024*1024*1024||offset!==payloadSize||!seen.has(MANIFEST))throw Error('增量更新数据长度不符。')
  const required=[...after.values()].filter(e=>!same(e,before.get(e.path))).map(e=>e.path)
  if(required.some(p=>!seen.has(p.toLowerCase())))throw Error('增量更新缺少变更文件。')
  const removed=h.base.files.filter(e=>!after.has(e.path)).map(e=>e.path)
  if(JSON.stringify([...removed].sort())!==JSON.stringify([...h.removed].sort())||removed.some(p=>!owned(p)))throw Error('增量更新移除清单无效。')
  return h
}
async function inspectPatch(file){
  const size=(await io.stat(file)).size;if(size<13||size>MAX_FILE)throw Error('增量更新包大小无效。')
  const handle=await io.open(file,'r');try{const prefix=Buffer.alloc(12);await handle.read(prefix,0,12,0);const count=prefix.readUInt32LE(8);if(!prefix.subarray(0,8).equals(MAGIC)||count<2||count>MAX_HEADER||count+12>size)throw Error('增量更新包结构无效。');const bytes=Buffer.alloc(count);await handle.read(bytes,0,count,12);return {header:validateHeader(JSON.parse(bytes),path.parse(path.resolve(file)).root,size-12-count),start:12+count}}finally{await handle.close()}
}
async function stagePatch({file,root,currentVersion,folder}){
  const {header:h,start}=await inspectPatch(file),base=await manifestAt(root)
  if(h.from!==currentVersion||base.value.version!==currentVersion||hash(base.bytes)!==h.baseManifest||JSON.stringify(base.value)!==JSON.stringify(h.base))throw Error('当前安装不适合此增量包，请使用完整安装包。')
  if(!(await verifyInstallation(root,base.value,currentVersion,undefined,{runtime:true})).complete)throw Error('当前程序文件不完整，请先修复或使用完整安装包。')
  const oldFiles=entries({files:[...base.value.files,...(h.aux[0]?[h.aux[0]]:[])]})
  if(h.aux[0]&&await digest(path.join(root,UNINSTALLER))!==h.aux[0].sha256)throw Error('卸载组件不匹配，请使用完整安装包。')
  await io.mkdir(folder,{recursive:false});const input=await io.open(file,'r');let complete=false
  try{
    for(const [i,e] of h.changed.entries()){
      if(e.path!==MANIFEST&&!oldFiles.has(e.path)&&await io.lstat(targetPath(root,e.path)).then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error}))throw Error('新增程序文件与现有文件冲突，请使用完整安装包。')
      const original=e.path===MANIFEST?base.bytes:oldFiles.has(e.path)?await io.readFile(targetPath(root,e.path)):Buffer.alloc(0)
      const packed=Buffer.alloc(e.length);await input.read(packed,0,e.length,start+e.offset)
      const expected=e.operations.filter(op=>op.copy===undefined).reduce((n,op)=>n+op.length,0)
      const literal=await gunzip(packed,{maxOutputLength:Math.max(1,expected)})
      if(literal.length!==expected)throw Error('增量更新解压数据不符。')
      const handle=await io.open(path.join(folder,String(i)),'wx');let cursor=0
      try{for(const op of e.operations){const bytes=op.copy!==undefined?original.subarray(op.copy,op.copy+op.length):literal.subarray(cursor,cursor+=op.length);if(bytes.length!==op.length)throw Error('增量引用超出文件。');await handle.writeFile(bytes)}await handle.sync()}finally{await handle.close()}
      const staged=path.join(folder,String(i));if((await io.stat(staged)).size!==e.size||await digest(staged)!==e.sha256)throw Error('增量合成校验失败，未修改原程序。')
    }
    const manifest=h.changed.findIndex(e=>e.path===MANIFEST),target=JSON.parse(await io.readFile(path.join(folder,String(manifest)),'utf8'))
    if(JSON.stringify(target)!==JSON.stringify(h.target))throw Error('增量安装清单与完整安装包不一致。')
    complete=true;return {schema:1,root:path.resolve(root),folder:path.resolve(folder),from:h.from,to:h.to,base:{...h.base,files:[...oldFiles.values()]},target:{...h.target,files:[...h.target.files,...(h.aux[1]?[h.aux[1]]:[])]},changed:h.changed.map((e,i)=>({path:e.path,size:e.size,sha256:e.sha256,stage:String(i)})),removed:h.removed,baseManifest:h.baseManifest}
  }finally{await input.close();if(!complete){for(const name of await io.readdir(folder))if(/^\d+$/.test(name))await io.unlink(path.join(folder,name)).catch(()=>{});await io.rmdir(folder).catch(()=>{})}}
}
module.exports={filename,buildPatch,inspectPatch,stagePatch,validateHeader,chunks,hash,owned}
