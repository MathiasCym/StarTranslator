const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto')
const {createManifest,MANIFEST}=require('../lib/install-integrity'),{buildPatch,filename,hash}=require('../lib/incremental-update'),{validateIndex}=require('../lib/incremental-source')
const {GitHubUpdates}=require('../lib/github-updates'),{GITHUB,source}=require('../lib/distribution-sources')
async function fixture(t){
 const folder=await fs.mkdtemp(path.join(__dirname,'.incremental-source-'));t.after(()=>fs.rm(folder,{recursive:true,force:true}));const base=path.join(folder,'base'),target=path.join(folder,'target')
 const files=['星译官.exe','resources/app.asar','resources/officecli/officecli.exe','resources/python-runtime/python.exe','resources/python-runtime/python311.dll','resources/app.asar.unpacked/backend/server.py']
 for(const [root,v] of [[base,'2.0.10'],[target,'2.0.11']]){for(const name of files){await fs.mkdir(path.dirname(path.join(root,name)),{recursive:true});await fs.writeFile(path.join(root,name),name==='resources/app.asar'?v:'unchanged')}await fs.writeFile(path.join(root,MANIFEST),JSON.stringify(await createManifest(root,v)))}
 const patch=path.join(folder,filename('2.0.10','2.0.11')),p=await buildPatch(base,target,patch),bytes=await fs.readFile(patch),index={schema:1,version:'2.0.11',platform:'win32',architecture:'x64',patches:[p]},meta=Buffer.from(JSON.stringify(index)),s=source('atomgit','MathiasCym/StarTranslator'),tag='v2.0.11'
 const full=Buffer.alloc(256*1024,12);full.write('MZ');full.writeUInt32LE(128,60);full.set([80,69,0,0],128)
 const fullName='StarTranslator-Setup-2.0.11.exe'
 function release(src,includeFull=false){return {tag_name:tag,body:'small update',prerelease:false,release_status:'latest',assets:[{name:p.filename,size:p.size,state:'uploaded',digest:'sha256:'+p.sha256,browser_download_url:src.web+'/releases/download/'+tag+'/'+p.filename},{name:'incremental.json',size:meta.length,state:'uploaded',digest:'sha256:'+hash(meta),browser_download_url:src.web+'/releases/download/'+tag+'/incremental.json'},...(includeFull?[{name:fullName,size:full.length,state:'uploaded',digest:'sha256:'+hash(full),browser_download_url:GITHUB.web+'/releases/download/'+tag+'/'+fullName}]:[])]}}
 const calls=[],domestic=release(s),github=release(GITHUB,true)
 const fetcher=async(url,options={})=>{calls.push({url,options});if(url.startsWith(s.api))return Response.json(domestic);if(url.startsWith(GITHUB.api))return Response.json(github);if(url.endsWith('/incremental.json'))return new Response(meta);if(url.endsWith('.stpatch'))return new Response(bytes,{headers:{'content-length':String(bytes.length)}});if(url.endsWith('.exe'))return new Response(full,{headers:{'content-length':String(full.length)}});throw Error('unexpected request')}
 const args={currentVersion:'2.0.10',installRoot:base,userData:folder,fetcher,distribution:{schema:1,mirrors:[{provider:'atomgit',repository:s.repository}]}}
 return {folder,base,target,args,p,bytes,index,meta,s,calls,domestic,github,full,release}
}
test('new clients discover, download, recheck and reuse small domestic patches without contacting GitHub',async t=>{
 const f=await fixture(t),engine=new GitHubUpdates(f.args);assert.equal((await engine.check()).kind,'patch');await engine.download();const file=await engine.prepareInstall();assert((await fs.readFile(file)).equals(f.bytes));assert(!f.calls.some(c=>c.url.includes('github.com')))
 const restarted=new GitHubUpdates(f.args);assert.equal(restarted.snapshot().phase,'ready');assert.equal(await restarted.prepareInstall(),file)
})
test('legacy clients and incompatible baselines retain the original complete-installer path',async t=>{
 const f=await fixture(t)
 for(const args of [{...f.args,installRoot:undefined},{...f.args,currentVersion:'2.0.9'}]){const engine=new GitHubUpdates(args);await engine.check();assert.equal(engine.snapshot().kind,'full');await engine.download();assert((await engine.prepareInstall()).endsWith('.exe'))}
})
test('a malformed or withdrawn patch never installs and full fallback remains available',async t=>{
 const f=await fixture(t),engine=new GitHubUpdates(f.args);await engine.check();await engine.download();f.domestic.assets=f.domestic.assets.filter(a=>a.name!==f.p.filename);await assert.rejects(engine.prepareInstall());await engine.useFullInstaller();assert.equal(engine.snapshot().kind,'full')
 for(const change of [x=>x.patches.push(x.patches[0]),x=>x.patches[0].filename='../escape',x=>x.architecture='arm64',x=>x.patches[0].baseManifest='invalid']){const index=structuredClone(f.index);change(index);assert.throws(()=>validateIndex(index,'2.0.11'))}
})
test('domestic publication uploads only exact small original artifacts and verifies them before promotion',async t=>{
 const f=await fixture(t),{GitCodePublisher,readBody}=require('../tools/publish-gitcode.cjs'),{publishIncremental}=require('../tools/publish-incremental.cjs'),files=new Map();let domestic=null,promoted=false
 const fetcher=async(url,opts={})=>{
   if(url.startsWith(f.s.api)){
     if(opts.method==='POST'){domestic={tag_name:'v2.0.11',release_status:'pre',prerelease:true,assets:[]};return Response.json(domestic)}
     if(opts.method==='PATCH'){promoted=true;assert(files.has('incremental.json'));domestic.release_status='latest';domestic.prerelease=false;return Response.json(domestic)}
     if(url.includes('upload_url?'))return Response.json({url:'https://file.gitcode.com/'+new URL(url).searchParams.get('file_name'),headers:{'Content-Type':'application/octet-stream'}})
     return domestic?Response.json(domestic):new Response(null,{status:404})
   }
   if(url.startsWith('https://file.gitcode.com/')){const name=new URL(url).pathname.slice(1);assert(!name.endsWith('.exe'));const bytes=Buffer.from(opts.body);files.set(name,bytes);domestic.assets.push({name,browser_download_url:f.s.web+'/releases/download/v2.0.11/'+name});return new Response(null,{status:204})}
   if(url.startsWith(f.s.web)){const name=new URL(url).pathname.split('/').at(-1);return files.has(name)?new Response(files.get(name)):new Response(null,{status:404})}
   assert(!url.endsWith('.exe'));return f.args.fetcher(url,opts)
 }
 const publisher=new GitCodePublisher({source:f.s,token:'synthetic-private-token',fetcher}),result=await publishIncremental(publisher,f.github,{readBody})
 assert.equal(result.fullInstallerUploaded,false);assert(promoted);assert.equal(files.size,3);assert(files.get(f.p.filename).equals(f.bytes));assert.equal((await publishIncremental(publisher,f.github,{readBody})).retained,true)
})
