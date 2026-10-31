// Keep installer identity stable while giving new profiles the product's name.
// A legacy junction preserves absolute paths in history/checkpoints and older
// update workers. No data is merged, deleted, decrypted or serialized here.
const fs = require('node:fs'), path = require('node:path')
const LEGACY = 'novaterm-checker', CURRENT = 'StarTranslator'
function resolveExisting(appData) {
  const current = path.join(appData, CURRENT), legacy = path.join(appData, LEGACY)
  // A new empty directory can be created by Electron or an installer before
  // normal startup. Update helpers must follow the same legacy fallback.
  if (fs.existsSync(current) && fs.existsSync(legacy) && fs.realpathSync(current) !== fs.realpathSync(legacy)) return legacy
  return fs.existsSync(current) ? current : fs.existsSync(legacy) ? legacy : current
}
function migrate(appData, io = fs) {
  const current = path.join(appData, CURRENT), legacy = path.join(appData, LEGACY)
  const result = { path: current, migrated: false, warning: '' }
  if (!io.existsSync(legacy)) return result
  if (io.existsSync(current)) {
    if (io.realpathSync(legacy) === io.realpathSync(current)) return result
    // Only an ordinary, completely empty directory is a safe placeholder.
    // Never follow a different junction, delete contents or combine profiles.
    if (io.lstatSync(current).isSymbolicLink() || !io.statSync(current).isDirectory() || io.readdirSync(current).length) {
      return { ...result, path: legacy, warning: '发现新旧两个独立的数据目录。为保留现有词库、模型配置和历史，本次继续使用旧目录；请通过诊断日志联系维护者核对后迁移。' }
    }
    try { io.rmdirSync(current) }
    catch (error) { return { ...result, path: legacy, warning: '空的新数据目录暂时被占用，未迁移任何文件。本次继续使用原有词库、模型配置和历史；关闭旧程序后重新启动可重试。' } }
  }
  try {
    io.renameSync(legacy, current)
    try { io.symlinkSync(current, legacy, 'junction') }
    catch (error) {
      // Without the compatibility path, persisted absolute references may fail.
      io.renameSync(current, legacy)
      throw error
    }
    return { ...result, migrated: true }
  } catch (error) {
    if (!io.existsSync(legacy)) throw error // Do not start a blank profile.
    return { ...result, path: legacy, warning: '本机数据目录暂时无法迁移（可能仍有旧程序占用）。本次继续使用旧目录，数据已保留；请关闭旧版本后重新启动。' }
  }
}
function configure(app, { move = true } = {}) {
  const appData = app.getPath('appData'), selected = app.getPath('userData')
  const defaults = [LEGACY, CURRENT, 'startranslator'].map(name => path.resolve(appData, name).toLowerCase())
  if (!defaults.includes(path.resolve(selected).toLowerCase())) return { path: selected, migrated: false, warning: '' }
  const result = move ? migrate(appData) : { path: resolveExisting(appData), migrated: false, warning: '' }
  app.setPath('userData', result.path)
  return result
}
module.exports = { migrate, configure, resolveExisting, CURRENT, LEGACY }
