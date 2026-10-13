// 打包入口：同步版本、保留旧包，并记录成功生成的安装包。
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { spawnSync } = require('node:child_process')

function parts(version) {
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version)) {
    throw new Error(`版本号必须是 主版本.功能版本.修订版本：${version}`)
  }
  const values = version.split('.').map(Number)
  if (values.some(value => !Number.isSafeInteger(value) || value > 65535)) {
    throw new Error('Windows 版本号的每一位必须介于 0 和 65535 之间')
  }
  return values
}

function bumpVersion(version, kind) {
  const numbers = parts(version)
  const index = { major: 0, minor: 1, patch: 2 }[kind]
  if (index === undefined) throw new Error('升级类型必须是 patch、minor 或 major')
  numbers[index]++
  numbers.fill(0, index + 1)
  const next = numbers.join('.')
  parts(next)
  return next
}

function readJson(file) { return JSON.parse(fs.readFileSync(file, 'utf8')) }
function writeJson(file, value) { fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n') }
function dateString(date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-')
}

function prepareRelease(root, kind = 'auto', note = '', now = new Date()) {
  const pkgPath = path.join(root, 'package.json')
  const lockPath = path.join(root, 'package-lock.json')
  const pkg = readJson(pkgPath)
  const lock = readJson(lockPath)
  if (!lock.packages || !lock.packages['']) throw new Error('package-lock.json 缺少项目记录')
  const historyPath = path.join(root, 'release-history.json')
  const history = fs.existsSync(historyPath) ? readJson(historyPath) : []
  if (!Array.isArray(history)) throw new Error('发布记录格式不正确')
  const output = path.resolve(root, pkg.build.directories.output)
  const installerFor = version => path.join(output, `${pkg.build.productName} Setup ${version}.exe`)
  const used = version => history.some(item => item.version === version) || fs.existsSync(installerFor(version))
  let version = pkg.version
  parts(version)
  if (kind !== 'auto') version = bumpVersion(version, kind)
  // 当前版本已有安装包时，自动递增，绝不覆盖该版本的旧安装包。
  while (used(version)) version = bumpVersion(version, 'patch')
  for (const item of history) {
    const previous = parts(item.version)
    const current = parts(version)
    const firstDifference = current.findIndex((value, index) => value !== previous[index])
    if (firstDifference >= 0 && current[firstDifference] < previous[firstDifference]) {
      throw new Error(`当前版本低于已发布版本 ${item.version}，请先修正项目版本`)
    }
  }

  const changelogPath = path.join(root, 'CHANGELOG.md')
  let changelog = fs.existsSync(changelogPath) ? fs.readFileSync(changelogPath, 'utf8') : '# 更新记录\n'
  const marker = `## [${version}]`
  if (!changelog.includes(marker)) {
    const summary = note.trim() || '按当前源码生成新的安装包；具体功能说明请在发布前补充。'
    const entry = `${marker} - ${dateString(now)}\n\n- ${summary.replace(/\r?\n/g, '\n- ')}\n\n`
    const heading = changelog.indexOf('\n')
    changelog = heading < 0 ? `${changelog}\n\n${entry}` : `${changelog.slice(0, heading + 1)}\n${entry}${changelog.slice(heading + 1).trimStart()}`
  }
  pkg.version = version
  lock.version = version
  lock.packages[''].version = version
  writeJson(pkgPath, pkg)
  writeJson(lockPath, lock)
  fs.writeFileSync(changelogPath, changelog)
  return { root, version, installer: installerFor(version), historyPath, history }
}

function recordRelease(release, now = new Date()) {
  const bytes = fs.readFileSync(release.installer)
  if (!bytes.length) throw new Error('安装包为空，不能登记为成功发布')
  const record = {
    version: release.version,
    builtAt: now.toISOString(),
    installer: path.relative(release.root, release.installer).replace(/\\/g, '/'),
    size: bytes.length,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
  }
  writeJson(release.historyPath, [...release.history, record])
  return record
}

function buildRelease(root, kind = 'auto', note = '', builder) {
  const release = prepareRelease(root, kind, note)
  console.log(`[release] 准备生成 v${release.version}`)
  const runBuilder = builder || (() => {
    const cli = path.join(root, 'node_modules', 'electron-builder', 'cli.js')
    const result = spawnSync(process.execPath, ['--require', path.join(root, 'tools', 'nsis-timeout.js'), cli, '--win', 'nsis', '--x64'], {
      cwd: root, stdio: 'inherit', windowsHide: true,
    })
    if (result.error) throw result.error
    if (result.status !== 0) throw new Error(`打包失败（退出码 ${result.status}），未登记为成功发布`)
  })
  runBuilder(release)
  const record = recordRelease(release)
  console.log(`[release] 已生成 v${record.version}：${record.installer}`)
  return record
}

function main() {
  const args = process.argv.slice(2)
  const kind = args[0] && !args[0].startsWith('--') ? args.shift() : 'auto'
  if (!['auto', 'patch', 'minor', 'major'].includes(kind)) throw new Error('未知升级类型')
  let note = ''
  if (args.length) {
    if (args.length !== 2 || args[0] !== '--note' || !args[1].trim()) {
      throw new Error('用法：npm run dist -- --note "本次更新说明"')
    }
    note = args[1]
  }
  buildRelease(path.resolve(__dirname, '..'), kind, note)
}

module.exports = { bumpVersion, prepareRelease, recordRelease, buildRelease }
if (require.main === module) {
  try { main() }
  catch (error) { console.error(`[release] ${error.message}`); process.exitCode = 1 }
}
