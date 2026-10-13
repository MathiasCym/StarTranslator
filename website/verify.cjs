const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto'),assert=require('node:assert/strict')
const out=path.join(__dirname,'dist'),base=process.argv[2],links=[]
const releases=JSON.parse(fs.readFileSync(path.join(out,'releases.json')))
function head(url,expected=200){return new Promise((resolve,reject)=>{
 const req=http.request(url,{method:'HEAD'},res=>{res.resume();res.on('end',()=>res.statusCode===expected?resolve():reject(new Error(res.statusCode+' '+url)))})
 req.on('error',reject);req.end()
})}
;(async()=>{
 const assets=path.resolve(__dirname,'../renderer/assets')
 const knownImages=new Set(['app-icon.png','welcome.png','portrait.png'].map(name=>crypto.createHash('sha256').update(fs.readFileSync(path.join(assets,name))).digest('hex')))
 let embeddedImages=0
 for(const page of ['index.html','guide.html','星译官官网.html']){
  const html=fs.readFileSync(path.join(out,page),'utf8')
  assert(!html.includes('{{'));assert(!html.includes('C:\\Users'));assert(html.includes('name="viewport"'))
  assert(!/<a\b[^>]*\sdownload(?:\s|=|>)/i.test(html),'download control')
  assert(html.includes('<style>')&&!/<link[^>]+rel="stylesheet"/i.test(html),'external stylesheet')
  assert(!/@import|url\s*\(/i.test(html.match(/<style>([\s\S]*?)<\/style>/i)[1]),'external style resource')
  assert(html.includes('id="guide"')&&html.includes('id="features"')&&html.includes('id="updates"'),'incomplete standalone content')
  for(const m of html.matchAll(/(?:href|src)="([^"]+)"/g)){
   const link=m[1].replaceAll('&amp;','&');assert(!/\.exe|releases\/download|\/downloads\//i.test(link),'installer link '+link)
   if(link.startsWith('data:image/png;base64,')){
    const bytes=Buffer.from(link.slice('data:image/png;base64,'.length),'base64')
    assert(knownImages.has(crypto.createHash('sha256').update(bytes).digest('hex')),'embedded image differs from original')
    embeddedImages++;continue
   }
   assert(!/^[\w+.-]+:|^\/\//.test(link),'remote resource '+link)
   const [route,anchor]=link.split('#'),target=path.resolve(out,route?decodeURIComponent(route):page)
   assert(!route,'standalone page depends on sibling file '+link)
   assert(target.startsWith(out+path.sep)&&fs.existsSync(target),'missing target '+link)
   if(anchor)assert(fs.readFileSync(target,'utf8').includes('id="'+anchor+'"'),'missing anchor '+link)
   if(route)links.push(new URL(route,new URL(page,base||'http://localhost/')).href)
  }
 }
 for(const r of releases){assert.deepEqual(Object.keys(r).sort(),['date','notes','version']);assert(r.notes.length>0)}
 for(const file of fs.readdirSync(out,{recursive:true}))assert(!/\.(exe|zip|7z)$/i.test(file),'binary distribution')
 const guide=fs.readFileSync(path.join(out,'guide.html'),'utf8')
 for(const id of ['combined','review','export','history','glossary'])assert(guide.includes('id="'+id+'"'))
 if(base){
  assert.equal(new URL(base).hostname,'127.0.0.1');for(const page of ['index.html','guide.html','星译官官网.html'])links.push(new URL(page,base).href)
  for(const url of new Set(links))await head(url)
  await head(new URL('/downloads/StarTranslator-Setup-'+releases[0].version+'.exe',base),404)
  await head(new URL('/dist/'+encodeURIComponent('星译官 Setup '+releases[0].version+'.exe'),base),404)
 }
 const result={passed:true,latest:releases[0].version,releaseCount:releases.length,pages:3,selfContained:true,embeddedImages,noDownloadLinks:true,noDownloadMetadata:true,httpLinks:base?new Set(links).size:0}
 fs.writeFileSync(path.join(__dirname,'verification.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result))
})().catch(error=>{console.error(error);process.exitCode=1})
