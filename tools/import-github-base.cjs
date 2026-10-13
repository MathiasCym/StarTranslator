// Fetch transport fallback: restore verified Git objects without changing work files.
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8').replace(/^\ufeff/,''))
function git(args,content){const result=spawnSync('git',args,{input:content,encoding:'utf8',windowsHide:true});if(result.status!==0)throw Error(result.stderr);return result.stdout.trim()}
for(const blob of input.blobs)assert.equal(git(['hash-object','-w','--stdin'],blob.content),blob.sha,blob.path)
const tree=git(['mktree'],input.blobs.map(b=>'100644 blob '+b.sha+'\t'+b.path).join('\n')+'\n');assert.equal(tree,input.commit.tree.sha)
const verification=input.commit.verification;assert(verification.payload&&verification.signature)
const split=verification.payload.indexOf('\n\n'),headers=verification.payload.slice(0,split).split('\n'),message=verification.payload.slice(split+2)
let body,hash
for(const ending of ['', '\n'])for(const signature of [verification.signature.trimEnd(),verification.signature])for(let location=0;location<=headers.length;location++){
  const parts=[...headers];parts.splice(location,0,'gpgsig '+signature.replaceAll('\n','\n '));const value=parts.join('\n')+'\n\n'+message+ending
  const valueHash=crypto.createHash('sha1').update('commit '+Buffer.byteLength(value)+'\0'+value).digest('hex')
  if(valueHash===input.commit.sha){body=value;hash=valueHash}
}
assert.equal(hash,input.commit.sha,'GitHub commit byte representation was not verified')
assert.equal(git(['hash-object','-t','commit','-w','--stdin'],body),hash)
git(['update-ref','refs/remotes/origin/main',hash]);git(['update-ref','refs/heads/main',hash]);git(['read-tree','HEAD'])
console.log(JSON.stringify({imported:true,head:hash,tree,workFilesUnchanged:true}))
