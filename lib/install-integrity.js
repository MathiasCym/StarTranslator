// Electron's normal fs treats app.asar as a virtual directory. Integrity checks
// must hash the actual archive on disk, just as the Node packaging step does.
let fs
try { fs = require('original-fs') } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; fs = require('node:fs') }
const io = fs.promises, path = require('node:path'), crypto = require('node:crypto')

const MANIFEST = 'resources/install-manifest.json'
async function digest(file) {
  const hash = crypto.createHash('sha256')
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk)
  return hash.digest('hex')
}
function targetPath(root, relative) {
  if (typeof relative !== 'string' || !relative || path.isAbsolute(relative) || /[\\:\x00-\x1f]/.test(relative) || relative.split('/').some(p => !p || p === '..' || p === '.' || /[. ]$/.test(p))) throw new Error('安装校验清单包含无效路径。')
  const target = path.resolve(root, relative), inside = path.relative(path.resolve(root), target)
  if (inside.startsWith('..') || path.isAbsolute(inside)) throw new Error('安装校验清单路径超出安装目录。')
  return target
}
async function createManifest(root, version) {
  const files = []
  async function visit(folder) {
    for (const entry of await io.readdir(folder, { withFileTypes: true })) {
      const full = path.join(folder, entry.name)
      if (entry.isDirectory()) await visit(full)
      else if (entry.isFile()) {
        const relative = path.relative(root, full).replaceAll('\\', '/')
        if (relative !== MANIFEST) files.push({ path: relative, size: (await io.stat(full)).size, sha256: await digest(full) })
      }
    }
  }
  await visit(root)
  return { schema: 1, version, files }
}
function validateManifest(root, manifest, version) {
  if (manifest?.schema !== 1 || manifest.version !== version || !Array.isArray(manifest.files) || !manifest.files.length) throw new Error('安装校验清单缺失或版本不匹配，请重新打开完整安装包。')
  const required = ['星译官.exe', 'resources/app.asar', 'resources/officecli/officecli.exe', 'resources/python-runtime/python.exe', 'resources/python-runtime/python311.dll', 'resources/app.asar.unpacked/backend/server.py']
  if (required.some(file => !manifest.files.some(entry => entry.path === file))) throw new Error('安装校验清单缺少必要组件，请重新获取完整安装包。')
  const seen = new Set()
  for (const entry of manifest.files) {
    targetPath(root, entry.path)
    if (!Number.isSafeInteger(entry.size) || entry.size < 0 || !/^[a-f0-9]{64}$/.test(entry.sha256) || seen.has(entry.path.toLowerCase())) throw new Error('安装校验清单无效，请重新获取完整安装包。')
    seen.add(entry.path.toLowerCase())
  }
}
function isRuntimeCache(relative) { return relative.split('/').includes('__pycache__') || /\.py[co]$/i.test(relative) }
async function verifyInstallation(root, manifest, version, progress = () => {}, options = {}) {
  validateManifest(root, manifest, version)
  const files = options.runtime ? manifest.files.filter(entry => !isRuntimeCache(entry.path)) : manifest.files
  const skipped = manifest.files.length - files.length, realRoot = await io.realpath(root)
  let cursor = 0, checked = 0
  const failures = []
  await Promise.all(Array.from({ length: 4 }, async () => {
    while (cursor < files.length) {
      const entry = files[cursor++]
      const target = targetPath(root, entry.path)
      try {
        const resolved = await io.realpath(target), inside = path.relative(realRoot, resolved)
        if (inside.startsWith('..') || path.isAbsolute(inside)) throw Object.assign(new Error('程序路径指向安装目录之外'), { code: 'UNSAFE_PATH' })
        const metadata = await io.lstat(target)
        if (!metadata.isFile() || metadata.size !== entry.size || await digest(target) !== entry.sha256) failures.push({ path: entry.path, reason: '内容与安装包不一致' })
      } catch (error) { failures.push({ path: entry.path, reason: error.code === 'ENOENT' ? '文件缺失' : '无法读取（' + (error.code || '未知错误') + '）' }) }
      progress(++checked, files.length)
    }
  }))
  return { complete: !failures.length, checked, skipped, failures, message: failures.length ? '安装文件校验未通过：' + failures.slice(0, 4).map(f => `${f.path}（${f.reason}）`).join('；') + (failures.length > 4 ? `；另有 ${failures.length - 4} 项` : '') + '。请重新安装；详情已保存在安装日志中。' : '' }
}
module.exports = { MANIFEST, digest, targetPath, createManifest, verifyInstallation, validateManifest, isRuntimeCache }
