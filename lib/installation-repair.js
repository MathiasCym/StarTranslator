// Offline component recovery. The UI supplies no paths or replacement bytes.
let fs
try { fs = require('original-fs') } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; fs = require('node:fs') }
const io = fs.promises, path = require('node:path'), crypto = require('node:crypto'), zlib = require('node:zlib')
const { pipeline } = require('node:stream/promises'), { Transform } = require('node:stream')
const { MANIFEST, digest, targetPath, verifyInstallation, validateManifest, isRuntimeCache } = require('./install-integrity')
const RECOVERY_INDEX = 'resources/repair/index.json', RECOVERY_DATA = 'resources/repair/components.gzpack'
function recoverable(relative) {
  return !isRuntimeCache(relative) && ['resources/officecli/', 'resources/python-runtime/', 'resources/app.asar.unpacked/backend/'].some(prefix => relative.startsWith(prefix))
}
async function safeTarget(root, relative) {
  const target = targetPath(root, relative)
  // Refuse junctions and symlinks instead of following them when writing.
  let current = path.resolve(root)
  for (const part of [null, ...relative.split('/')]) {
    if (part) current = path.join(current, part)
    try { if ((await io.lstat(current)).isSymbolicLink()) throw new Error('程序路径使用了链接，无法安全自动修复。') }
    catch (error) { if (error.code !== 'ENOENT') throw error }
  }
  return target
}
async function loadRecovery(root, manifest, version) {
  for (const relative of [RECOVERY_INDEX, RECOVERY_DATA]) {
    const entry = manifest.files.find(file => file.path === relative)
    const file = await safeTarget(root, relative)
    if (!entry || (await io.stat(file)).size !== entry.size || await digest(file) !== entry.sha256) throw new Error('本机修复副本缺失或损坏，请使用完整安装包重新安装。')
  }
  const index = JSON.parse(await io.readFile(targetPath(root, RECOVERY_INDEX), 'utf8'))
  if (index.schema !== 1 || index.version !== version || !Array.isArray(index.files)) throw new Error('本机修复副本版本不匹配，请重新安装。')
  const dataSize = (await io.stat(targetPath(root, RECOVERY_DATA))).size, seen = new Set(), entries = new Map()
  for (const entry of index.files) {
    const expected = manifest.files.find(file => file.path === entry.path)
    if (!expected || !recoverable(entry.path) || seen.has(entry.path.toLowerCase()) || !Number.isSafeInteger(entry.offset) || entry.offset < 0 || !Number.isSafeInteger(entry.length) || entry.length <= 0 || entry.offset + entry.length > dataSize || !/^[a-f0-9]{64}$/.test(entry.packedSha256) || expected.size !== entry.size || expected.sha256 !== entry.sha256) throw new Error('本机修复副本清单无效，请重新安装。')
    seen.add(entry.path.toLowerCase()); entries.set(entry.path, entry)
  }
  return entries
}
async function restoreOne(root, entry) {
  const target = await safeTarget(root, entry.path)
  const metadata = await io.lstat(target).catch(error => { if (error.code !== 'ENOENT') throw error; return null })
  if (metadata && !metadata.isFile()) throw new Error('目标位置不是程序文件，无法自动替换。')
  // A file may have been repaired by another process since the initial scan.
  if (metadata?.size === entry.size && await digest(target) === entry.sha256) return false
  await io.mkdir(path.dirname(target), { recursive: true })
  const temporary = target + '.star-repair-' + crypto.randomUUID() + '.tmp'
  let written = 0
  const packedHash = crypto.createHash('sha256')
  const compressed = new Transform({ transform(chunk, _encoding, cb) { packedHash.update(chunk); cb(null, chunk) } })
  const limiter = new Transform({ transform(chunk, _encoding, cb) {
    written += chunk.length
    cb(written > entry.size ? new Error('修复副本解压大小不符。') : null, written > entry.size ? undefined : chunk)
  } })
  try {
    await pipeline(fs.createReadStream(targetPath(root, RECOVERY_DATA), { start: entry.offset, end: entry.offset + entry.length - 1 }), compressed, zlib.createGunzip(), limiter, fs.createWriteStream(temporary, { flags: 'wx' }))
    if (written !== entry.size || packedHash.digest('hex') !== entry.packedSha256 || await digest(temporary) !== entry.sha256) throw new Error('修复副本内容校验失败，未替换原文件。')
    await safeTarget(root, entry.path)
    await io.rename(temporary, target)
    if ((await io.stat(target)).size !== entry.size || await digest(target) !== entry.sha256) throw new Error('修复后文件再次校验失败。')
    return true
  } finally { await io.unlink(temporary).catch(() => {}) }
}
async function checkAndRepair({ root, version, progress = () => {}, beforeRepair = async () => {}, afterRepair = async () => {}, log = () => {} }) {
  const manifest = JSON.parse(await io.readFile(targetPath(root, MANIFEST), 'utf8'))
  validateManifest(root, manifest, version)
  const scan = phase => verifyInstallation(root, manifest, version, (checked, total) => progress({ phase, checked, total, percent: Math.floor(100 * checked / total) }), { runtime: true })
  const initial = await scan('checking')
  log('Integrity scan', initial)
  if (initial.complete) return { ...initial, repaired: [], repairErrors: [], message: `完整性校验通过 · 已检查 ${initial.checked} 项程序文件。` }
  const candidates = initial.failures.filter(failure => recoverable(failure.path)), repaired = [], repairErrors = []
  let backendPaused = false
  try {
    if (candidates.length) {
      progress({ phase: 'preparing', checked: 0, total: candidates.length, percent: 0 })
      const recovery = await loadRecovery(root, manifest, version)
      // Only pause the backend after validating the complete local recovery data.
      await beforeRepair(candidates); backendPaused = true
      for (const [i, failure] of candidates.entries()) {
        progress({ phase: 'repairing', checked: i, total: candidates.length, percent: Math.floor(100 * i / candidates.length) })
        try {
          const entry = recovery.get(failure.path)
          if (!entry) throw new Error('本版本未包含该文件的修复副本，请重新安装。')
          if (await restoreOne(root, entry)) repaired.push(failure.path)
        } catch (error) {
          const reason = ['EACCES', 'EPERM', 'EBUSY'].includes(error.code) ? '文件被占用或无写入权限；请关闭软件后用安装包修复。' : error.message
          repairErrors.push({ path: failure.path, reason }); log('Repair failed', { path: failure.path, code: error.code, reason })
        }
      }
    }
  } catch (error) { repairErrors.push({ path: '本机修复副本', reason: error.message }); log('Repair unavailable', error.message) }
  let final
  let serviceError = ''
  try {
    final = await scan('rechecking')
    log('Integrity recheck', { ...final, repaired, repairErrors })
  } finally {
    if (backendPaused) try { await afterRepair() } catch (error) { serviceError = error.message; log('Backend restart failed', serviceError) }
  }
  return { ...final, filesComplete: final.complete, complete: final.complete && !serviceError, repaired, repairErrors, serviceError,
    message: final.complete ? `修复完成，完整性校验通过 · 已恢复 ${repaired.length} 项程序文件。${serviceError ? '本地服务未恢复，请重启软件或导出日志。' : ''}`
      : `已恢复 ${repaired.length} 项，仍有 ${final.failures.length} 项未通过校验。请查看下方原因，必要时使用完整安装包重新安装。` }
}
module.exports = { RECOVERY_INDEX, RECOVERY_DATA, recoverable, safeTarget, checkAndRepair }
