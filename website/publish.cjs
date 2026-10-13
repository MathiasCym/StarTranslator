// Publish only the static website and recorded installer assets. Never app source/configuration.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),repo=process.argv[2]
if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo||''))throw new Error('用法：node website/publish.cjs 账号名/公开仓库名')
const branch='startranslator-site',stage=path.join(__dirname,'publish-work'),marker=path.join(stage,'.startranslator-site.json')
function run(exe,args,cwd=__dirname,quiet=false){const r=spawnSync(exe,args,{cwd,windowsHide:true,encoding:'utf8',stdio:quiet?['ignore','pipe','pipe']:['ignore','pipe','inherit']});if(r.error)throw r.error;if(r.status!==0)throw new Error(exe+' '+args[0]+' 执行失败'+(quiet?'：'+r.stderr.trim():''));return r.stdout.trim()}
function gh(args,quiet=false){return run('gh',[...args,'--repo',repo],__dirname,quiet)}
function api(endpoint,args=[]){return run('gh',['api',endpoint,...args],__dirname,true)}
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
run('gh',['auth','status'],__dirname,true)
run('gh',['auth','setup-git'],__dirname,true)
run('git',['--version'],__dirname,true)
const user=JSON.parse(api('user'))
const commitIdentity=['-c','user.name='+user.login,'-c',`user.email=${user.id}+${user.login}@users.noreply.github.com`]
let info
try{info=JSON.parse(run('gh',['repo','view',repo,'--json','nameWithOwner,visibility'],__dirname,true))}catch(error){
  // Explicit repository creation is part of publishing to the supplied destination.
  run('gh',['repo','create',repo,'--public','--description','星译官版本下载与使用指南'],__dirname)
  info=JSON.parse(run('gh',['repo','view',repo,'--json','nameWithOwner,visibility'],__dirname,true))
}
if(info.visibility!=='PUBLIC')throw new Error('请使用公开的独立网站仓库；本工具不会修改既有私有仓库的可见性。')
const history=JSON.parse(fs.readFileSync(path.join(root,'release-history.json'))).filter(r=>!r.renumberedTo&&fs.existsSync(path.join(root,r.installer)))
for(const r of history){const file=path.join(root,r.installer);if(fs.statSync(file).size!==r.size||hash(file)!==r.sha256)throw new Error('安装包校验失败：'+r.version)}
fs.mkdirSync(stage,{recursive:true})
const git=args=>run('git',args,stage)
if(!fs.existsSync(path.join(stage,'.git'))){
  if(fs.readdirSync(stage).length)throw new Error('发布工作目录已有不明文件，请选择干净的工作目录。')
  git(['init','--initial-branch='+branch]);git(['remote','add','origin','https://github.com/'+repo+'.git'])
}
if(git(['remote','get-url','origin'])!=='https://github.com/'+repo+'.git')throw new Error('发布工作目录对应另一仓库。')
if(git(['branch','--show-current'])!==branch)throw new Error('当前分支不是网站发布分支。')
const remoteBranch=git(['ls-remote','--heads','origin',branch])
if(remoteBranch){
  git(['fetch','origin',branch])
  if(!fs.existsSync(marker)){
    if(fs.readdirSync(stage).some(file=>file!=='.git'))throw new Error('发布工作目录已有不明文件，未覆盖。')
    const remoteMarker=JSON.parse(git(['show','FETCH_HEAD:.startranslator-site.json']))
    if(remoteMarker.repository!==repo||remoteMarker.product!=='StarTranslator')throw new Error('远端分支不是本网站，未覆盖。')
    git(['checkout','-B',branch,'FETCH_HEAD'])
  }else git(['pull','--ff-only','origin',branch])
  if(!fs.existsSync(marker)||JSON.parse(fs.readFileSync(marker)).repository!==repo)throw new Error('网站分支缺少星译官发布标记，已停止以避免覆盖其他内容。')
}else{
  fs.writeFileSync(marker,JSON.stringify({repository:repo,product:'StarTranslator'},null,2)+'\n')
  fs.writeFileSync(path.join(stage,'README.md'),'# 星译官\n\n版本下载与使用指南。\n')
  git(['add','.']);git([...commitIdentity,'commit','-m','Prepare StarTranslator website'])
  git(['push','--set-upstream','origin',branch])
}
const assets=path.join(__dirname,'release-assets');fs.mkdirSync(assets,{recursive:true})
const published=[]
for(const r of history){
  const asset=`StarTranslator-Setup-${r.version}.exe`,temp=path.join(assets,asset)
  let release
  try{release=JSON.parse(gh(['release','view','v'+r.version,'--json','assets'],true))}catch{
    const notes=path.join(assets,'release-notes.txt')
    fs.writeFileSync(notes,'星译官 '+r.version+' Windows x64 安装包。\n\n发布者：MathiasCym\n\nSHA-256: '+r.sha256+'\n')
    gh(['release','create','v'+r.version,'--target',branch,'--title','星译官 '+r.version,'--notes-file',notes])
    release={assets:[]}
  }
  const existing=release.assets.find(a=>a.name===asset)
  if(existing&&existing.size!==r.size)throw new Error('远端同名安装包大小不符，未覆盖：'+r.version)
  if(!existing){
    fs.copyFileSync(path.join(root,r.installer),temp)
    try{gh(['release','upload','v'+r.version,temp])}finally{fs.unlinkSync(temp)}
  }
  const check=JSON.parse(api(`repos/${repo}/releases/tags/v${r.version}`)).assets.find(a=>a.name===asset)
  if(!check||check.size!==r.size)throw new Error('远端安装包验证失败：'+r.version)
  if(check.digest&&check.digest!=='sha256:'+r.sha256)throw new Error('远端安装包校验值不符：'+r.version)
  if(!check.digest){
    gh(['release','download','v'+r.version,'--pattern',asset,'--dir',assets])
    try{if(hash(temp)!==r.sha256)throw new Error('远端安装包校验值不符：'+r.version)}finally{fs.unlinkSync(temp)}
  }
  published.push(r.version)
  console.log('已核对安装包 v'+r.version)
}
fs.writeFileSync(path.join(__dirname,'hosting.json'),JSON.stringify({repository:repo,publishedVersions:published},null,2)+'\n')
run(process.execPath,[path.join(__dirname,'build.cjs'),'--public'])
fs.cpSync(path.join(__dirname,'dist'),stage,{recursive:true})
git(['add','.']);if(git(['status','--porcelain']))git([...commitIdentity,'commit','-m','Update StarTranslator downloads and guide'])
git(['push','origin',branch])
const payload=path.join(__dirname,'pages-request.json');fs.writeFileSync(payload,JSON.stringify({build_type:'legacy',source:{branch,path:'/'}}))
let pages
try{pages=JSON.parse(api(`repos/${repo}/pages`))}
catch{pages=JSON.parse(api(`repos/${repo}/pages`,['--method','POST','--input',payload]))}
if(pages.source?.branch!==branch||pages.source?.path!=='/')throw new Error('该仓库 Pages 已关联其他来源。文件已上传，请在 Settings → Pages 人工选择网站分支；未改动原网站来源。')
pages=JSON.parse(api(`repos/${repo}/pages`))
console.log('静态网站已提交。GitHub Pages 构建完成后访问：'+pages.html_url)
console.log('可在仓库 Pages 页面检查部署状态。')
