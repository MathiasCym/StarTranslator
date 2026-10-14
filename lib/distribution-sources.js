// Owned public repositories only. Publishing credentials never enter this config.
const REPOSITORY='MathiasCym/StarTranslator'
const PLATFORMS={
  github:{name:'GitHub',api:'https://api.github.com/repos/',web:'https://github.com/',hosts:['api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com']},
  atomgit:{name:'AtomGit',api:'https://api.atomgit.com/api/v5/repos/',web:'https://atomgit.com/',assetOrigins:['https://atomgit.com','https://gitcode.com'],hosts:['api.atomgit.com','atomgit.com','file-cdn.atomgit.com','raw.atomgit.com','gitcode.com','file-cdn.gitcode.com','raw.gitcode.com']},
  gitcode:{name:'AtomGit / GitCode',api:'https://api.gitcode.com/api/v5/repos/',web:'https://gitcode.com/',hosts:['api.gitcode.com','gitcode.com','file-cdn.gitcode.com','raw.gitcode.com']},
  gitee:{name:'Gitee',api:'https://gitee.com/api/v5/repos/',web:'https://gitee.com/',hosts:['gitee.com','foruda.gitee.com','raw.giteeusercontent.com']},
}
function repository(value){
  if(typeof value!=='string'||value.length>200||!value.split('/').every(part=>/^[A-Za-z0-9_-][A-Za-z0-9_.-]*$/.test(part)&&!part.includes('..'))||value.split('/').length!==2)throw Error('公开镜像仓库地址无效。')
  return value
}
function source(provider,repo){
  const platform=PLATFORMS[provider];if(!platform)throw Error('不支持此发布平台。')
  repository(repo)
  const trusted=url=>{const value=new URL(url);if(value.protocol!=='https:'||!platform.hosts.includes(value.hostname)||value.username||value.password||value.port)throw Error('更新下载地址不属于可信发布服务。');return value.href}
  const assetUrl=(url,tag,filename)=>{
    const value=new URL(trusted(url)),expected=new URL(platform.web+repo+'/releases/download/'+tag+'/'+filename)
    if(!(platform.assetOrigins||[expected.origin]).includes(value.origin)||value.pathname!==expected.pathname||value.search||value.hash)throw Error('发布包地址与版本不一致。')
    return value.href
  }
  return {id:provider+':'+repo,provider,repository:repo,name:platform.name,api:platform.api+repo+'/',web:platform.web+repo,trusted,assetUrl}
}
const GITHUB=source('github',REPOSITORY)
function mirrors(config){
  if(!config||config.schema!==1||Object.keys(config).some(key=>!['schema','mirrors'].includes(key))||!Array.isArray(config.mirrors)||config.mirrors.length>2)throw Error('公开来源配置无效。')
  const seen=new Set()
  return config.mirrors.map(item=>{
    if(!item||!['atomgit','gitcode','gitee'].includes(item.provider)||Object.keys(item).some(key=>!['provider','repository'].includes(key)))throw Error('公开来源配置不得包含授权或自定义网址。')
    const value=source(item.provider,item.repository),family=value.provider==='gitcode'?'atomgit':value.provider;if(seen.has(family))throw Error('公开来源配置重复。');seen.add(family);return value
  })
}
function manifest(value,version,filename){
  if(!value||value.schema!==1||value.version!==version||value.platform!=='win32'||value.architecture!=='x64'||value.filename!==filename||!Number.isSafeInteger(value.size)||value.size<256*1024||value.size>1024*1024*1024||!/^[a-f0-9]{64}$/.test(value.sha256||''))throw Error('镜像发布信息与安装包不一致，暂不能更新。')
  return value
}
module.exports={GITHUB,REPOSITORY,PLATFORMS,source,mirrors,manifest}
