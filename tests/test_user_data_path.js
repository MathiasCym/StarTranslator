const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os')
const {migrate,configure,resolveExisting}=require('../lib/user-data-path')
function fixture(t){const base=fs.mkdtempSync(path.join(os.tmpdir(),'StarTranslator-data-'));t.after(()=>fs.rmSync(base,{recursive:true,force:true}));return {base,old:path.join(base,'novaterm-checker'),current:path.join(base,'StarTranslator')}}
test('fresh install uses branded directory without creating a legacy folder',t=>{const f=fixture(t);assert.equal(migrate(f.base).path,f.current);assert(!fs.existsSync(f.old))})
test('migration preserves exact data, encrypted bytes, timestamps and old absolute references; repeated launches are idempotent',t=>{
 const f=fixture(t);fs.mkdirSync(f.old);const samples={'lexicon.json':'[{"zh":"自定义","en":"Personal"}]','model-profiles.json':'dpapi:opaque-encrypted-bytes','history.json':JSON.stringify({path:path.join(f.old,'comparisons/saved.json')})}
 fs.mkdirSync(path.join(f.old,'comparisons'));fs.writeFileSync(path.join(f.old,'comparisons/saved.json'),'saved comparison')
 for(const [name,data]of Object.entries(samples))fs.writeFileSync(path.join(f.old,name),data)
 const before=fs.statSync(path.join(f.old,'model-profiles.json')).mtimeMs
 assert.equal(resolveExisting(f.base),f.old);assert.equal(migrate(f.base).migrated,true)
 for(const [name,data]of Object.entries(samples))assert.equal(fs.readFileSync(path.join(f.current,name),'utf8'),data)
 assert.equal(fs.statSync(path.join(f.current,'model-profiles.json')).mtimeMs,before)
 assert.equal(fs.readFileSync(JSON.parse(fs.readFileSync(path.join(f.current,'history.json'))).path,'utf8'),'saved comparison')
 assert(fs.lstatSync(f.old).isSymbolicLink());assert.equal(migrate(f.base).migrated,false);assert.equal(resolveExisting(f.base),f.current)
})
test('locked legacy directory keeps using legacy profile and reports deferred migration',t=>{const f=fixture(t);fs.mkdirSync(f.old);fs.writeFileSync(path.join(f.old,'personal'),'original');const r=migrate(f.base,{...fs,renameSync(){throw Object.assign(Error('in use'),{code:'EBUSY'})}});assert.equal(r.path,f.old);assert(r.warning);assert.equal(fs.readFileSync(path.join(f.old,'personal'),'utf8'),'original');assert(!fs.existsSync(f.current))})
test('junction failure rolls back directory rename before continuing',t=>{const f=fixture(t);fs.mkdirSync(f.old);fs.writeFileSync(path.join(f.old,'personal'),'original');const r=migrate(f.base,{...fs,symlinkSync(){throw Error('denied')}});assert.equal(r.path,f.old);assert(r.warning);assert(!fs.existsSync(f.current));assert.equal(fs.readFileSync(path.join(f.old,'personal'),'utf8'),'original')})
test('two independent profiles are preserved and never silently merged',t=>{const f=fixture(t);for(const p of[f.old,f.current])fs.mkdirSync(p);fs.writeFileSync(path.join(f.old,'personal'),'old');fs.writeFileSync(path.join(f.current,'personal'),'new');const r=migrate(f.base);assert.equal(r.path,f.old);assert(r.warning);assert.equal(fs.readFileSync(path.join(f.current,'personal'),'utf8'),'new')})
test('explicit isolated data paths and special modes never migrate unrelated profiles',t=>{const f=fixture(t);fs.mkdirSync(f.old);const set=[];const app={getPath:n=>n==='appData'?f.base:path.join(f.base,'qa-profile'),setPath:(...args)=>set.push(args)};assert.equal(configure(app).path,path.join(f.base,'qa-profile'));assert.deepEqual(set,[]);app.getPath=n=>n==='appData'?f.base:f.current;assert.equal(configure(app,{move:false}).path,f.old);assert(!fs.existsSync(f.current))})
