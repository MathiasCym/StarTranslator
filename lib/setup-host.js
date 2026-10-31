const { app, BrowserWindow, ipcMain, shell } = require('electron')
const { execFile } = require('node:child_process')
const fs = require('node:fs/promises'), path = require('node:path'), os = require('node:os')
const { installFilePicker } = require('./file-picker')
const { workerArguments, directoryNeedsElevation, launchWorker, workerOutcome } = require('./setup-worker')
const { createLogger } = require('./runtime-log')
const { verifyInstallation } = require('./install-integrity')
const REGISTRY_KEY = 'Software\\40dcc9aa-3b67-5e68-9a54-dc7e46ccf86d'
const EXE = '星译官.exe'

function argument(name) { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] || '' : '' }
async function registeredLocation(hive) {
  const root = hive === 'HKCU' ? 'HKEY_CURRENT_USER' : 'HKEY_LOCAL_MACHINE'
  const script = `$p=(Get-ItemProperty -LiteralPath 'Registry::${root}\\${REGISTRY_KEY}' -ErrorAction SilentlyContinue).InstallLocation; if($p){[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($p))}`
  return new Promise(resolve => execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], { windowsHide: true }, (error, stdout) => {
    if (error) return resolve('')
    resolve(stdout.trim() ? Buffer.from(stdout.trim(), 'base64').toString('utf8') : '')
  }))
}
async function isExistingInstallation(directory) {
  try {
    const metadata = JSON.parse(await fs.readFile(path.join(directory, 'resources', 'app.asar', 'package.json'), 'utf8'))
    return ['startranslator', 'novaterm-checker'].includes(metadata.name) || metadata.build?.appId === 'tech.novastar.novaterm'
  } catch { return false }
}
async function validateInstallDirectory(value, registeredDirectories = []) {
  if (typeof value !== 'string' || !path.win32.isAbsolute(value) || /["<>|?*\x00-\x1f]/.test(value)) throw new Error('请输入完整、有效的安装路径。')
  const normalized = path.win32.normalize(value)
  const directory = normalized.replace(/\\+$/, '')
  const forbidden = [path.win32.parse(normalized).root, process.env.WINDIR, process.env.ProgramFiles, process.env['ProgramFiles(x86)'], process.env.LOCALAPPDATA, process.env.APPDATA, os.homedir()].filter(Boolean)
  if (forbidden.some(p => path.win32.normalize(p).replace(/\\+$/, '').toLowerCase() === directory.toLowerCase())) throw new Error('请为星译官指定独立的程序文件夹。')
  if (directory.split('\\').some(part => /[. ]$/.test(part) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(part))) throw new Error('安装路径包含无效的文件夹名称。')
  const registered = registeredDirectories.some(p => p && path.win32.normalize(p).replace(/\\+$/, '').toLowerCase() === directory.toLowerCase())
  try {
    const entries = await fs.readdir(directory)
    if (entries.length) {
      if (!registered && !await isExistingInstallation(directory)) throw new Error('此位置不是星译官安装目录。请选择现有星译官文件夹，或为新安装指定独立的空文件夹。')
    }
  } catch (error) {
    // A registered installation can be validated by the elevated worker.
    if (error.code !== 'ENOENT' && !(registered && ['EACCES', 'EPERM'].includes(error.code))) throw error
  }
  return directory
}

async function startSetup(testOptions = {}) {
  const updateUserData = app.getPath('userData')
  app.commandLine.appendSwitch('force-device-scale-factor', '1')
  if (!testOptions.userData) app.setPath('userData', path.join(app.getPath('temp'), 'StarTranslatorSetup'))
  else app.setPath('userData', testOptions.userData)
  if (!app.requestSingleInstanceLock()) { app.quit(); return }
  const uninstall = testOptions.uninstall ?? process.argv.includes('--star-uninstall')
  const worker = testOptions.worker || argument('--star-worker')
  const initialDirectory = testOptions.directory || argument('--star-directory')
  let win, busy = false, complete = false, target = '', child, poll
  await app.whenReady()
  const log = createLogger(path.join(app.getPath('userData'), 'logs', 'setup.log'))
  const [userPath, machinePath] = testOptions.locations || (process.argv.includes('--star-locations-loaded')
    ? [argument('--star-user-directory'), argument('--star-machine-directory')]
    : await Promise.all([registeredLocation('HKCU'), registeredLocation('HKLM')]))
  const scope = machinePath && !userPath ? 'all' : 'current'
  const defaultPath = uninstall ? initialDirectory || userPath || machinePath : userPath || machinePath || initialDirectory || path.join(process.env.LOCALAPPDATA || app.getPath('home'), 'Programs', 'StarTranslator')
  const icon = () => path.join(process.resourcesPath, 'icon.png')
  const pick = installFilePicker(() => win, icon)
  const check = event => { if (!win || event.sender.id !== win.webContents.id) throw new Error('安装窗口不可访问。') }
  const status = value => { if (win && !win.isDestroyed()) win.webContents.send('setup-status', value) }
  ipcMain.handle('setup-info', event => { check(event); return { version: app.getVersion(), directory: defaultPath, scope, uninstall, upgrade: !!(userPath || machinePath) } })
  ipcMain.handle('setup-pick-directory', async event => {
    check(event)
    const paths = await pick({ title: '选择安装文件夹', mode: 'directory', directory: defaultPath, extensions: [] })
    if (!paths[0]) return ''
    const existing = [userPath, machinePath].some(p => p && path.normalize(p).toLowerCase() === path.normalize(paths[0]).toLowerCase()) || await isExistingInstallation(paths[0])
    return existing || path.basename(paths[0]).toLowerCase() === 'startranslator' ? paths[0] : path.join(paths[0], 'StarTranslator')
  })
  ipcMain.handle('setup-close', event => { check(event); if (!busy) win.close(); return !busy })
  ipcMain.handle('setup-minimize', event => { check(event); win.minimize() })
  ipcMain.handle('setup-launch', async event => {
    check(event)
    if (!complete || uninstall) throw new Error('安装尚未完成。')
    const error = await shell.openPath(path.join(target, EXE))
    if (error) throw new Error(error)
    win.close()
  })
  ipcMain.handle('setup-start', async (event, input) => {
    check(event)
    if (busy || complete) return { started: false }
    if (!worker || !path.isAbsolute(worker) || !(await fs.stat(worker).catch(() => null))?.isFile()) throw new Error('安装组件不可访问，请重新打开安装包。')
    target = uninstall ? defaultPath : await validateInstallDirectory(input.directory, [userPath, machinePath])
    // A reinstall keeps the scope recorded by the existing installation.
    const selectedScope = userPath || machinePath ? scope : input.scope === 'all' ? 'all' : 'current'
    const elevate = selectedScope === 'all' || await (testOptions.directoryNeedsElevation || directoryNeedsElevation)(target)
    const sessionDir = await fs.mkdtemp(path.join(app.getPath('temp'), 'star-setup-status-'))
    const statusFile = path.join(sessionDir, 'status.txt')
    busy = true; status({ phase: 'checking' })
    const args = workerArguments({ uninstall, directory: target, scope: selectedScope, statusFile })
    log.info('Starting', { uninstall, target, scope: selectedScope, elevate })
    let previous = '', verifiedCount = 0
    poll = setInterval(async () => {
      try { const phase = (await fs.readFile(statusFile, 'utf8')).trim(); if (phase !== previous && ['checking', 'files', 'registering'].includes(phase)) { previous = phase; status({ phase }) } } catch {}
    }, 250)
    try {
      child = (testOptions.launchWorker || launchWorker)({ worker, args, elevate })
      let settled = false
      const finish = async (code, error) => {
        if (settled) return
        settled = true; clearInterval(poll); child = null
        const phase = (await fs.readFile(statusFile, 'utf8').catch(() => '')).trim()
        const executableExists = !!(await fs.stat(path.join(target, EXE)).catch(() => null))
        let outcome = workerOutcome({ code, error, phase, executableExists, uninstall })
        if (outcome.complete && !uninstall) {
          status({ phase: 'verifying', percent: 0 })
          try {
            // Trust the checklist carried by this installer, not an older copy
            // already in the destination directory.
            const checklist = await fs.readFile(path.join(process.resourcesPath, 'install-manifest.json'), 'utf8')
            if (await fs.readFile(path.join(target, 'resources/install-manifest.json'), 'utf8') !== checklist) throw new Error('安装校验清单未完整写入，请重新安装。')
            const manifest = JSON.parse(checklist)
            let lastPercent = -1
            outcome = await (testOptions.verifyInstallation || verifyInstallation)(target, manifest, app.getVersion(), (checked, total) => {
              const percent = Math.floor(100 * checked / total)
              verifiedCount = checked
              if (percent !== lastPercent) { lastPercent = percent; status({ phase: 'verifying', percent, checked, total }) }
            })
            log.info('File verification', outcome)
          } catch (error) { log.error(error); outcome = { complete: false, message: '安装文件校验未完成：' + error.message } }
        }
        complete = outcome.complete
        log.info('Finished', { code, phase, complete, error: error?.message })
        busy = false
        if (complete) {
          if (!uninstall) {
            try {
              const cleanup = await require('./update-cache-cleanup').cleanupInstalledUpdate({
                userData: updateUserData, currentVersion: app.getVersion(), installer: worker,
              })
              if (cleanup.removed) log.info('Verified update cache removed', { version: cleanup.version })
              else if (cleanup.deferred) log.info('Update cache still in use; cleanup will retry on application startup')
            } catch (error) { log.error('Update cache cleanup deferred', error) }
          }
          status({ phase: 'complete', directory: target, checked: verifiedCount })
        }
        else status({ phase: 'error', message: outcome.message })
        await fs.rm(sessionDir, { recursive: true, force: true }).catch(() => {})
      }
      child.once('error', error => finish(null, error))
      child.once('exit', code => finish(code))
    } catch (error) {
      clearInterval(poll); busy = false; log.error(error); status({ phase: 'error', message: workerOutcome({ error }).message })
      await fs.rm(sessionDir, { recursive: true, force: true }).catch(() => {})
    }
    return { started: true }
  })
  win = new BrowserWindow({ width: 980, height: 660, frame: false, resizable: false, show: false, backgroundColor: '#081421', icon: icon(),
    webPreferences: { preload: path.join(__dirname, '../setup-preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  })
  win.on('close', event => { if (busy) event.preventDefault() })
  app.on('second-instance', () => { if (win) { win.restore(); win.focus() } })
  app.on('window-all-closed', () => app.quit())
  win.once('ready-to-show', () => win.show())
  await win.loadFile(path.join(__dirname, '../renderer/setup.html'))
  return win
}
module.exports = { startSetup, validateInstallDirectory, isExistingInstallation }
