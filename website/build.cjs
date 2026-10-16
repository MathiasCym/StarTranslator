const fs=require('node:fs'),path=require('node:path')
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'dist')
const history=JSON.parse(fs.readFileSync(path.join(root,'release-history.json')))
const requestedVersion=process.argv.indexOf('--version')
const currentVersion=requestedVersion<0?JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version:process.argv[requestedVersion+1]
if(!/^\d+\.\d+\.\d+$/.test(currentVersion||''))throw new Error('请指定已正式发布的版本：--version 2.0.12')
const excluded=new Set(history.filter(r=>r.renumberedTo).map(r=>r.version))
const compare=(a,b)=>{const x=a.split('.').map(Number),y=b.split('.').map(Number);for(let i=0;i<3;i++){if(x[i]!==y[i])return x[i]-y[i]}return 0}
const source=fs.readFileSync(path.join(root,'CHANGELOG.md'),'utf8')
const releases=[...source.matchAll(/^## \[([\d.]+)\] - ([\d-]+)\r?\n([\s\S]*?)(?=^## |$(?![\s\S]))/gm)]
 .map(m=>({version:m[1],date:m[2],notes:[...m[3].matchAll(/^(?:[-*]|\d+[.)])\s+(.+)$/gm)].map(x=>x[1])}))
 .filter(r=>!excluded.has(r.version)&&compare(r.version,currentVersion)<=0)
 .sort((a,b)=>compare(b.version,a.version))
const latest=releases[0]
if(!latest||latest.version!==currentVersion)throw new Error('缺少当前版本的更新说明：'+currentVersion)
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
const card=r=>`<article class="update-card"><h3>v${esc(r.version)}</h3><time datetime="${esc(r.date)}">${esc(r.date)}</time><ol>${r.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ol></article>`
const updateRows=releases.slice(0,3).map(card).join('\n')+(releases.length>3?`<details><summary>更早的更新记录</summary><div class="older-updates">${releases.slice(3).map(card).join('\n')}</div></details>`:'')
const substitutions={'latest.version':latest.version,'latest.date':latest.date,updateRows}
fs.mkdirSync(path.join(out,'assets'),{recursive:true})
const pages={}
for(const file of ['index.html','guide.html']){
 const html=fs.readFileSync(path.join(__dirname,file),'utf8').replace(/\{\{([\w.]+)\}\}/g,(_m,key)=>{
  if(!(key in substitutions))throw new Error('缺少页面变量：'+key)
  return key==='updateRows'?substitutions[key]:esc(substitutions[key])
 })
 pages[file]=html
}
const css=fs.readFileSync(path.join(__dirname,'site.css'),'utf8')
if(/@import|url\s*\(/i.test(css))throw new Error('单文件网站的样式不能依赖外部资源')
const embeddedCss=css+'\n.embedded-guide > .guide-main { padding:36px 0 80px; }\n'
const mainPattern=/<main\b[^>]*>([\s\S]*?)<\/main>/i
const content=file=>{
 const match=pages[file].match(mainPattern)
 if(!match)throw new Error('缺少页面正文：'+file)
 return match[1]
}
const home=content('index.html').replace('<section class="hero">','<section class="hero" id="home">')
const guide='<section class="embedded-guide section" id="guide"><div class="guide-main">'+content('guide.html')+'</div></section>'
const assetNames=new Set(['app-icon.png','welcome.png','portrait.png'])
function embedAssets(html){
 return html.replace(/(src|href)="assets\/([^"/]+)"/g,(_m,attribute,name)=>{
  if(!assetNames.has(name))throw new Error('未知图片资源：'+name)
  const bytes=fs.readFileSync(path.join(root,'renderer/assets',name))
  if(!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))throw new Error('图片格式无效：'+name)
  return attribute+'="data:image/png;base64,'+bytes.toString('base64')+'"'
 })
}
for(const file of ['index.html','guide.html']){
 let html=pages[file].replace(mainPattern,()=>'<main id="main">'+(file==='guide.html'?guide+home:home+guide)+'</main>')
 html=html.replace(/href="(?:index|guide)\.html(?:#([^"]+))?"/g,(_m,anchor)=>'href="#'+(anchor||(_m.includes('guide.html')?'guide':'home'))+'"')
 html=html.replace('<link rel="stylesheet" href="site.css">',()=>'<style>'+embeddedCss+'</style>')
 html=embedAssets(html)
 fs.writeFileSync(path.join(out,file),html)
}
// Each entry contains the entire site and can be shared as one HTML file.
fs.copyFileSync(path.join(out,'index.html'),path.join(out,'星译官官网.html'))
// Public metadata deliberately contains no installer paths or addresses.
fs.writeFileSync(path.join(out,'releases.json'),JSON.stringify(releases,null,2)+'\n')
fs.writeFileSync(path.join(out,'.nojekyll'),'')
console.log(JSON.stringify({mode:'self-contained-information',version:latest.version,releases:releases.length,directory:out,standalone:'星译官官网.html'}))
