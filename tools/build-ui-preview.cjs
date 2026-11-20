const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')
const { build, Platform, Arch } = require('electron-builder')

async function main() {
  const root = path.resolve(__dirname, '..')
  const stamp = new Date().toISOString().replace(/[^0-9]/g, '')
  const channel = path.join(root, 'dist', 'ui-preview')
  const output = path.join(channel, stamp)
  const runGit = args => execFileSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true }).trim()
  const source = { branch: process.env.GITHUB_HEAD_REF || process.env.GITHUB_REF_NAME || runGit(['branch', '--show-current']), commit: runGit(['rev-parse', 'HEAD']), localChanges: Boolean(runGit(['status', '--porcelain'])) }
  require('./build-patch-helper.cjs').build()
  await build({
    projectDir: root,
    targets: Platform.WINDOWS.createTarget(['dir'], Arch.x64),
    publish: 'never',
    config: {
      directories: { output },
      extraMetadata: { starPreview: true },
      electronDist: path.join(root, 'node_modules', 'electron', 'dist'),
    },
  })
  const name = require('../package.json').build.productName + '.exe'
  const executable = path.join(output, 'win-unpacked', name)
  fs.accessSync(executable)
  const launcher = relative => '@echo off\r\nchcp 65001 >nul\r\nstart "" "%~dp0' + relative + '"\r\n'
  const target = path.join('win-unpacked', name)
  fs.writeFileSync(path.join(output, 'Start-StarTranslator-Test.cmd'), launcher(target))
  fs.writeFileSync(path.join(output, 'preview-build.json'), JSON.stringify({ ...source, builtAt: new Date().toISOString() }, null, 2) + '\n')
  const manifest = JSON.parse(fs.readFileSync(path.join(output, 'win-unpacked', 'resources', 'install-manifest.json'), 'utf8'))
  const checked = await require('../lib/install-integrity').verifyInstallation(path.dirname(executable), manifest, require('../package.json').version)
  if (!checked.complete) throw Error(checked.message)
  const ready = path.join(channel, 'Start-StarTranslator-Test.cmd')
  fs.writeFileSync(ready + '.tmp', launcher(path.join(stamp, target)))
  fs.renameSync(ready + '.tmp', ready)
  console.log('Local UI test executable: ' + executable)
}
main().catch(error => { console.error(error); process.exitCode = 1 })
