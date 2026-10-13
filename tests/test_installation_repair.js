const { test } = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs/promises'), path = require('node:path'), crypto = require('node:crypto')
const { createManifest, verifyInstallation, MANIFEST } = require('../lib/install-integrity')
const { checkAndRepair, RECOVERY_DATA, RECOVERY_INDEX } = require('../lib/installation-repair')
const { buildComponentRecovery } = require('../tools/build-component-recovery')
const VERSION = '1.8.5'
async function fixture(t) {
  const root = await fs.mkdtemp(path.join(__dirname, '.repair-runtime-'))
  t.after(async () => { assert.equal(path.dirname(root), __dirname); await fs.rm(root, { recursive: true, force: true }) })
  const files = ['星译官.exe', 'resources/app.asar', 'resources/officecli/officecli.exe', 'resources/python-runtime/python.exe', 'resources/python-runtime/python311.dll', 'resources/app.asar.unpacked/backend/server.py', 'resources/python-runtime/Lib/site-packages/flask/__init__.py', 'resources/python-runtime/Lib/site-packages/flask/__pycache__/__init__.cpython-311.pyc']
  for (const relative of files) { const file = path.join(root, relative); await fs.mkdir(path.dirname(file), { recursive: true }); await fs.writeFile(file, 'Original component contents: ' + relative) }
  const userFile = path.join(root, 'personal-documents', 'My draft.docx')
  await fs.mkdir(path.dirname(userFile)); await fs.writeFile(userFile, 'PERSONAL DOCUMENT')
  const bundle = await buildComponentRecovery(root, VERSION)
  const manifest = await createManifest(root, VERSION)
  await fs.writeFile(path.join(root, MANIFEST), JSON.stringify(manifest))
  return { root, manifest, bundle, userFile, run: options => checkAndRepair({ root, version: VERSION, ...options }) }
}
test('runtime ignores rewritten Python caches, leaves healthy components and personal files intact', async t => {
  const { root, run, userFile } = await fixture(t), file = path.join(root, 'resources/officecli/officecli.exe')
  const before = (await fs.stat(file)).mtimeMs
  await fs.writeFile(path.join(root, 'resources/python-runtime/Lib/site-packages/flask/__pycache__/__init__.cpython-311.pyc'), 'Runtime cache changed')
  const result = await run({ beforeRepair: () => { throw Error('Should not repair') } })
  assert.equal(result.complete, true); assert.equal(result.skipped, 1); assert.deepEqual(result.repaired, [])
  assert.equal((await fs.stat(file)).mtimeMs, before); assert.equal(await fs.readFile(userFile, 'utf8'), 'PERSONAL DOCUMENT')
})
test('missing OfficeCLI and same-size Python corruption are automatically restored, then fully rechecked', async t => {
  const { root, run, manifest, userFile } = await fixture(t), stages = [], hooks = []
  const office = 'resources/officecli/officecli.exe', python = 'resources/python-runtime/Lib/site-packages/flask/__init__.py'
  await fs.unlink(path.join(root, office))
  const bytes = await fs.readFile(path.join(root, python)); bytes[0] ^= 1; await fs.writeFile(path.join(root, python), bytes)
  const result = await run({ progress: value => stages.push(value), beforeRepair: async () => hooks.push('before'), afterRepair: async () => hooks.push('after') })
  assert.equal(result.complete, true); assert.deepEqual(new Set(result.repaired), new Set([office, python])); assert.deepEqual(hooks, ['before', 'after'])
  assert(stages.some(s => s.phase === 'repairing')); assert(stages.some(s => s.phase === 'rechecking' && s.percent === 100))
  assert.equal((await verifyInstallation(root, manifest, VERSION)).complete, true)
  assert.equal(await fs.readFile(userFile, 'utf8'), 'PERSONAL DOCUMENT')
  assert(!(await fs.readdir(path.join(root, 'resources/officecli'))).some(name => name.includes('.star-repair-')))
})
test('a missing entire runtime directory can be recovered without depending on Python', async t => {
  const { root, run } = await fixture(t)
  const target = path.resolve(root, 'resources/python-runtime')
  assert.equal(path.relative(root, target), path.join('resources', 'python-runtime'))
  await fs.rm(target, { recursive: true })
  const result = await run()
  assert.equal(result.complete, true); assert.equal(result.repaired.length, 3)
})
test('a broken recovery archive is never used for writing components', async t => {
  const { root, run } = await fixture(t), office = path.join(root, 'resources/officecli/officecli.exe'), bundle = path.join(root, RECOVERY_DATA)
  await fs.unlink(office)
  const bytes = await fs.readFile(bundle); bytes[5] ^= 1; await fs.writeFile(bundle, bytes)
  const result = await run({ beforeRepair: () => { throw Error('Should not pause service') } })
  assert.equal(result.complete, false); assert.equal(result.repaired.length, 0); assert.match(result.repairErrors[0].reason, /修复副本.*损坏/)
  await assert.rejects(fs.stat(office), { code: 'ENOENT' })
})
test('unsupported core corruption remains visible and never claims repair success', async t => {
  const { root, run } = await fixture(t)
  await fs.writeFile(path.join(root, 'resources/app.asar'), 'Broken core')
  const result = await run(); assert.equal(result.complete, false); assert.deepEqual(result.repaired, [])
  assert.equal(result.failures[0].path, 'resources/app.asar'); assert.match(result.message, /重新安装/)
})
test('a directory occupying a filename is preserved and repair reports failure', async t => {
  const { root, run } = await fixture(t), target = path.join(root, 'resources/officecli/officecli.exe')
  await fs.unlink(target); await fs.mkdir(target); await fs.writeFile(path.join(target, 'keep.txt'), 'keep')
  const result = await run(); assert.equal(result.complete, false); assert.match(result.repairErrors[0].reason, /不是程序文件/)
  assert.equal(await fs.readFile(path.join(target, 'keep.txt'), 'utf8'), 'keep')
})
test('unsafe or wrong-version manifests cannot restore files', async t => {
  const { root, manifest, run } = await fixture(t)
  for (const invalid of [{ ...manifest, version: '0.0.0' }, { ...manifest, files: [...manifest.files, { path: '../outside', size: 1, sha256: 'a'.repeat(64) }] }, { ...manifest, files: [...manifest.files, manifest.files[0]] }]) {
    await fs.writeFile(path.join(root, MANIFEST), JSON.stringify(invalid)); await assert.rejects(run(), /无效|不匹配/)
  }
})
test('out of bounds recovery metadata is rejected even if its outer checksum matches', async t => {
  const { root, manifest, run } = await fixture(t), indexPath = path.join(root, RECOVERY_INDEX)
  const index = JSON.parse(await fs.readFile(indexPath)); index.files[0].offset = Number.MAX_SAFE_INTEGER
  const bytes = Buffer.from(JSON.stringify(index)); await fs.writeFile(indexPath, bytes)
  const expected = manifest.files.find(f => f.path === RECOVERY_INDEX); expected.size = bytes.length; expected.sha256 = crypto.createHash('sha256').update(bytes).digest('hex')
  await fs.writeFile(path.join(root, MANIFEST), JSON.stringify(manifest)); await fs.unlink(path.join(root, 'resources/officecli/officecli.exe'))
  const result = await run(); assert.equal(result.complete, false); assert.equal(result.repaired.length, 0); assert.match(result.repairErrors[0].reason, /清单无效/)
})
test('a pending report can prevent a required service restart without losing files or faking success', async t => {
  const { root, run } = await fixture(t), file = path.join(root, 'resources/python-runtime/python.exe')
  await fs.unlink(file)
  const result = await run({ beforeRepair: async () => { throw Error('当前报告仍在处理') }, afterRepair: () => { throw Error('Should not restart') } })
  assert.equal(result.complete, false); assert.equal(result.repaired.length, 0); assert.match(result.repairErrors[0].reason, /报告/)
  await assert.rejects(fs.stat(file), { code: 'ENOENT' })
})
test('write permission or locking failure preserves the old file and cleans temporary repair data', async t => {
  const { root, run } = await fixture(t), file = path.join(root, 'resources/officecli/officecli.exe')
  await fs.writeFile(file, 'Corrupted original still present')
  const originalRename = fs.rename
  fs.rename = async (source, destination) => {
    if (destination === file) throw Object.assign(new Error('Synthetic write denial'), { code: 'EPERM' })
    return originalRename(source, destination)
  }
  let result
  try { result = await run() } finally { fs.rename = originalRename }
  assert.equal(result.complete, false); assert.equal(result.repaired.length, 0); assert.match(result.repairErrors[0].reason, /被占用|无写入权限/)
  assert.equal(await fs.readFile(file, 'utf8'), 'Corrupted original still present')
  assert(!(await fs.readdir(path.dirname(file))).some(name => name.includes('.star-repair-')))
})
test('junctions to another directory are never followed to overwrite files', async t => {
  const { root, run } = await fixture(t), directory = path.join(root, 'resources/officecli')
  const outside = await fs.mkdtemp(path.join(__dirname, '.outside-repair-'))
  t.after(async () => { assert.equal(path.dirname(outside), __dirname); await fs.rm(outside, { recursive: true, force: true }) })
  await fs.writeFile(path.join(outside, 'officecli.exe'), 'EXTERNAL FILE')
  await fs.rename(directory, directory + '-original'); await fs.symlink(outside, directory, 'junction')
  const result = await run(); assert.equal(result.complete, false); assert.equal(result.repaired.length, 0)
  assert.match(result.repairErrors[0].reason, /链接/); assert.equal(await fs.readFile(path.join(outside, 'officecli.exe'), 'utf8'), 'EXTERNAL FILE')
})
test('files restored but backend restart failed is reported as incomplete service recovery', async t => {
  const { root, run } = await fixture(t)
  await fs.unlink(path.join(root, 'resources/python-runtime/python.exe'))
  const result = await run({ afterRepair: async () => { throw Error('Synthetic service start failure') } })
  assert.equal(result.filesComplete, true); assert.equal(result.complete, false); assert.equal(result.repaired.length, 1)
  assert.match(result.serviceError, /service start failure/); assert.match(result.message, /本地服务未恢复/)
})
