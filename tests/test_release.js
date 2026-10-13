const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { bumpVersion, prepareRelease, buildRelease } = require('../tools/release')

function fixture(t, version = '1.1.0') {
  const root = fs.mkdtempSync(path.join(__dirname, '.release-test-'))
  t.after(() => {
    // 递归清理前核对路径，测试只能清理自身创建的目录。
    assert.equal(path.dirname(path.resolve(root)), path.resolve(__dirname))
    assert.ok(path.basename(root).startsWith('.release-test-'))
    fs.rmSync(root, { recursive: true, force: true })
  })
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({
    name: 'fixture', version,
    build: { productName: 'NovaTerm Checker', directories: { output: 'dist' } },
  }))
  fs.writeFileSync(path.join(root, 'package-lock.json'), JSON.stringify({
    version: '1.0.0', packages: { '': { version: '1.0.0' }, 'node_modules/example': { version: '1.0.0' } },
  }))
  fs.mkdirSync(path.join(root, 'dist'))
  return root
}

function load(root, name) { return JSON.parse(fs.readFileSync(path.join(root, name), 'utf8')) }
function fakeBuilder(release) { fs.writeFileSync(release.installer, `installer ${release.version}`) }

test('patch, minor and major reset the appropriate digits', () => {
  assert.equal(bumpVersion('1.2.9', 'patch'), '1.2.10')
  assert.equal(bumpVersion('1.2.9', 'minor'), '1.3.0')
  assert.equal(bumpVersion('1.2.9', 'major'), '2.0.0')
  assert.throws(() => bumpVersion('1.0.0-beta', 'patch'))
  assert.throws(() => bumpVersion('1.0.65535', 'patch'))
})

test('an unpublished version is retained and only project lock versions are synchronized', t => {
  const root = fixture(t)
  const release = prepareRelease(root, 'auto', '显示运行版本')
  assert.equal(release.version, '1.1.0')
  assert.equal(load(root, 'package.json').version, '1.1.0')
  const lock = load(root, 'package-lock.json')
  assert.equal(lock.version, '1.1.0')
  assert.equal(lock.packages[''].version, '1.1.0')
  assert.equal(lock.packages['node_modules/example'].version, '1.0.0')
  assert.match(fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8'), /显示运行版本/)
})

test('successive builds receive different versions and preserve old installers', t => {
  const root = fixture(t)
  const first = buildRelease(root, 'auto', '首个版本', fakeBuilder)
  const firstPath = path.join(root, first.installer)
  const firstBytes = fs.readFileSync(firstPath)
  const second = buildRelease(root, 'auto', '后续修复', fakeBuilder)
  assert.equal(first.version, '1.1.0')
  assert.equal(second.version, '1.1.1')
  assert.deepEqual(fs.readFileSync(firstPath), firstBytes)
  assert.equal(load(root, 'release-history.json').length, 2)
  assert.match(second.sha256, /^[a-f0-9]{64}$/)
  assert.equal(second.size, fs.statSync(path.join(root, second.installer)).size)
  const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8')
  assert.ok(changelog.indexOf('[1.1.1]') < changelog.indexOf('[1.1.0]'))
  assert.match(changelog, /后续修复/)
})

test('archived installer history still prevents a version from being reused', t => {
  const root = fixture(t)
  fs.writeFileSync(path.join(root, 'release-history.json'), JSON.stringify([{ version: '1.1.0' }]))
  const release = prepareRelease(root)
  assert.equal(release.version, '1.1.1')
})

test('explicit feature release advances the minor version', t => {
  const root = fixture(t, '1.1.9')
  assert.equal(prepareRelease(root, 'minor').version, '1.2.0')
})

test('failed builds never receive a successful release record or overwrite the prior installer', t => {
  const root = fixture(t)
  const old = path.join(root, 'dist', 'NovaTerm Checker Setup 1.1.0.exe')
  fs.writeFileSync(old, 'existing installer')
  assert.throws(() => buildRelease(root, 'auto', '修复', () => { throw new Error('build failed') }), /build failed/)
  assert.equal(fs.existsSync(path.join(root, 'release-history.json')), false)
  assert.equal(fs.readFileSync(old, 'utf8'), 'existing installer')
})

test('a manually downgraded project is rejected before files are changed', t => {
  const root = fixture(t)
  fs.writeFileSync(path.join(root, 'release-history.json'), JSON.stringify([{ version: '2.0.0' }]))
  assert.throws(() => prepareRelease(root), /低于已发布版本/)
  assert.equal(load(root, 'package.json').version, '1.1.0')
})
