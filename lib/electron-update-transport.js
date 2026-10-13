// Electron's fetch cancels manual redirects. Validate ClientRequest redirects
// synchronously, then expose its response as the stream used by the updater.
const {Readable}=require('node:stream')
const {trusted}=require('./github-updates')
function createFetcher(net){
  return (url,options={})=>new Promise((resolve,reject)=>{
    if(options.signal?.aborted){reject(new Error('更新请求已取消。'));return}
    let response,redirects=0,finished=false
    const request=net.request({url:trusted(url),method:'GET',redirect:'manual',credentials:'omit',useSessionCookies:false,headers:options.headers||{}})
    const cleanup=()=>options.signal?.removeEventListener('abort',abort)
    const fail=error=>{reject(error);if(response&&!response.destroyed)response.destroy(error)}
    const abort=()=>{if(!finished)fail(new Error('更新请求已取消。'));request.abort()}
    request.on('error',fail)
    request.on('close',cleanup)
    request.on('redirect',(_status,_method,target)=>{
      try{if(++redirects>5)throw Error('更新下载地址跳转过多。');trusted(target);request.followRedirect()}
      catch(error){fail(error);request.abort()}
    })
    request.on('response',incoming=>{
      response=incoming
      incoming.once('end',()=>{finished=true;cleanup()})
      incoming.once('close',()=>request.abort())
      const headers=new Headers();for(const [name,value] of Object.entries(incoming.headers))headers.set(name,Array.isArray(value)?value.join(', '):String(value))
      try{resolve(new Response([204,205,304].includes(incoming.statusCode)?null:Readable.toWeb(incoming),{status:incoming.statusCode,headers}))}
      catch(error){fail(error);request.abort()}
    })
    options.signal?.addEventListener('abort',abort,{once:true})
    request.end()
  })
}
module.exports={createFetcher}
