const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')
const { MANIFEST, verifyInstallation } = require('../lib/install-integrity')

function existingDirectory(parent, name) {
  const folder = path.join(parent, name)
  try {
    const entry = fs.lstatSync(folder)
    if (!entry.isDirectory() || fs.realpathSync(folder) !== folder) {
      throw Error(`预览构建目录无效：${folder}`)
    }
    return folder
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
    return null
  }
}

function publishPreview(channel, staging) {
  const current = path.join(channel, 'win-unpacked')
  const candidate = existingDirectory(staging, 'win-unpacked')
  if (!candidate) throw Error('未找到待替换的测试版。')

  const previous = path.join(staging, 'previous')
  if (existingDirectory(channel, 'win-unpacked')) {
    try {
      fs.renameSync(current, previous)
    } catch (error) {
      if (['EBUSY', 'EPERM', 'EACCES'].includes(error.code)) {
        throw Error('暂时无法替换本地测试版。请关闭正在运行的测试版后重新构建。', { cause: error })
      }
      throw error
    }
  }
  try {
    fs.renameSync(candidate, current)
  } catch (error) {
    if (!fs.existsSync(current) && existingDirectory(staging, 'previous')) {
      fs.renameSync(previous, current)
    }
    throw error
  }
  return current
}

async function main() {
  const { build, Platform, Arch } = require('electron-builder')
  const root = path.resolve(__dirname, '..')
  const previewDirectory = path.join(root, 'dist', 'ui-preview')
  fs.mkdirSync(previewDirectory, { recursive: true })
  const channel = fs.realpathSync(previewDirectory)
  const runGit = args => execFileSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true }).trim()
  const source = { branch: process.env.GITHUB_HEAD_REF || process.env.GITHUB_REF_NAME || runGit(['branch', '--show-current']), commit: runGit(['rev-parse', 'HEAD']), localChanges: Boolean(runGit(['status', '--porcelain'])) }
  const staging = fs.mkdtempSync(path.join(channel, '.build-'))
  try {
    require('./build-patch-helper.cjs').build()
    await build({
      projectDir: root,
      targets: Platform.WINDOWS.createTarget(['dir'], Arch.x64),
      publish: 'never',
      config: {
        directories: { output: staging },
        extraMetadata: { starPreview: true },
        electronDist: path.join(root, 'node_modules', 'electron', 'dist'),
      },
    })
    const candidate = existingDirectory(staging, 'win-unpacked')
    if (!candidate) throw Error('未找到构建后的测试版。')
    const { build: { productName }, version } = require('../package.json')
    const manifest = JSON.parse(fs.readFileSync(path.join(candidate, MANIFEST), 'utf8'))
    const checked = await verifyInstallation(candidate, manifest, version)
    if (!checked.complete) throw Error(checked.message)
    fs.writeFileSync(path.join(candidate, 'preview-build.json'),
      JSON.stringify({ ...source, builtAt: new Date().toISOString() }, null, 2) + '\n')
    const current = publishPreview(channel, staging)
    console.log('Local UI test executable: ' + path.join(current, productName + '.exe'))
  } finally {
    // If Windows refused both the replacement and rollback, a preserved copy
    // containing the last working app is more useful than an empty channel.
    if (fs.existsSync(path.join(channel, 'win-unpacked')) || !fs.existsSync(path.join(staging, 'previous'))) {
      const folder = existingDirectory(channel, path.basename(staging))
      if (folder) fs.rmSync(folder, { recursive: true, force: true })
    }
  }
}

if (require.main === module) {
  main().catch(error => { console.error(error); process.exitCode = 1 })
}
module.exports = { publishPreview }
