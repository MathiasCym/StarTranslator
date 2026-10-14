// Electron's fetch cancels manual redirects. Validate ClientRequest redirects
// synchronously, then expose its response as the stream used by the updater.
const {Readable}=require('node:stream')
const {trusted}=require('./github-updates')
const {PLATFORMS}=require('./distribution-sources')
const domesticHosts=new Set(['atomgit','gitcode','gitee'].flatMap(key=>PLATFORMS[key].hosts))
function isDomestic(url){const value=new URL(url);return value.protocol==='https:'&&domesticHosts.has(value.hostname)}
function createFetcher(net,{session,directHeaderTimeout=5000}={}){
  let directSession,configured
  function direct(){
    if(!configured){directSession=session.fromPartition('startranslator-public-updates-direct',{cache:false});configured=directSession.setProxy({mode:'direct'}).then(()=>directSession)}
    return configured
  }
  const requestOnce=(url,options,route,selectedSession)=>new Promise((resolve,reject)=>{
    if(options.signal?.aborted){reject(new Error('更新请求已取消。'));return}
    let response,redirects=0,finished=false,headerTimer,finalUrl=url
    const validateUrl=options.validateUrl||trusted
    const request=net.request({url:validateUrl(url),method:'GET',redirect:'manual',credentials:'omit',useSessionCookies:false,headers:options.headers||{},...(selectedSession?{session:selectedSession}:{})})
    const cleanup=()=>{clearTimeout(headerTimer);options.signal?.removeEventListener('abort',abort)}
    const fail=error=>{cleanup();reject(error);if(response&&!response.destroyed)response.destroy(error)}
    const abort=()=>{if(!finished)fail(new Error('更新请求已取消。'));request.abort()}
    request.on('error',fail)
    request.on('close',cleanup)
    request.on('redirect',(_status,_method,target)=>{
      try{if(++redirects>5)throw Error('更新下载地址跳转过多。');finalUrl=validateUrl(target);if(route==='direct'&&!isDomestic(finalUrl))throw Error('国内直连不能跳转至其他来源。');request.followRedirect()}
      catch(error){fail(error);request.abort()}
    })
    request.on('response',incoming=>{
      response=incoming
      clearTimeout(headerTimer)
      incoming.once('end',()=>{finished=true;cleanup()})
      incoming.once('close',()=>request.abort())
      const headers=new Headers();for(const [name,value] of Object.entries(incoming.headers))headers.set(name,Array.isArray(value)?value.join(', '):String(value))
      try{options.onRoute?.({route,host:new URL(finalUrl).hostname});resolve(new Response([204,205,304].includes(incoming.statusCode)?null:Readable.toWeb(incoming),{status:incoming.statusCode,headers}))}
      catch(error){fail(error);request.abort()}
    })
    options.signal?.addEventListener('abort',abort,{once:true})
    if(route==='direct')headerTimer=setTimeout(()=>{fail(Object.assign(Error('国内直连连接超时。'),{code:'ETIMEDOUT'}));request.abort()},directHeaderTimeout)
    request.end()
  })
  return async(url,options={})=>{
    const value=(options.validateUrl||trusted)(url)
    if(options.signal?.aborted)throw Error('更新请求已取消。')
    if(!session||!isDomestic(value)||options.networkMode==='system')return requestOnce(value,options,'system')
    try{
      const response=await requestOnce(value,options,'direct',await direct())
      if(options.networkMode!=='direct'&&(response.status===403||response.status>=500)){await response.body?.cancel();return requestOnce(value,options,'system')}
      return response
    }
    catch(error){if(options.signal?.aborted||options.networkMode==='direct'||error.code!=='ETIMEDOUT'&&!/^net::ERR_(?:CONNECTION|NAME|PROXY|ADDRESS|INTERNET|NETWORK|TIMED_OUT)/.test(error.message||''))throw error;return requestOnce(value,options,'system')}
  }
}
module.exports={createFetcher,isDomestic}
