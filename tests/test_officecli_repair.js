const { test } = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs/promises'), path = require('node:path'), crypto = require('node:crypto'), { execFile } = require('node:child_process'), { promisify } = require('node:util')
const execute = promisify(execFile), root = path.resolve(__dirname, '..')
const bundle = path.join(root, 'dist/StarTranslator-1.8.5-OfficeCLI-Repair')
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex')
async function fixture(version = '1.8.5') {
  const directory = path.join(root, 'dist/qa/officecli-repair', crypto.randomUUID())
  await fs.mkdir(path.join(directory, 'resources'), { recursive: true })
  const pinned = JSON.parse(await fs.readFile(path.join(bundle, 'repair-manifest.json'), 'utf8'))
  const files = [{ path: 'resources/officecli/officecli.exe', size: pinned.size, sha256: pinned.sha256 }]
  for (const relative of ['星译官.exe', 'resources/app.asar']) {
    const bytes = Buffer.from('synthetic immutable program fixture ' + relative)
    await fs.writeFile(path.join(directory, relative), bytes)
    files.push({ path: relative, size: bytes.length, sha256: hash(bytes) })
  }
  await fs.writeFile(path.join(directory, 'resources/install-manifest.json'), JSON.stringify({ schema: 1, version, files }))
  await fs.writeFile(path.join(directory, 'sample.docx'), 'unchanged document fixture')
  return { directory, pinned, component: path.join(directory, 'resources/officecli/officecli.exe') }
}
async function run(directory, source = bundle) {
  try { const result = await execute('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', path.join(source, 'Repair-OfficeCLI.ps1'), '-InstallDirectory', directory, '-NoPause'], { windowsHide: true, timeout: 45000, maxBuffer: 100000 }); return { code: 0, ...result } }
  catch (error) { return { code: error.code, stdout: error.stdout, stderr: error.stderr } }
}
test('missing component is repaired and really starts; existing correct component is not rewritten', async () => {
  const f = await fixture(), coreBefore = await fs.readFile(path.join(f.directory, 'resources/app.asar'))
  const first = await run(f.directory)
  assert.equal(first.code, 0, first.stdout + first.stderr)
  assert.equal(hash(await fs.readFile(f.component)), f.pinned.sha256)
  assert.deepEqual(await fs.readFile(path.join(f.directory, 'resources/app.asar')), coreBefore)
  assert.equal(await fs.readFile(path.join(f.directory, 'sample.docx'), 'utf8'), 'unchanged document fixture')
  const modified = (await fs.stat(f.component)).mtimeMs
  const second = await run(f.directory)
  assert.equal(second.code, 0, second.stdout + second.stderr)
  assert.equal((await fs.stat(f.component)).mtimeMs, modified)
  assert.deepEqual(await fs.readdir(path.dirname(f.component)), ['officecli.exe'])
})
test('wrong application version refuses to replace even an existing damaged component', async () => {
  const f = await fixture('1.8.4'); await fs.mkdir(path.dirname(f.component), { recursive: true }); await fs.writeFile(f.component, 'old fixture')
  const result = await run(f.directory); assert.notEqual(result.code, 0)
  assert.equal(await fs.readFile(f.component, 'utf8'), 'old fixture')
})
test('same-size app archive corruption refuses component-only repair', async () => {
  const f = await fixture(), file = path.join(f.directory, 'resources/app.asar'), bytes = await fs.readFile(file)
  bytes[0] ^= 1; await fs.writeFile(file, bytes)
  assert.notEqual((await run(f.directory)).code, 0)
  await assert.rejects(fs.stat(f.component), { code: 'ENOENT' })
  assert.deepEqual(await fs.readFile(file), bytes)
})
test('corrupt repair payload is rejected before the installation is modified', async () => {
  const f = await fixture(), bad = path.join(f.directory, 'bad-repair-package'); await fs.mkdir(bad)
  for (const name of ['Repair-OfficeCLI.ps1', 'repair-manifest.json']) await fs.copyFile(path.join(bundle, name), path.join(bad, name))
  await fs.writeFile(path.join(bad, 'officecli.exe'), 'untrusted broken fixture')
  assert.notEqual((await run(f.directory, bad)).code, 0)
  await assert.rejects(fs.stat(f.component), { code: 'ENOENT' })
})
test('a directory occupying the component filename is rejected without writing into it', async () => {
  const f = await fixture(); await fs.mkdir(f.component, { recursive: true })
  assert.notEqual((await run(f.directory)).code, 0)
  assert.deepEqual(await fs.readdir(f.component), [])
})
