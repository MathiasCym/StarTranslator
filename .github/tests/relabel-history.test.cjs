const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const {validate,section,presentation,protectedState,planProvider,applyProvider,github}=require('../scripts/relabel-history.cjs')
const config=JSON.parse(fs.readFileSync(path.join(__dirname,'../release-display-versions.json'),'utf8'))
const changelog=fs.readFileSync(path.join(__dirname,'../../CHANGELOG.md'),'utf8')
function release(version,id){return {id,tag_name:'v'+version,name:'old '+version,body:'original notes',
 target_commitish:'commit-'+version,draft:false,prerelease:false,published_at:'2026-10-16T00:00:00Z',
 assets:[{id:id+100,name:'StarTranslator-Setup-'+version+'.exe',state:'uploaded',size:300000,digest:'sha256:'+'a'.repeat(64),
 browser_download_url:'https://github.com/MathiasCym/StarTranslator/releases/download/v'+version+'/StarTranslator-Setup-'+version+'.exe'}]}}
function provider(name='GitHub'){
 const values=new Map([...config.aliases.map((a,i)=>['v'+a.original,release(a.original,i+1)]),['v2.1.7',release('2.1.7',20)]])
 const calls=[]
 return {name,values,calls,get:async tag=>structuredClone(values.get(tag)||null),
  update:async(tag,before,body)=>{assert.deepEqual(Object.keys(body).sort(),['body','name']);calls.push({tag,body});Object.assign(values.get(tag),body)}}
}
test('mapping is exact and cannot redirect maintenance to another repository or version',()=>{
 assert.equal(validate(config),config)
 assert.throws(()=>validate({...config,repository:'unrelated/repository'}))
 assert.throws(()=>validate({...config,aliases:config.aliases.slice(1)}))
 const altered=structuredClone(config);altered.aliases[0].display='3.0.0';assert.throws(()=>validate(altered))
})
test('all eight historical sections use new display numbers and the current section is unique',()=>{
 const headings=[...changelog.matchAll(/^## \[([^\]]+)\]/gm)].map(m=>m[1])
 for(const item of config.aliases){assert.equal(headings.filter(v=>v===item.display).length,1);assert(!headings.includes(item.original));assert(section(changelog,item.display).includes('1. '))}
 assert(section(changelog,'2.1.7').includes('Word'))
 assert(section(changelog,'2.1.0').includes('增量更新'))
 assert(!section(changelog,'2.1.7').startsWith('历史编号：'))
 assert.throws(()=>section(changelog,'9.9.9'))
})
test('a historical title always states both display version and original update identity',()=>{
 const desired=presentation(config.aliases[0],'1. Feature')
 assert.equal(desired.tag,'v2.0.10');assert.equal(desired.name,'星译官 v2.1.0（原 v2.0.10）')
 assert(desired.body.includes('原发行编号'));assert(desired.body.includes('内部版本'))
})
test('maintenance updates only title and body, retaining tags, publication state and all assets',async()=>{
 const p=provider(),before=new Map([...p.values].map(([k,v])=>[k,protectedState(v)]))
 const plans=await planProvider(p,config,changelog),result=await applyProvider(p,plans)
 assert.equal(result.length,9);assert.equal(p.calls.length,9)
 for(const [tag,value] of p.values)assert.deepEqual(protectedState(value),before.get(tag))
 assert.equal(p.values.get('v2.1.7').name,'星译官 v2.1.7')
})
test('a second run is idempotent and never creates or reuploads a release',async()=>{
 const p=provider();await applyProvider(p,await planProvider(p,config,changelog));p.calls.length=0
 const result=await applyProvider(p,await planProvider(p,config,changelog))
 assert.equal(p.calls.length,0);assert(result.every(x=>!x.updated&&x.assetsUnchanged))
})
test('concurrent text edits or changed artifacts are rejected before overwriting',async()=>{
 const p=provider(),plans=await planProvider(p,config,changelog)
 p.values.get('v2.0.10').body='Maintainer edited this during planning'
 await assert.rejects(()=>applyProvider(p,plans),/notes changed/);assert.equal(p.calls.length,0)
 const q=provider(),other=await planProvider(q,config,changelog)
 q.values.get('v2.0.10').assets[0].digest='sha256:'+'b'.repeat(64)
 await assert.rejects(()=>applyProvider(q,other),/changed during planning/);assert.equal(q.calls.length,0)
})
test('server-side metadata side effects are detected after patching',async()=>{
 const p=provider(),original=p.update
 p.update=async(...args)=>{await original(...args);p.values.get(args[0]).prerelease=true}
 const plans=await planProvider(p,config,changelog)
 await assert.rejects(()=>applyProvider(p,plans),/Protected release metadata changed/)
})
test('missing domestic history is skipped without inventing releases; canonical history is required',async()=>{
 const p=provider('AtomGit');p.values.delete('v2.0.10')
 const result=await applyProvider(p,await planProvider(p,config,changelog));assert.equal(result[0].skipped,'not present')
 assert(!p.values.has('v2.0.10'))
 p.values.delete('v2.1.7');await assert.rejects(()=>planProvider(p,config,changelog),/missing release/)
 const q=provider();q.values.delete('v2.0.10');await assert.rejects(()=>planProvider(q,config,changelog),/missing release/)
})
test('title changes cannot alter the updater version or its validated download asset',()=>{
 const {candidate}=require('../../lib/github-updates'),item=release('2.0.16',2)
 const before=candidate(item,'2.0.15');Object.assign(item,presentation(config.aliases[6],'Updated description'))
 const after=candidate(item,'2.0.15')
 assert.equal(after.version,'2.0.16');assert.equal(after.sha256,before.sha256);assert.equal(after.url,before.url)
 assert.equal(after.size,before.size);assert.equal(after.filename,before.filename)
})
test('GitHub credentials only go to fixed owned endpoints without following redirects',async()=>{
 const requests=[],client=github('fixture-token',async(url,options)=>{
  requests.push({url,options});return new Response(JSON.stringify(release('2.0.10',1)),{status:200})
 })
 await client.get('v2.0.10');await client.update('v2.0.10',{id:1},{name:'new',body:'notes'})
 assert.equal(requests[0].url,'https://api.github.com/repos/MathiasCym/StarTranslator/releases/tags/v2.0.10')
 assert.equal(requests[1].options.method,'PATCH')
 assert(requests.every(r=>r.options.redirect==='error'&&!r.url.includes('fixture-token')))
 assert.deepEqual(JSON.parse(requests[1].options.body),{name:'new',body:'notes'})
})
