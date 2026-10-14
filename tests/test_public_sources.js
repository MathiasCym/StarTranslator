const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto')
const {GitHubUpdates,fetchTrusted}=require('../lib/github-updates'),{source,mirrors,manifest}=require('../lib/distribution-sources')
function pe(){const b=Buffer.alloc(256*1024,27);b.write('MZ');b.writeUInt32LE(128,60);b.set([80,69,0,0],128);return b}
async function fixture(t,provider='gitcode'){
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'star-mirror-test-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}))
 const bytes=pe(),s=source(provider,'synthetic/StarTranslator'),tag='v2.0.4',filename='StarTranslator-Setup-2.0.4.exe'
 const metadata={schema:1,version:'2.0.4',filename,platform:'win32',architecture:'x64',size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')}
 const r={tag_name:tag,prerelease:false,assets:[{name:filename,browser_download_url:s.web+'/releases/download/'+tag+'/'+filename},{name:'update.json',browser_download_url:s.web+'/releases/download/'+tag+'/update.json'}]}
 const calls=[];let failure=false,metadataValue=metadata,releaseValue=r
 const fetcher=async(url,opts)=>{
  calls.push({url,opts});if(failure&&url.startsWith(s.api))throw Error('offline')
  if(url.startsWith(s.api))return new Response(JSON.stringify(releaseValue))
  if(url.endsWith('/update.json'))return new Response(JSON.stringify(metadataValue))
  if(url.startsWith('https://api.github.com/'))throw Error('GitHub unavailable')
  return new Response(bytes,{headers:{'content-length':String(bytes.length)}})
 }
 const engine=new GitHubUpdates({currentVersion:'2.0.3',userData:dir,fetcher,distribution:{schema:1,mirrors:[{provider,repository:s.repository}]}})
 return {dir,engine,s,r,metadata,calls,bytes,offline:()=>failure=true,setMetadata:value=>metadataValue=value,setRelease:value=>releaseValue=value}
}
test('public mirror config accepts only known platforms and two-part repositories without credentials',()=>{
 assert.equal(mirrors({schema:1,mirrors:[]}).length,0)
 for(const item of [{provider:'unknown',repository:'a/b'},{provider:'gitcode',repository:'../x'},{provider:'gitcode',repository:'a/b',token:'never-ship'},{provider:'gitcode',repository:'https://x/y'}])assert.throws(()=>mirrors({schema:1,mirrors:[item]}))
 assert.throws(()=>mirrors({schema:1,mirrors:[{provider:'gitcode',repository:'a/b'},{provider:'gitcode',repository:'c/d'}]}))
})
for(const provider of ['atomgit','gitcode','gitee'])test(provider+' verifies check, download and pre-install without any GitHub call or credentials',async t=>{
 const f=await fixture(t,provider);assert.equal((await f.engine.check()).phase,'available');await f.engine.download()
 const file=await f.engine.prepareInstall();assert.deepEqual(await fs.readFile(file),f.bytes)
 assert(!f.calls.some(c=>c.url.includes('github.com')));assert(f.calls.every(c=>c.opts.credentials==='omit'&&!c.opts.headers?.Authorization))
 assert(f.calls.some(c=>c.url===f.s.api+'releases/tags/v2.0.4'));assert.equal(f.engine.snapshot().sourceName,f.s.name)
})
test('unreachable mirror falls back to the original GitHub release checks',async t=>{
 const f=await fixture(t);f.offline()
 // Use a standalone public GitHub response, not a mirror's claimed checksum.
 f.engine.fetcher=async(url,opts)=>{f.calls.push({url,opts});if(!url.startsWith('https://api.github.com/'))throw Error('offline');return new Response(JSON.stringify({...f.r,assets:[{name:f.metadata.filename,state:'uploaded',size:f.metadata.size,digest:'sha256:'+f.metadata.sha256,browser_download_url:'https://github.com/MathiasCym/StarTranslator/releases/download/v2.0.4/'+f.metadata.filename}]}))}
 const result=await f.engine.check();assert.equal(result.phase,'available');assert.equal(result.sourceName,'GitHub')
})
test('metadata cannot downgrade the platform, package, version or checksum contract',async t=>{
 const f=await fixture(t)
 for(const change of [{version:'2.0.5'},{platform:'linux'},{architecture:'arm64'},{filename:'other.exe'},{size:0},{sha256:'fake'}])assert.throws(()=>manifest({...f.metadata,...change},'2.0.4',f.metadata.filename))
 f.setMetadata({...f.metadata,sha256:'fake'});await assert.rejects(f.engine.check());assert.equal(f.engine.snapshot().canDownload,false)
})
test('foreign repositories, duplicate assets and forged release tags are refused',async t=>{
 const f=await fixture(t);f.setRelease({...f.r,assets:f.r.assets.map(a=>({...a,browser_download_url:a.browser_download_url.replace('/synthetic/','/someone-else/')}))});await assert.rejects(f.engine.check(),/一致/)
 f.setRelease({...f.r,assets:[...f.r.assets,f.r.assets[0]]});await assert.rejects(f.engine.check(),/完整/)
 f.setRelease(f.r);await f.engine.check();await f.engine.download();f.setRelease({...f.r,tag_name:'v2.0.5'});await assert.rejects(f.engine.prepareInstall(),/一致/)
})
test('a cached domestic installer is rechecked through its own platform after restart',async t=>{
 const f=await fixture(t);await f.engine.check();await f.engine.download()
 const restarted=new GitHubUpdates({currentVersion:'2.0.3',userData:f.dir,fetcher:f.engine.fetcher,distribution:{schema:1,mirrors:[{provider:'gitcode',repository:f.s.repository}]}})
 await restarted.prepareInstall();f.setMetadata({...f.metadata,sha256:'a'.repeat(64)});await assert.rejects(restarted.prepareInstall(),/已变化/)
})
test('domestic redirect hosts are scoped and do not broaden the default GitHub whitelist',async()=>{
 const s=source('gitcode','synthetic/StarTranslator')
 const r=await fetchTrusted(async(url)=>url.startsWith('https://gitcode.com/')?new Response(null,{status:302,headers:{location:'https://file-cdn.gitcode.com/public/install.exe'}}):new Response('bytes'),s.web+'/releases/download/v2.0.4/x.exe',{},s.trusted);assert.equal(await r.text(),'bytes')
 await assert.rejects(fetchTrusted(async()=>new Response('x'),'https://file-cdn.gitcode.com/x'),/可信/)
 for(const target of ['http://file-cdn.gitcode.com/x','https://evil.example/x','https://api.github.com/x','https://token@file-cdn.gitcode.com/x'])await assert.rejects(fetchTrusted(async()=>new Response(null,{status:302,headers:{location:target}}),s.web+'/x',{},s.trusted),/可信/)
})
test('download fallback only accepts the identical version, size and checksum from GitHub',async t=>{
 const f=await fixture(t);await f.engine.check()
 f.engine.fetcher=async(url,opts)=>{
  f.calls.push({url,opts})
  if(url.startsWith(f.s.web))return new Response(null,{status:503})
  if(url.startsWith('https://api.github.com/'))return Response.json({...f.r,assets:[{name:f.metadata.filename,state:'uploaded',size:f.metadata.size,digest:'sha256:'+f.metadata.sha256,browser_download_url:'https://github.com/MathiasCym/StarTranslator/releases/download/v2.0.4/'+f.metadata.filename}]})
  return new Response(f.bytes,{headers:{'content-length':String(f.bytes.length)}})
 }
 assert.equal((await f.engine.download()).phase,'ready');assert.equal(f.engine.snapshot().sourceName,'GitHub');await f.engine.prepareInstall()
 assert(! (await fs.readdir(path.join(f.dir,'updates'))).some(n=>n.endsWith('.part')))
})
test('a changed fallback checksum never starts downloading the unrelated installer',async t=>{
 const f=await fixture(t);await f.engine.check();let downloaded=false
 f.engine.fetcher=async(url)=>{
  if(url.startsWith(f.s.web))return new Response(null,{status:503})
  if(url.startsWith('https://api.github.com/'))return Response.json({...f.r,assets:[{name:f.metadata.filename,state:'uploaded',size:f.metadata.size,digest:'sha256:'+'a'.repeat(64),browser_download_url:'https://github.com/MathiasCym/StarTranslator/releases/download/v2.0.4/'+f.metadata.filename}]})
  downloaded=true;return new Response(f.bytes)
 }
 await assert.rejects(f.engine.download());assert.equal(downloaded,false);assert.equal(f.engine.snapshot().phase,'error')
})
test('an empty AtomGit repository returns a current-version result when discovery uses 400 and an empty list',async t=>{
 const f=await fixture(t,'atomgit')
 f.engine.fetcher=async(url)=>url.startsWith(f.s.api+'releases/latest')?new Response(null,{status:400}):url.startsWith(f.s.api+'releases?')?Response.json([]):new Response(null,{status:404})
 assert.equal((await f.engine.check()).phase,'current')
})
