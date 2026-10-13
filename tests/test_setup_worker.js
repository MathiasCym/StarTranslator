const { test } = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs/promises'), path = require('node:path')
const { workerArguments, directoryNeedsElevation, launchWorker, workerOutcome } = require('../lib/setup-worker')

test('install and uninstall keep scope and Unicode paths across elevation', () => {
  const input = { directory: "D:\\软件与资料\\Mathias' test\\StarTranslator", scope: 'all', statusFile: 'C:\\Temp folder\\安装状态.txt' }
  const calls = []
  for (const uninstall of [false, true]) {
    const args = workerArguments({ ...input, uninstall })
    assert.equal(args.at(-1), (uninstall ? '_?=' : '/D=') + input.directory)
    assert.equal(args[1], '/allusers')
    launchWorker({ worker: "C:\\Users\\Mathias' test\\Setup.exe", args, elevate: true, spawnProcess: (...values) => calls.push(values) })
  }
  for (const [exe, args, options] of calls) {
    assert.match(exe, /powershell\.exe$/i)
    const script = Buffer.from(args.at(-1), 'base64').toString('utf16le')
    assert.match(script, /-Verb RunAs/)
    assert.match(script, /-PassThru -Wait/)
    assert.match(script, /STAR_STATUS="C:\\Temp folder\\安装状态\.txt"/)
    assert.match(script, /Mathias'' test/)
    assert.equal(options.windowsHide, true)
  }
  assert.throws(() => workerArguments({ ...input, directory: 'D:\\bad"path' }), /无效/)
})

test('a writable parent permits a new folder without elevation and leaves no probe files', async t => {
  const root = await fs.mkdtemp(path.join(__dirname, '.setup-write-'))
  t.after(async () => { assert.equal(path.dirname(root), __dirname); await fs.rm(root, { recursive: true, force: true }) })
  assert.equal(await directoryNeedsElevation(path.join(root, 'new folder', 'StarTranslator')), false)
  assert.deepEqual(await fs.readdir(root), [])
})

test('write access denial requests elevation, while storage faults are not misreported as permission', async () => {
  const denied = Object.assign(new Error('Denied by ACL'), { code: 'EACCES' })
  const full = Object.assign(new Error('Disk full'), { code: 'ENOSPC' })
  const io = { stat: async () => ({ isDirectory: () => true }), open: async () => { throw denied } }
  assert.equal(await directoryNeedsElevation('C:\\protected\\StarTranslator', io), true)
  io.open = async () => { throw full }
  await assert.rejects(directoryNeedsElevation('C:\\full\\StarTranslator', io), error => error === full)
})

test('cancelled or unfinished upgrades never claim success just because the old executable exists', () => {
  const existing = { executableExists: true, uninstall: false }
  assert.equal(workerOutcome({ ...existing, code: 0, phase: 'checking' }).complete, false)
  assert.match(workerOutcome({ ...existing, code: 1223, phase: 'checking' }).message, /授权已取消/)
  assert.match(workerOutcome({ ...existing, code: 0, phase: 'error:1619' }).message, /仍在运行/)
  assert.match(workerOutcome({ ...existing, code: 2, phase: 'files' }).message, /旧版本移除失败/)
  assert.equal(workerOutcome({ ...existing, code: 0, phase: 'complete' }).complete, true)
  assert.equal(workerOutcome({ code: 0, phase: 'complete', uninstall: true, executableExists: true }).complete, false)
  assert.equal(workerOutcome({ code: 0, phase: 'complete', uninstall: true, executableExists: false }).complete, true)
})

test('ordinary current-user installs use the direct worker without changing the user token', () => {
  const args = workerArguments({ directory: 'C:\\Programs\\StarTranslator', statusFile: 'C:\\Temp\\status.txt', scope: 'current' })
  let call
  launchWorker({ worker: 'C:\\Setup.exe', args, elevate: false, spawnProcess: (...values) => { call = values } })
  assert.equal(call[0], 'C:\\Setup.exe')
  assert.equal(call[1][1], '/currentuser')
  assert.equal(call[2].windowsVerbatimArguments, true)
})
