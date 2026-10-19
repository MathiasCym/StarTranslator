const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path')
const {UpdateNotifications,highlights}=require('../lib/update-notifications')
function fixture(t) {
  const userData=fs.mkdtempSync(path.join(os.tmpdir(),'star-notice-'))
  t.after(()=>fs.rmSync(userData,{recursive:true,force:true}))
  let date=new Date(2026,9,15,8),calls=0,value={version:'2.0.7',notes:'## 更新\n1. 放大字体\n2. 优化布局'}
  const options={userData,currentVersion:'2.0.6',check:async()=>{calls++;return value},now:()=>date}
  return {options,get calls(){return calls},nextDay:()=>{date=new Date(date.getFullYear(),date.getMonth(),date.getDate()+1,8)},set value(v){value=v}}
}
test('each launch checks even on the same day; duplicate calls in a process do not repeat',async t=>{
  const f=fixture(t),a=new UpdateNotifications(f.options)
  assert.equal((await a.startup()).version,'2.0.7');assert.equal(await a.startup(),null)
  assert.equal((await new UpdateNotifications(f.options).startup()).version,'2.0.7');assert.equal(f.calls,2)
  f.nextDay();assert.equal((await new UpdateNotifications(f.options).startup()).version,'2.0.7');assert.equal(f.calls,3)
})
test('a release published later the same day is discovered on the next launch',async t=>{
  const f=fixture(t);f.value={version:'2.0.6',notes:''}
  assert.equal(await new UpdateNotifications(f.options).startup(),null)
  f.value={version:'2.0.7',notes:'1. 新修复'}
  assert.equal((await new UpdateNotifications(f.options).startup()).version,'2.0.7')
  assert.equal(f.calls,2)
})
test('old daily preferences never suppress a launch check and keep ignored versions',async t=>{
  const f=fixture(t),file=path.join(f.options.userData,'update-notifications.json')
  fs.writeFileSync(file,JSON.stringify({checkedDay:'2026-10-15',ignored:['2.0.7']}))
  assert.equal(await new UpdateNotifications(f.options).startup(),null);assert.equal(f.calls,1)
  f.value={version:'2.0.8',notes:''}
  const next=new UpdateNotifications(f.options)
  assert.equal((await next.startup()).version,'2.0.8');next.ignore('2.0.8')
  assert.deepEqual(JSON.parse(fs.readFileSync(file,'utf8')),{ignored:['2.0.7','2.0.8']})
})
test('ignoring a release persists, but future releases remain eligible',async t=>{
  const f=fixture(t),a=new UpdateNotifications(f.options)
  await a.startup();a.ignore('2.0.7')
  assert.equal(await new UpdateNotifications(f.options).startup(),null)
  f.value={version:'2.0.8',notes:''}
  assert.equal((await new UpdateNotifications(f.options).startup()).version,'2.0.8')
  assert.throws(()=>a.ignore('../../other'),'当前更新提醒')
})
test('parallel requests share one check; offline failure is quiet and a new launch retries',async t=>{
  const f=fixture(t)
  fs.writeFileSync(path.join(f.options.userData,'update-notifications.json'),'broken json')
  const a=new UpdateNotifications(f.options),p=a.startup()
  assert.equal(p,a.startup());await p;assert.equal(f.calls,1)
  let failures=0;const b=new UpdateNotifications({...f.options,check:async()=>{failures++;throw Error('offline')}})
  assert.equal(await b.startup(),null);assert.equal(await b.startup(),null)
  assert.equal(failures,1)
  assert.equal((await new UpdateNotifications(f.options).startup()).version,'2.0.7')
})
test('old releases never prompt and highlights are bounded plain text',async t=>{
  const f=fixture(t);f.value={version:'2.0.5',notes:'1. ignored'}
  assert.equal(await new UpdateNotifications(f.options).startup(),null)
  const result=highlights('## title\n1. **Readable** [notes](https://example.org)\n'+Array(8).fill('- '+ '长'.repeat(200)).join('\n'))
  assert.equal(result.length,5);assert.equal(result[0],'Readable notes');assert.equal(result[1].length,150)
})
