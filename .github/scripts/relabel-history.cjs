// Maintainer-only release text maintenance. Never rename tags or artifacts.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict')
const {GitCodePublisher,readBody}=require('../../tools/publish-gitcode.cjs')
const {mirrors}=require('../../lib/distribution-sources')
const REPOSITORY='MathiasCym/StarTranslator'
const normal=value=>String(value||'').replace(/\r\n/g,'\n').trim()

function validate(config){
 assert.equal(config.schema,1);assert.equal(config.repository,REPOSITORY)
 assert.equal(config.canonical,'2.1.7');assert.equal(config.aliases.length,8)
 config.aliases.forEach((item,i)=>assert.deepEqual(item,{original:'2.0.'+(10+i),display:'2.1.'+i}))
 return config
}
function section(changelog,version){
 const escaped=version.replaceAll('.','\\.')
 const match=changelog.match(new RegExp('^## \\['+escaped+'\\] - [^\\n]+\\n([\\s\\S]*?)(?=^## |$(?![\\s\\S]))','m'))
 if(!match)throw Error('Missing historical notes: '+version)
 return normal(match[1]).replace(/^历史编号：[^\n]*\n*/, '')
}
function presentation(item,notes,canonical=false){
 const tag='v'+item.original
 return {tag,name:canonical?'星译官 v'+item.display:'星译官 v'+item.display+'（原 v'+item.original+'）',
  body:canonical?notes:
   `历史展示版本：**${item.display}**；原发行编号：\`${item.original}\`。\n\n`+
   '为兼容已安装程序，原 Git 标签、安装包内部版本、附件名称及更新校验保持不变。下方是本版原有更新内容。\n\n'+notes}
}
function protectedState(release){
 const keys=['id','tag_name','target_commitish','draft','prerelease','release_status','published_at']
 const state=Object.fromEntries(keys.filter(k=>release[k]!==undefined).map(k=>[k,release[k]]))
 state.assets=(release.assets||[]).map(a=>Object.fromEntries(
  ['id','name','size','digest','browser_download_url'].filter(k=>a[k]!==undefined).map(k=>[k,a[k]])))
  .sort((a,b)=>a.name.localeCompare(b.name))
 return state
}
async function planProvider(provider,config,changelog){
 const items=[...config.aliases.map(item=>({...item,canonical:false})),
  {original:config.canonical,display:config.canonical,canonical:true}]
 const plans=[]
 for(const item of items){
  const desired=presentation(item,section(changelog,item.display),item.canonical)
  const before=await provider.get(desired.tag)
  if(!before){
   if(item.canonical||provider.name==='GitHub')throw Error(provider.name+' missing release '+desired.tag)
   plans.push({desired,missing:true});continue
  }
  assert.equal(before.tag_name,desired.tag,'Release lookup returned another tag')
  plans.push({desired,before,protected:protectedState(before)})
 }
 return plans
}
async function applyProvider(provider,plans){
 const summary=[]
 for(const plan of plans){
  if(plan.missing){summary.push({tag:plan.desired.tag,skipped:'not present'});continue}
  const {desired,before}=plan
  const fresh=await provider.get(desired.tag)
  assert.deepEqual(protectedState(fresh),plan.protected,'Release changed during planning')
  assert.equal(normal(fresh.body),normal(before.body),'Release notes changed during planning')
  assert.equal(fresh.name,before.name,'Release title changed during planning')
  const changed=fresh.name!==desired.name||normal(fresh.body)!==normal(desired.body)
  if(changed)await provider.update(desired.tag,fresh,{name:desired.name,body:desired.body})
  const after=await provider.get(desired.tag)
  assert.deepEqual(protectedState(after),plan.protected,'Protected release metadata changed')
  assert.equal(after.name,desired.name);assert.equal(normal(after.body),normal(desired.body))
  summary.push({tag:desired.tag,name:desired.name,updated:changed,assetsUnchanged:true})
 }
 return summary
}
function github(token,fetcher=globalThis.fetch){
 if(!token)throw Error('GITHUB_TOKEN is required in the maintainer workflow')
 const base='https://api.github.com/repos/'+REPOSITORY
 async function call(method,endpoint,body){
  const response=await fetcher(base+endpoint,{method,redirect:'error',signal:AbortSignal.timeout(30000),
   headers:{Accept:'application/vnd.github+json',Authorization:'Bearer '+token,
    'X-GitHub-Api-Version':'2022-11-28',...(body?{'Content-Type':'application/json'}:{})},
   body:body?JSON.stringify(body):undefined})
  if(response.status===404)return null
  if(!response.ok)throw Error('GitHub release text request failed (HTTP '+response.status+')')
  return JSON.parse((await readBody(response)).toString('utf8'))
 }
 return {name:'GitHub',get:tag=>call('GET','/releases/tags/'+encodeURIComponent(tag)),
  update:(_tag,release,body)=>call('PATCH','/releases/'+release.id,body)}
}
async function run(root=path.resolve(__dirname,'../..')){
 if(process.env.GITHUB_REPOSITORY!==REPOSITORY)throw Error('Run only in the owned repository')
 const config=validate(JSON.parse(await fs.readFile(path.join(root,'.github/release-display-versions.json'),'utf8')))
 const changelog=await fs.readFile(path.join(root,'CHANGELOG.md'),'utf8')
 const source=mirrors(JSON.parse(await fs.readFile(path.join(root,'backend/distribution.json'),'utf8')))
  .find(s=>s.provider==='atomgit'&&s.repository===REPOSITORY)
 if(!source)throw Error('Owned domestic source missing')
 const publisher=new GitCodePublisher({source,token:process.env.GITCODE_TOKEN})
 const domestic={name:'AtomGit',get:tag=>publisher.call('GET','releases/tags/'+encodeURIComponent(tag)),
  update:(tag,release,body)=>publisher.call('PATCH','releases/'+encodeURIComponent(tag),{
   ...body,...(release.release_status!==undefined?{release_status:release.release_status}:{})})}
 const providers=[github(process.env.GITHUB_TOKEN),domestic]
 const planned=[]
 // Read and validate both providers before changing either one's text.
 for(const provider of providers)planned.push({provider,plans:await planProvider(provider,config,changelog)})
 const folder=path.join(root,'dist/qa/relabel-history');await fs.mkdir(folder,{recursive:true})
 await fs.writeFile(path.join(folder,'before.json'),JSON.stringify(planned.map(x=>({provider:x.provider.name,plans:x.plans})),null,2))
 const result=[]
 for(const {provider,plans} of planned){
  const releases=await applyProvider(provider,plans)
  result.push({provider:provider.name,releases});console.log(JSON.stringify(result.at(-1)))
 }
 await fs.writeFile(path.join(folder,'result.json'),JSON.stringify({passed:true,result},null,2))
 return {passed:true,providers:result.map(x=>x.provider),installerChanged:false,tagsChanged:false}
}
if(require.main===module)run().then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e.message);process.exitCode=1})
module.exports={validate,section,presentation,protectedState,planProvider,applyProvider,github}
