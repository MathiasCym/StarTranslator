// 打包后给 exe 嵌入图标与版本信息。
//
// 为什么不用 electron-builder 自带的 rcedit：它会去下载 winCodeSign 压缩包，
// 包里含 macOS 的 .dylib 符号链接，Windows 无符号链接特权时解压失败，
// 整条 rcedit 步骤就没了 —— 结果就是安装后显示 Electron 自带的原子图标。
// 这里直接调用随仓库分发的 rcedit-x64.exe，绕开那次下载。
const { execFileSync } = require('child_process')
const path = require('path')
const fs = require('fs')
const crypto = require('crypto')

exports.default = async function afterPack(context) {
  // The product ships Chinese/English UI. Keep both Chinese variants and English
  // Chromium resources; ICU data (dates, numbers, all scripts) is retained.
  const locales = path.join(context.appOutDir, 'locales')
  for (const name of fs.readdirSync(locales)) {
    if (name.endsWith('.pak') && !['en-US.pak','zh-CN.pak','zh-TW.pak'].includes(name)) fs.unlinkSync(path.join(locales,name))
  }
  const sources = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'backend', 'skills', 'sources.json'), 'utf8'))
  const pinned = sources.find(source => source.name === 'officecli').binary
  const officecli = fs.readFileSync(path.join(context.appOutDir, 'resources', 'officecli', 'officecli.exe'))
  if (officecli.length !== pinned.size || 'sha256:' + crypto.createHash('sha256').update(officecli).digest('hex') !== pinned.digest) {
    throw new Error('文档检查组件与已验证的版本不一致，请恢复锁定的组件后再打包。')
  }
  const exe = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.exe`)
  if (!fs.existsSync(exe)) return

  const rcedit = path.join(__dirname, 'bin', 'rcedit-x64.exe')
  const ico = path.join(__dirname, '..', 'build', 'icon.ico')
  if (!fs.existsSync(rcedit) || !fs.existsSync(ico)) {
    throw new Error('缺少 rcedit 或 icon.ico，无法同步程序图标和版本信息')
  }

  const info = context.packager.appInfo
  const args = [
    exe,
    '--set-icon', ico,
    '--set-version-string', 'FileDescription', info.description || info.productName,
    '--set-version-string', 'ProductName', info.productName,
    '--set-version-string', 'InternalName', info.productName,
    '--set-version-string', 'CompanyName', info.companyName || '',
    '--set-version-string', 'OriginalFilename', path.basename(exe),
    '--set-file-version', info.version,
    '--set-product-version', `${info.version}.0`,
  ]
  if (info.copyright) args.push('--set-version-string', 'LegalCopyright', info.copyright)

  execFileSync(rcedit, args, { stdio: 'inherit' })
  console.log(`[afterpack] 已嵌入图标：${path.basename(exe)}`)
  const { createManifest, MANIFEST } = require('../lib/install-integrity')
  const recovery = await require('./build-component-recovery').buildComponentRecovery(context.appOutDir, info.version)
  console.log(`[afterpack] 已生成 ${recovery.files} 项离线组件修复副本（${Math.ceil(recovery.bytes / 1024 / 1024)} MiB）`)
  const manifest = await createManifest(context.appOutDir, info.version)
  fs.writeFileSync(path.join(context.appOutDir, MANIFEST), JSON.stringify(manifest))
  console.log(`[afterpack] 已生成 ${manifest.files.length} 项安装文件校验清单`)
  // Feed the stock NSIS file installer directly, avoiding an intermediate 7z
  // extraction/copy. NSIS deduplicates the UI/runtime files embedded twice.
  const nsisPath = value => value.replace(/\$/g, '$$$$').replace(/"/g, '$\\"')
  fs.writeFileSync(path.join(__dirname, '..', 'build', 'setup-runtime.nsh'),
    `!define STAR_APP_DIR "${nsisPath(context.appOutDir)}"\n!define APP_BUILD_DIR "${nsisPath(context.appOutDir)}"\n`)
}
