const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync,spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),version=JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version,folder=path.join(root,'dist/qa/release-200/extracted')
fs.mkdirSync(folder,{recursive:true})
const zip=process.env['ProgramFiles']+'\\7-Zip\\7z.exe'
execFileSync(zip,['x',path.join(root,'dist/星译官 Setup '+version+'.exe'),'-y','-o'+folder],{windowsHide:true,stdio:'ignore'})
const stage=path.join(folder,'$PLUGINSDIR/stage'),images=spawnSync(process.execPath,[path.join(root,'tools/check-setup-images.cjs'),stage],{cwd:root,windowsHide:true,stdio:'inherit'})
assert.equal(images.status,0,'Installer images failed')
const verification=spawnSync(path.join(root,'node_modules/electron/dist/electron.exe'),[path.join(root,'tools/verify-payload.cjs'),folder],{cwd:root,windowsHide:true,stdio:'inherit'})
assert.equal(verification.status,0,'Installer payload failed')
