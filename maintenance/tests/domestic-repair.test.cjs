const {test}=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events'),{PassThrough}=require('node:stream'),fs=require('node:fs/promises')
const {curlConfig,curlUpload,staleUpload,stopStaleUploads}=require('../domestic-repair.cjs')
const url='https://file.gitcode.com/synthetic?signature=private-fixture',headers={'Content-Type':'application/octet-stream','x-obs-callback':'private-fixture-callback'}
test('signed upload configuration rejects redirects, foreign hosts and header injection',()=>{
 assert.match(curlConfig(url,headers),/url = /)
 assert.throws(()=>curlConfig('https://unrelated.example/file',headers))
 assert.throws(()=>curlConfig(url,{'x-obs-callback':'value\r\nInjected: yes'}))
 assert.throws(()=>curlConfig(url,{'Proxy-Authorization':'no'}))
})
test('curl keeps signed URLs and headers out of command arguments, preserves bytes and removes its own temporary files',async()=>{
 let folder,received,command,args
 const spawn=(name,values,options)=>{
  command=name;args=values;assert.equal(options.windowsHide,true)
  const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdin=new PassThrough()
  child.stdin.on('data',value=>received=(received||'')+value)
  child.stdin.on('finish',async()=>{
   const file=values[values.indexOf('--upload-file')+1];folder=require('node:path').dirname(file)
   assert.deepEqual(await fs.readFile(file),Buffer.from('same-original-bytes'))
   await fs.writeFile(values[values.indexOf('--output')+1],'<Complete/>')
   child.stdout.write('200');child.emit('close',0)
  });return child
 }
 const result=await curlUpload(url,{body:Buffer.from('same-original-bytes'),headers},spawn)
 assert.equal(result.status,200);assert.equal(await result.text(),'<Complete/>')
 assert.equal(command,'curl.exe');assert(!args.some(value=>value.includes('private-fixture')))
 assert(!args.includes('--location'));assert(received.includes('private-fixture-callback'))
 await assert.rejects(fs.stat(folder),{code:'ENOENT'})
})
test('curl failures never expose signed URLs or private stderr',async()=>{
 const spawn=()=>{const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdin=new PassThrough();child.stdin.on('finish',()=>{child.stderr.write(url);child.emit('close',28)});return child}
 await assert.rejects(curlUpload(url,{body:Buffer.from('bytes'),headers},spawn),error=>error.message.includes('28')&&!error.message.includes('private-fixture'))
})
test('only an upload attached to the same immutable release with a successful build may be stopped',()=>{
 const run={id:10,head_sha:'a'.repeat(40),status:'in_progress',name:'Build and publish StarTranslator'}
 const jobs=[{name:'windows',status:'completed',conclusion:'success'},{name:'public-mirror / mirror',status:'in_progress'}]
 assert(staleUpload(run,jobs,run.head_sha,11))
 assert(!staleUpload(run,jobs,run.head_sha,10))
 assert(!staleUpload(run,jobs,'b'.repeat(40),11))
 assert(!staleUpload(run,[{name:'windows',status:'in_progress'},jobs[1]],run.head_sha,11))
 assert(!staleUpload({...run,name:'another workflow'},jobs,run.head_sha,11))
})
test('a successful empty 202 cancellation response is accepted and completion is confirmed before recovery',async()=>{
 const prior=process.env.GITHUB_TOKEN;process.env.GITHUB_TOKEN='synthetic-github-workflow-token'
 const calls=[],sha='a'.repeat(40)
 try{
  const fetcher=async(url,options)=>{
   assert(url.startsWith('https://api.github.com/repos/MathiasCym/StarTranslator/'))
   assert.equal(options.redirect,'error');calls.push([url,options.method])
   if(url.endsWith('/cancel'))return new Response(null,{status:202})
   if(url.includes('/releases/tags/'))return Response.json({target_commitish:sha,draft:false,prerelease:false})
   if(url.includes('/actions/runs?'))return Response.json({workflow_runs:[{id:10,head_sha:sha,status:'in_progress',name:'Build and publish StarTranslator'}]})
   if(url.endsWith('/jobs'))return Response.json({jobs:[{name:'windows',status:'completed',conclusion:'success'},{name:'public-mirror / mirror',status:'in_progress'}]})
   return Response.json({status:'completed'})
  }
  const result=await stopStaleUploads(require('node:path').resolve(__dirname,'../..'),fetcher,async()=>assert.fail('already completed'))
  assert.deepEqual(result.stopped,[10]);assert.equal(calls.filter(([,method])=>method==='POST').length,1)
 }finally{if(prior===undefined)delete process.env.GITHUB_TOKEN;else process.env.GITHUB_TOKEN=prior}
})
