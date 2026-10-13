const { test } = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs/promises'), path = require('node:path')
const { createManifest, verifyInstallation } = require('../lib/install-integrity')
const { buildDiagnostics, taskMetadata } = require('../lib/diagnostics')
async function payload(t) {
  const root = await fs.mkdtemp(path.join(__dirname, '.integrity-'))
  t.after(async () => { assert.equal(path.dirname(root), __dirname); await fs.rm(root, { recursive: true, force: true }) })
  const files = ['星译官.exe', 'resources/app.asar', 'resources/officecli/officecli.exe', 'resources/python-runtime/python.exe', 'resources/python-runtime/python311.dll', 'resources/app.asar.unpacked/backend/server.py', 'resources/python-runtime/Lib/site-packages/flask/__init__.py']
  for (const file of files) { const target = path.join(root, file); await fs.mkdir(path.dirname(target), { recursive: true }); await fs.writeFile(target, 'verified synthetic contents') }
  return { root, manifest: await createManifest(root, '1.8.5') }
}
test('all delivered files pass and progress reaches the full file count', async t => {
  const { root, manifest } = await payload(t), progress = []
  const result = await verifyInstallation(root, manifest, '1.8.5', (n, total) => progress.push([n, total]))
  assert.equal(result.complete, true); assert.equal(result.checked, 7)
  assert.deepEqual(progress.at(-1), [7, 7])
})
test('an existing app executable does not hide a missing OfficeCLI', async t => {
  const { root, manifest } = await payload(t)
  await fs.unlink(path.join(root, 'resources/officecli/officecli.exe'))
  const result = await verifyInstallation(root, manifest, '1.8.5')
  assert.equal(result.complete, false); assert.match(result.message, /officecli.exe（文件缺失）/)
})
test('same-size corruption of a Python dependency fails full integrity check', async t => {
  const { root, manifest } = await payload(t)
  const file = path.join(root, manifest.files.find(f => f.path.endsWith('flask/__init__.py')).path)
  const bytes = await fs.readFile(file); bytes[0] ^= 1; await fs.writeFile(file, bytes)
  const result = await verifyInstallation(root, manifest, '1.8.5')
  assert.equal(result.complete, false); assert.match(result.message, /flask.*内容与安装包不一致/)
})
test('wrong version, incomplete checklists and path escapes never pass', async t => {
  const { root, manifest } = await payload(t)
  await assert.rejects(verifyInstallation(root, manifest, '1.8.4'), /版本不匹配/)
  await assert.rejects(verifyInstallation(root, { ...manifest, files: manifest.files.slice(0, 1) }, '1.8.5'), /缺少必要组件/)
  await assert.rejects(verifyInstallation(root, { ...manifest, files: [...manifest.files, { path: '../outside.txt', size: 0, sha256: 'a'.repeat(64) }] }, '1.8.5'), /无效路径/)
})
test('export includes environment, missing components and recent errors without model credentials or report text', async t => {
  const { root } = await payload(t), userData = path.join(root, 'profile')
  await fs.mkdir(path.join(userData, 'logs'), { recursive: true })
  await fs.writeFile(path.join(userData, 'model-settings.json'), JSON.stringify({ api_key: 'personal-secret-123', profiles: [{ api_key: 'second-secret-789' }] }))
  await fs.writeFile(path.join(userData, 'logs/runtime.log'), 'Authorization: Bearer unlisted-token\nconfigured personal-secret-123 second-secret-789\nError code 5')
  await fs.unlink(path.join(root, 'resources/officecli/officecli.exe'))
  const task = { id: 'job', status: 'failed', error: '启动失败', errors: [{ path: 'sample.pptx', error: '组件无法启动' }], report: { segments: ['PRIVATE DOCUMENT TEXT'] }, api_key: 'do-not-export' }
  const report = await buildDiagnostics({ version: '1.8.5', resources: path.join(root, 'resources'), userData, task })
  assert.match(report, /ENOENT/); assert.match(report, /Error code 5/); assert.match(report, /sample.pptx/)
  for (const secret of ['personal-secret-123', 'second-secret-789', 'unlisted-token', 'PRIVATE DOCUMENT TEXT', 'do-not-export']) assert(!report.includes(secret), secret)
  assert(!('report' in taskMetadata(task)))
})
