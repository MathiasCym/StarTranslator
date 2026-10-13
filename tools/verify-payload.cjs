const fs=require('fs'),path=require('path'),assert=require('assert/strict'),{app}=require('electron')
const root=path.resolve(__dirname,'..'),folder=path.resolve(process.argv[2]),version=JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version
const bytes=fs.readFileSync(path.join(folder,'resources/install-manifest.json'))
assert(bytes.equals(fs.readFileSync(path.join(root,'dist/win-unpacked/resources/install-manifest.json'))))
assert(bytes.equals(fs.readFileSync(path.join(folder,'$PLUGINSDIR/stage/resources/install-manifest.json'))))
require('../lib/install-integrity').verifyInstallation(folder,JSON.parse(bytes),version).then(result=>{
 assert(result.complete,JSON.stringify(result.failures));fs.writeFileSync(path.join(root,'dist/qa/release-200/payload-result.json'),JSON.stringify({passed:true,version,files:result.checked,stageMatches:true},null,2));console.log('Verified '+result.checked+' installer files');app.exit(0)
}).catch(error=>{console.error(error);app.exit(1)})
