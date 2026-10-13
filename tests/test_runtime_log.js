const test = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs'), os = require('node:os'), path = require('node:path')
const { spawn } = require('node:child_process')
const { createLogger, installDiagnosticConsole } = require('../lib/runtime-log')
const { EventEmitter } = require('node:events')

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

test('console-based IPC diagnostics survive closed stdout and stderr without losing error details', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'star-console-log-'))
  const file = path.join(folder, 'runtime.log')
  const source = `const {createLogger,installDiagnosticConsole}=require(process.argv[1]);
    installDiagnosticConsole(createLogger(process.argv[2]));process.stdout.write('ready');
    process.stdin.once('data',()=>{console.error("Error occurred in handler for 'open-shared-service':",new Error('invalid shared address'));console.warn('port rejected');console.info('still running');process.stdin.destroy()});`
  const child = spawn(process.execPath, ['-e', source, require.resolve('../lib/runtime-log'), file], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  try {
    const finished = new Promise((resolve, reject) => { child.on('error', reject); child.on('close', (code, signal) => resolve({ code, signal })) })
    await new Promise((resolve, reject) => { child.stdout.once('data', () => { child.stderr.destroy(); child.stdout.destroy(); child.stdin.end('closed'); resolve() }); child.on('error', reject) })
    assert.deepEqual(await finished, { code: 0, signal: null })
    const text = fs.readFileSync(file, 'utf8')
    assert.match(text, /open-shared-service.*Error: invalid shared address/)
    assert.match(text, /\[ERROR\] port rejected/); assert.match(text, /\[INFO\] still running/)
  } finally { fs.rmSync(folder, { recursive: true, force: true }) }
})

test('only a broken standard-output pipe is tolerated; unrelated stream faults still throw', () => {
  const stream = new EventEmitter(), records = [], target = { error() {}, warn() {}, info() {}, log() {}, debug() {} }, original = target.error
  const restore = installDiagnosticConsole({ error: (...values) => records.push(values), info: (...values) => records.push(values) }, { target, streams: [stream] })
  const broken = Object.assign(new Error('receiver closed'), { code: 'EPIPE' }), unexpected = Object.assign(new Error('disk failed'), { code: 'EIO' })
  try {
    assert.doesNotThrow(() => stream.emit('error', broken)); assert.equal(records[0][1], broken)
    assert.throws(() => stream.emit('error', unexpected), error => error === unexpected)
    target.error('original diagnostic'); assert.deepEqual(records[1], ['original diagnostic'])
  } finally { restore() }
  assert.equal(target.error, original); assert.equal(stream.listenerCount('error'), 0)
})
