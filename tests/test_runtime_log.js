const test = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs'), os = require('node:os'), path = require('node:path')
const { spawn } = require('node:child_process')
const { createLogger } = require('../lib/runtime-log')

test('backend diagnostics survive a closed stderr receiver', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'star-log-'))
  const file = path.join(folder, 'logs', 'runtime.log')
  const source = `const log=require(process.argv[1]).createLogger(process.argv[2]);
    process.stdout.write('ready');
    process.stdin.once('data',()=>{for(let i=0;i<25;i++)log.error('[backend]', 'request completed', i);process.stdin.destroy();});`
  const child = spawn(process.execPath, ['-e', source, require.resolve('../lib/runtime-log'), file],
    { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  try {
    const finished = new Promise((resolve, reject) => {
      child.on('error', reject)
      child.on('close', (code, signal) => resolve({ code, signal }))
    })
    await new Promise((resolve, reject) => {
      child.stdout.once('data', () => {
        child.stderr.destroy()
        child.stdin.end('receiver closed')
        resolve()
      })
      child.on('error', reject)
    })
    assert.deepEqual(await finished, { code: 0, signal: null })
    const text = fs.readFileSync(file, 'utf8')
    assert.equal(text.trim().split('\n').length, 25)
    assert.match(text, /\[ERROR\] \[backend\] request completed 24/)
  } finally { fs.rmSync(folder, { recursive: true, force: true }) }
})

test('an unavailable diagnostic file does not break application work', () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'star-log-unavailable-'))
  try {
    const blocked = path.join(folder, 'file')
    fs.writeFileSync(blocked, 'existing file')
    const log = createLogger(path.join(blocked, 'runtime.log'))
    assert.doesNotThrow(() => log.error(new Error('backend failed')))
    assert.equal(fs.readFileSync(blocked, 'utf8'), 'existing file')
  } finally { fs.rmSync(folder, { recursive: true, force: true }) }
})
