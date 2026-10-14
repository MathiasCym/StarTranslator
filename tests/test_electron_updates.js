const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events'),{PassThrough}=require('node:stream')
const {createFetcher}=require('../lib/electron-update-transport'),{fetchTrusted}=require('../lib/github-updates')
function fixture(hops=[],body='released bytes'){
 const state={followed:[],options:null,aborted:false,response:null}
 const net={request(options){state.options=options;const r=new EventEmitter();r.abort=()=>{if(state.aborted)return;state.aborted=true;r.emit('close')};r.followRedirect=()=>state.followed.push(state.target)
  r.end=()=>queueMicrotask(()=>{for(const target of hops){state.target=target;const before=state.followed.length;r.emit('redirect',302,'GET',target,{});if(state.aborted)return;if(state.followed.length===before){r.emit('error',Error('Redirect was cancelled'));return}}
   const response=new PassThrough();Object.assign(response,{statusCode:200,headers:{'content-length':String(Buffer.byteLength(body))}});state.response=response;r.emit('response',response);if(body!==null)response.end(body)
  });return r}}
 return {state,fetcher:createFetcher(net)}
}
test('Chromium manual redirects follow synchronously after trusted-host validation and stream intact bytes',async()=>{const hops=['https://github.com/MathiasCym/StarTranslator/releases/download/v2.0.0/x.exe','https://release-assets.githubusercontent.com/github-production-release-asset/x'];const f=fixture(hops);const r=await fetchTrusted(f.fetcher,'https://api.github.com/repos/MathiasCym/StarTranslator/releases/latest');assert.equal(await r.text(),'released bytes');assert.deepEqual(f.state.followed,hops);assert.equal(f.state.options.redirect,'manual');assert.equal(f.state.options.credentials,'omit');assert.equal(f.state.options.useSessionCookies,false)})
test('Untrusted or insecure redirects are aborted before following or exposing response bytes',async()=>{for(const url of ['https://example.com/exe','http://github.com/exe']){const f=fixture([url]);await assert.rejects(fetchTrusted(f.fetcher,'https://github.com/exe'),/可信/);assert.deepEqual(f.state.followed,[]);assert(f.state.aborted)}})
test('Redirect loops are bounded even when every host is trusted',async()=>{const f=fixture(Array.from({length:7},(_,i)=>'https://github.com/'+i));await assert.rejects(f.fetcher('https://github.com/start'),/跳转过多/);assert.equal(f.state.followed.length,5);assert(f.state.aborted)})
test('Cancellation after response headers aborts the Chromium request and pending body read',async()=>{const f=fixture([],'');const original=f.state;const net={request(options){const r=new EventEmitter();r.abort=()=>{original.aborted=true;r.emit('close')};r.end=()=>queueMicrotask(()=>{const response=new PassThrough();Object.assign(response,{statusCode:200,headers:{}});original.response=response;r.emit('response',response)});return r}};const controller=new AbortController(),response=await createFetcher(net)('https://github.com/exe',{signal:controller.signal});const read=response.body.getReader().read();controller.abort();await assert.rejects(read,/取消/);assert(original.aborted)})
test('Domestic Chromium redirects use the scoped source validator without sharing cookies',async()=>{
 const s=require('../lib/distribution-sources').source('gitcode','synthetic/StarTranslator'),f=fixture(['https://file-cdn.gitcode.com/public/file'])
 const response=await fetchTrusted(f.fetcher,s.web+'/releases/download/v2.0.4/x.exe',{},s.trusted)
 assert.equal(await response.text(),'released bytes');assert.equal(f.state.followed.length,1);assert.equal(f.state.options.useSessionCookies,false)
 const bad=fixture(['https://release-assets.githubusercontent.com/x']);await assert.rejects(fetchTrusted(bad.fetcher,s.web+'/x',{},s.trusted),/可信/);assert.equal(bad.state.followed.length,0)
})

function routeFixture({directFailure=false,stall=false}={}){
 const calls=[],configs=[],scoped={setProxy:async value=>configs.push(value)},sessions={fromPartition:(name,options)=>{assert.equal(name,'startranslator-public-updates-direct');assert.equal(options.cache,false);return scoped}}
 const net={request(options){calls.push(options);const r=new EventEmitter();let stopped=false;r.abort=()=>{stopped=true;r.emit('close')};r.followRedirect=()=>{};r.end=()=>queueMicrotask(()=>{
  if(stopped)return
  if(options.session&&stall)return
  if(options.session&&directFailure){r.emit('error',Error('net::ERR_CONNECTION_REFUSED'));return}
  const body=new PassThrough();Object.assign(body,{statusCode:200,headers:{}});r.emit('response',body);body.end('public')
 });return r}}
 return {calls,configs,scoped,fetcher:createFetcher(net,{session:sessions,directHeaderTimeout:20})}
}
test('domestic updates use an isolated direct session while GitHub retains the system route',async()=>{
 const f=routeFixture(),s=require('../lib/distribution-sources').source('atomgit','synthetic/StarTranslator'),routes=[]
 assert.equal(await(await fetchTrusted(f.fetcher,s.web+'/x',{onRoute:v=>routes.push(v)},s.trusted)).text(),'public')
 await fetchTrusted(f.fetcher,'https://api.github.com/repos/MathiasCym/StarTranslator/releases/latest')
 assert.deepEqual(f.configs,[{mode:'direct'}]);assert.equal(f.calls[0].session,f.scoped);assert.equal(f.calls[1].session,undefined)
 assert.deepEqual(routes,[{route:'direct',host:'atomgit.com'}]);assert(f.calls.every(c=>c.credentials==='omit'&&!c.useSessionCookies))
})
test('failed direct connections retry the same public source through system networking',async()=>{
 for(const option of [{directFailure:true},{stall:true}]){
  const f=routeFixture(option),s=require('../lib/distribution-sources').source('atomgit','synthetic/StarTranslator')
  assert.equal(await(await fetchTrusted(f.fetcher,s.web+'/x',{},s.trusted)).text(),'public')
  assert.equal(f.calls.length,2);assert.equal(f.calls[0].session,f.scoped);assert.equal(f.calls[1].session,undefined)
 }
})
test('explicit system route and user cancellation do not attempt another connection',async()=>{
 const s=require('../lib/distribution-sources').source('atomgit','synthetic/StarTranslator'),f=routeFixture({stall:true})
 await fetchTrusted(f.fetcher,s.web+'/x',{networkMode:'system'},s.trusted);assert.equal(f.calls[0].session,undefined)
 const controller=new AbortController(),pending=fetchTrusted(f.fetcher,s.web+'/x',{signal:controller.signal},s.trusted)
 await new Promise(resolve=>setTimeout(resolve,5));controller.abort();await assert.rejects(pending,/取消/);assert.equal(f.calls.length,2)
})
