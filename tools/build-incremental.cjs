// Build small, version-specific updates from immutable GitHub installer bytes.
const fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process')
const {GitHubUpdates,candidate,newer,fetchTrusted}=require('../lib/github-updates'),{GITHUB}=require('../lib/distribution-sources')
const {buildPatch,filename,hash}=require('../lib/incremental-update')
const root=path.resolve(__dirname,'..')
async function build(){
 const current=JSON.parse(await fs.readFile(path.join(root,'package.json'),'utf8')).version,folder=path.join(root,'dist/qa/incremental'),out=path.join(root,'dist/incremental')
 await fs.mkdir(folder,{recursive:true});await fs.mkdir(out,{recursive:true})
 const response=await fetchTrusted(fetch,GITHUB.api+'releases?per_page=100',{signal:AbortSignal.timeout(30000)},GITHUB.trusted)
 if(!response.ok)throw Error('Cannot inspect immutable patch baselines')
 const releases=(await response.json()).filter(r=>!r.draft&&!r.prerelease&&/^v\d+\.\d+\.\d+$/.test(r.tag_name)&&newer(current,r.tag_name)).sort((a,b)=>newer(a.tag_name,b.tag_name)?-1:1).slice(0,3)
 const patches=[]
 const target=JSON.parse(await fs.readFile(path.join(folder,'target.json'),'utf8')).folder
 for(const release of releases){
   const a=candidate(release,'0.0.0'),download=path.join(folder,a.filename)
   const bytes=Buffer.from(await(await fetchTrusted(fetch,a.url,{signal:AbortSignal.timeout(180000)},GITHUB.trusted)).arrayBuffer())
   if(bytes.length!==a.size||hash(bytes)!==a.sha256)throw Error('Baseline installer hash mismatch')
   await fs.writeFile(download,bytes)
   const base=await fs.mkdtemp(path.join(folder,'base-'))
   execFileSync(process.env.ProgramFiles+'\\7-Zip\\7z.exe',['x',download,'-y','-o'+base,'-xr!$PLUGINSDIR'],{windowsHide:true,stdio:'ignore'})
   const metadata=await buildPatch(base,target,path.join(out,filename(a.version,current)))
   if(metadata.size>=a.size*.8){
     console.log(JSON.stringify({from:a.version,to:current,fullUpdateRequired:true,reason:'Runtime changes exceed the small-update threshold'}))
     if(path.dirname(base)!==folder)throw Error('Unsafe QA cleanup path')
     await fs.rm(base,{recursive:true,force:true});await fs.unlink(download);await fs.unlink(path.join(out,metadata.filename));continue
   }
   // Exercise the real Windows file replacement and exact target integrity in
   // a disposable extracted installation. No installed program is modified.
   await require('./verify-incremental.cjs').verify({file:path.join(out,metadata.filename),base,target,output:path.join(folder,'verified-'+a.version+'.json')})
   patches.push(metadata);console.log(JSON.stringify({from:a.version,to:current,bytes:metadata.size,fullBytes:a.size}))
   if(path.dirname(base)!==folder)throw Error('Unsafe QA cleanup path')
   await fs.rm(base,{recursive:true,force:true});await fs.unlink(download)
 }
 const index={schema:1,version:current,platform:'win32',architecture:'x64',patches}
 await fs.writeFile(path.join(out,'incremental.json'),JSON.stringify(index,null,2)+'\n')
 await fs.writeFile(path.join(out,'SHA256SUMS.incremental.txt'),patches.map(p=>p.sha256+'  '+p.filename+'\n').join(''))
 return index
}
if(require.main===module)build().catch(error=>{console.error(error.message);process.exitCode=1})
module.exports={build}
