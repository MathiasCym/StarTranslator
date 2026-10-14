// Configure an owned public mirror; never accept a publishing token here.
const fs=require('node:fs'),path=require('node:path'),{mirrors}=require('../lib/distribution-sources')
function fromUrl(input){
 const url=new URL(input),providers={'atomgit.com':'atomgit','gitcode.com':'gitcode','gitee.com':'gitee'}
 if(url.protocol!=='https:'||!providers[url.hostname]||url.username||url.password||url.port||url.search||url.hash)throw Error('请提供 GitCode 或 Gitee 公开仓库的 HTTPS 网页地址。')
 const repository=url.pathname.replace(/^\//,'').replace(/\/$/,'').replace(/\.git$/,'')
 const config={schema:1,mirrors:[{provider:providers[url.hostname],repository}]};mirrors(config);return config
}
function configure(input,root=path.resolve(__dirname,'..')){
 const config=fromUrl(input),target=path.join(root,'backend/distribution.json'),temp=target+'.'+process.pid+'.tmp'
 try{fs.writeFileSync(temp,JSON.stringify(config,null,2)+'\n',{flag:'wx'});fs.renameSync(temp,target)}finally{if(fs.existsSync(temp))fs.unlinkSync(temp)}
 return config
}
if(require.main===module){try{console.log(JSON.stringify(configure(process.argv[2]),null,2))}catch(error){console.error(error.message);process.exitCode=1}}
module.exports={fromUrl,configure}
