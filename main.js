const runtimeLog = require('./lib/runtime-log').createLogger(() =>
  require('path').join(require('electron').app.getPath('userData'), 'logs', 'runtime.log'))

if (process.argv.includes('--star-setup') || process.argv.includes('--star-uninstall')) {
  require('./lib/setup-host').startSetup().catch(error => { runtimeLog.error(error); process.exitCode = 1 })
} else {
const { app, BrowserWindow, ipcMain, shell, screen, clipboard } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { ModelConnectionMonitor } = require('./lib/model-monitor')

// Electron dimensions normally use DIP; a 125/150% Windows scale enlarges them.
// Pin the device scale to 1 so window width/height below map to physical pixels
// and the default size is honored verbatim. Must be set before Chromium starts.
app.commandLine.appendSwitch('force-device-scale-factor', '1')

const { installFilePicker } = require('./lib/file-picker')
let mainWindow = null
let windowCloseGuard = null
let pickCustom
let backendProc = null
let backendPort = null
let maintenanceBusy = false, apiWrites = 0
const modelMonitor = new ModelConnectionMonitor({
  getPort: () => backendPort,
  onStatus: status => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('model-status', status)
  },
})

// 后端代码（backend/glossary/tools）在 asarUnpack 列表里，打包后会落到
// app.asar.unpacked。外部 Python 读不了 asar 归档，必须把路径换到解包目录。
function appRoot() {
  return __dirname.includes('app.asar')
    ? __dirname.replace('app.asar', 'app.asar.unpacked')
    : __dirname
}

// 窗口/任务栏图标。不指定的话 Electron 会用自带默认图标（就是一个原子状的 logo），
// 与安装包外观不一致。开发时读 build/icon.png，打包后读 extraResources 放出的同名文件。
function iconPath() {
  const candidates = [
    path.join(process.resourcesPath || '', 'icon.png'),
    path.join(__dirname, 'build', 'icon.png'),
  ]
  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c
  }
  return undefined
}

// 运行期定位 Python：优先用打包进来的便携运行时，退回系统安装
function resolvePython() {
  const root = appRoot()
  const candidates = [
    path.join(process.resourcesPath || '', 'python-runtime', 'python.exe'),
    path.join(root, 'python-runtime', 'python.exe'),
    path.join(__dirname, 'python-runtime', 'python.exe'),
    'C:\\Users\\Administrator\\AppData\\Local\\NovaClaudeTools\\python-3.11.9\\python.exe',
    'python',
  ]
  for (const c of candidates) {
    if (c === 'python' || fs.existsSync(c)) return c
  }
  return 'python'
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const python = resolvePython()
    const root = appRoot()
    const script = path.join(root, 'backend', 'server.py')

    const child = backendProc = spawn(python, [script, '--port', '0'], {
      cwd: root,
      env: { ...process.env, NOVATERM_DATA_DIR: app.getPath('userData'), STAR_RESOURCE_DIR: process.resourcesPath },
      windowsHide: true,
    })

    let settled = false
    const timeout = setTimeout(() => {
      if (!settled) { settled = true; reject(new Error('后端启动超时')) }
    }, 30000)

    child.stdout.on('data', (data) => {
      const text = data.toString()
      const m = text.match(/PORT=(\d+)/)
      if (m && !settled) {
        settled = true
        clearTimeout(timeout)
        backendPort = parseInt(m[1], 10)
        resolve(backendPort)
      }
    })

    child.stderr.on('data', (d) => {
      runtimeLog.error('[backend]', d.toString())
    })

    child.on('error', (err) => {
      if (backendProc === child) { backendProc = null; backendPort = null }
      if (!settled) { settled = true; clearTimeout(timeout); reject(err) }
    })

    child.on('exit', (code) => {
      runtimeLog.info('[backend] exited with', code)
      if (backendProc === child) {
        backendProc = null; backendPort = null
        modelMonitor.backendUnavailable('本地服务已停止，请重新启动软件。')
      }
      if (!settled) {
        settled = true
        clearTimeout(timeout)
        reject(new Error('后端启动失败'))
      }
    })
  })
}

function stopBackend() {
  modelMonitor.stop()
  backendPort = null
  if (backendProc) {
    try { backendProc.kill() } catch (_) {}
    backendProc = null
  }
}

// 后端可能启动慢，前端通过 IPC 拿到端口再发请求
ipcMain.handle('backend-port', () => backendPort)
ipcMain.handle('app-version', () => app.getVersion())
let githubUpdater,quitAfterDownload=false
function updater(){
  if(!githubUpdater)githubUpdater=new (require('./lib/github-updates').GitHubUpdates)({
    currentVersion:app.getVersion(),userData:app.getPath('userData'),
    fetcher:require('./lib/electron-update-transport').createFetcher(require('electron').net),
    onStatus:value=>{if(mainWindow&&!mainWindow.isDestroyed())mainWindow.webContents.send('update-status',value)},
  })
  return githubUpdater
}
function updateSender(event){if(!mainWindow||event.sender.id!==mainWindow.webContents.id)throw Error('当前窗口无法管理软件更新。')}
ipcMain.handle('update-state',event=>{updateSender(event);return updater().snapshot()})
ipcMain.handle('check-updates',event=>{updateSender(event);return updater().check()})
ipcMain.handle('download-update',event=>{updateSender(event);return updater().download()})
ipcMain.handle('cancel-update',event=>{updateSender(event);return updater().cancel()})
ipcMain.handle('open-maintenance-authorization',event=>{updateSender(event);return shell.openExternal('https://github.com/settings/tokens')})
ipcMain.handle('install-update',async event=>{
  updateSender(event)
  if(!app.isPackaged)throw Error('请在安装后的星译官中使用在线安装更新。')
  if(maintenanceBusy||apiWrites)throw Error('正在保存或校验，请完成后再安装更新。')
  if(BrowserWindow.getAllWindows().some(window=>window!==mainWindow))throw Error('请先关闭共享工作台和文件选择窗口，再安装更新。')
  maintenanceBusy=true;let launched=false
  try{
    await backendMaintenanceLease(true)
    const installer=await updater().prepareInstall()
    const error=await shell.openPath(installer);if(error)throw Error('无法启动更新安装包：'+error)
    launched=true;mainWindow.destroy();app.quit();return {started:true}
  }finally{
    if(!launched){maintenanceBusy=false;await backendMaintenanceLease(false).catch(()=>{})}
  }
})
app.on('before-quit',event=>{
  if(githubUpdater?.isDownloading&&!quitAfterDownload){event.preventDefault();quitAfterDownload=true;githubUpdater.cancel().finally(()=>app.quit())}
})
ipcMain.handle('export-diagnostics', async (event, task) => {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) throw new Error('当前窗口无法导出日志。')
  const paths = await pickCustom({ title: '导出错误日志', mode: 'save', multiple: false,
    name: 'StarTranslator-Error-' + new Date().toISOString().replace(/[:.]/g, '-') + '.txt', extensions: ['txt'] })
  if (!paths.length) return null
  const report = await require('./lib/diagnostics').buildDiagnostics({ version: app.getVersion(), resources: process.resourcesPath,
    userData: app.getPath('userData'), setupLog: path.join(app.getPath('temp'), 'StarTranslatorSetup/logs/setup.log'), task })
  await fs.promises.writeFile(paths[0], '\ufeff' + report, 'utf8')
  return paths[0]
})
// 关于对话框展示各版本更新内容。CHANGELOG.md 随包分发（files 白名单已含），
// 打包后在 asar 内，直接用 fs 读 __dirname 即可，无需解包目录。
ipcMain.handle('app-changelog', () => {
  try { return fs.readFileSync(path.join(__dirname, 'CHANGELOG.md'), 'utf8') } catch (_) { return '' }
})
ipcMain.handle('copy-author-email', event => {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) throw new Error('当前窗口无法复制邮箱。')
  clipboard.writeText('chenym1@novastar.tech')
  return true
})
ipcMain.handle('model-status', () => modelMonitor.status)

function backendMaintenanceStatus() {
  if (!backendPort) {
    if (backendProc) throw new Error('本地服务正在启动，请稍候再校验。')
    return Promise.resolve({ busy: false })
  }
  return new Promise((resolve, reject) => {
    const request = http.get({ hostname: '127.0.0.1', port: backendPort, path: '/api/maintenance/status', timeout: 5000 }, response => {
      let text = ''
      response.on('data', chunk => { text += chunk })
      response.on('end', () => { try {
        const value = JSON.parse(text)
        if (response.statusCode !== 200 || typeof value.busy !== 'boolean') throw new Error('未能确认任务状态，请稍候再校验。')
        resolve(value)
      } catch (error) { reject(error) } })
    })
    request.on('error', reject); request.on('timeout', () => request.destroy(new Error('未能确认任务状态，请稍候再校验。')))
  })
}
function backendMaintenanceLease(lock) {
  if (!backendPort) return Promise.resolve()
  return new Promise((resolve,reject)=>{
    const req=http.request({hostname:'127.0.0.1',port:backendPort,path:'/api/maintenance/'+(lock?'lock':'unlock'),method:'POST',timeout:5000},res=>{
      let data='';res.on('data',chunk=>{data+=chunk});res.on('end',()=>{try{const value=JSON.parse(data);if(!value.ok)throw Error(value.error||'未能确认维护状态。');resolve()}catch(e){reject(e)}})
    });req.on('error',reject);req.on('timeout',()=>req.destroy(Error('未能确认维护状态。')));req.end()
  })
}
async function pauseBackendForRepair() {
  const child = backendProc
  if (!child) return
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error('本地服务尚未停止，未替换运行中的组件。')) }, 5000)
    const stopped = () => { cleanup(); resolve() }
    const cleanup = () => { clearTimeout(timer); child.removeListener('exit', stopped) }
    child.once('exit', stopped)
    try { modelMonitor.stop(); child.kill() } catch (error) { cleanup(); reject(error) }
  })
}
ipcMain.handle('check-installation', async (event, allowServiceRestart) => {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) throw new Error('当前窗口无法校验安装文件。')
  if (!app.isPackaged) throw new Error('开发环境没有安装校验清单，请在安装后的星译官中使用此功能。')
  if (maintenanceBusy || apiWrites) throw new Error('正在处理任务或保存数据，请稍候再校验。')
  maintenanceBusy = true
  const log = require('./lib/runtime-log').createLogger(path.join(app.getPath('userData'), 'logs', 'integrity.log'))
  let servicePaused = false, lastProgress = ''
  try {
    if ((await backendMaintenanceStatus()).busy) throw new Error('后台仍有任务运行，请完成或取消任务后再校验。')
    await backendMaintenanceLease(true)
    const result = await require('./lib/installation-repair').checkAndRepair({ root: path.dirname(process.resourcesPath), version: app.getVersion(),
      log: (...items) => log.info(...items),
      progress: value => {
        const key = value.phase + ':' + value.percent
        if (key !== lastProgress && !mainWindow?.isDestroyed()) { lastProgress = key; mainWindow.webContents.send('installation-status', value) }
      },
      beforeRepair: async failures => {
        if (failures.some(f => !f.path.startsWith('resources/officecli/'))) {
          if (allowServiceRestart !== true) throw new Error('修复这些组件需要重启本地服务。请先保存并完成当前报告，再返回文档页面重新校验。')
          await pauseBackendForRepair(); servicePaused = true
        }
      },
      afterRepair: async () => {
        if (!servicePaused) return
        servicePaused = false
        await startBackend(); modelMonitor.start()
        if (!mainWindow?.isDestroyed()) mainWindow.webContents.send('backend-ready', backendPort)
      },
    })
    if (result.complete) {
      mainWindow?.webContents.send('installation-status', { phase: 'testing', percent: 0 })
      try {
        const executable = path.join(process.resourcesPath, 'officecli', 'officecli.exe')
        await new Promise((resolve, reject) => require('node:child_process').execFile(executable, ['--version'], {
          windowsHide: true, timeout: 30000, maxBuffer: 64 * 1024,
          env: { ...process.env, OFFICECLI_NO_AUTO_RESIDENT: '1', OFFICECLI_SKIP_UPDATE: '1' },
        }, (error, stdout) => {
          if (error) return reject(new Error(`文档检查组件无法启动（${error.code || '超时'}）。请导出诊断日志。`))
          if (!/\d+\.\d+\.\d+/.test(stdout)) return reject(new Error('文档检查组件未返回版本信息。请导出诊断日志。'))
          resolve()
        }))
        result.componentReady = true
      } catch (error) {
        result.filesComplete = true; result.complete = false
        result.componentErrors = [{ path: '文档检查组件', reason: error.message }]
        result.message = '程序文件完整，但文档检查组件未能正常启动。请查看原因并导出诊断日志。'
      }
    }
    log.info('Finished', result)
    return result
  } catch (error) { log.error(error); throw error }
  finally {
    if (servicePaused) {
      try { await startBackend(); modelMonitor.start() } catch (error) { log.error('Backend recovery', error) }
    }
    maintenanceBusy = false
    try { await backendMaintenanceLease(false) } catch (error) { log.error('Maintenance release',error) }
  }
})

ipcMain.handle('open-shared-service', async (event, address) => {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) throw new Error('当前窗口无法连接共享服务。')
  const target = require('./lib/shared-address').validateSharedAddress(address)
  const window = new BrowserWindow({ width:1280, height:900, minWidth:820, minHeight:620, show:false,
    title:'星译官 · 共享工作台', icon:path.join(__dirname,'renderer','assets','app-icon.png'),
    parent:mainWindow, backgroundColor:'#081524', autoHideMenuBar:true,
    webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,partition:'persist:star-lan-'+new URL(target).host} })
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}))
  window.webContents.on('will-navigate',(evt,url)=>{if(new URL(url).origin!==new URL(target).origin)evt.preventDefault()})
  window.once('ready-to-show',()=>window.show())
  try { await window.loadURL(target) } catch(error) { window.destroy(); throw new Error('未能连接共享电脑，请确认地址和共享服务已开启。') }
  return true
})

// 代理 HTTP 请求，避免前端跨域与端口暴露
ipcMain.handle('api', async (_evt, { method, path: apiPath, body }) => {
  const writing = method !== 'GET'
  if (maintenanceBusy && writing) return { error: '正在校验与修复程序文件，请完成后再开始任务或保存数据。' }
  if (!backendPort) return { error: '后端未就绪' }
  if (writing) apiWrites++
  try { return await new Promise((resolve) => {
    const payload = body ? JSON.stringify(body) : null
    const req = http.request({
      hostname: '127.0.0.1',
      port: backendPort,
      path: apiPath,
      method,
      headers: payload
        ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) }
        : {},
      timeout: 600000,
    }, (res) => {
      let data = ''
      res.on('data', (c) => { data += c })
      res.on('end', () => {
        try { resolve(JSON.parse(data)) }
        catch (_) { resolve({ error: '响应解析失败', raw: data.slice(0, 500) }) }
      })
    })
    req.on('error', (e) => resolve({ error: e.message }))
    req.on('timeout', () => { req.destroy(); resolve({ error: '请求超时' }) })
    if (payload) req.write(payload)
    req.end()
  }) } finally { if (writing) apiWrites-- }
})

ipcMain.handle('open-folder', async (_evt, filePath) => {
  if (!filePath || !fs.existsSync(filePath)) throw new Error('文件不存在，无法打开所在位置。')
  if (fs.statSync(filePath).isDirectory()) {
    const error = await shell.openPath(filePath)
    if (error) throw new Error('无法打开目录：' + error)
  } else shell.showItemInFolder(filePath)
})

ipcMain.handle('open-file', async (_evt, filePath) => {
  const error = await shell.openPath(filePath)
  if (error) throw new Error('无法打开文件：' + error)
})

ipcMain.handle('pick-files', () => pickCustom({ title: '选择要检验的文档', mode: 'open', multiple: true, extensions: ['docx', 'pptx'] }))
ipcMain.handle('pick-glossary', () => pickCustom({ title: '选择术语表', mode: 'open', multiple: true, extensions: ['xlsx', 'xlsm', 'csv', 'tsv', 'json'] }))
ipcMain.handle('export-glossary-path', async (_evt, format) => {
  if (!['json','xlsx'].includes(format)) throw new Error('请选择词库文件或 Excel 格式。')
  const paths=await pickCustom({ title:'导出术语库',mode:'save',multiple:false,name:'StarTranslator-Glossary.'+format,extensions:[format] })
  if (!paths.length)return null
  let fingerprint=''
  try { fingerprint=require('node:crypto').createHash('sha256').update(fs.readFileSync(paths[0])).digest('hex') }
  catch(error) { if(error.code!=='ENOENT')throw error }
  return {path:paths[0],fingerprint}
})
ipcMain.handle('pick-references', () => pickCustom({ title: '选择中文原文或英文参考材料', mode: 'open', multiple: true, extensions: ['docx', 'pptx', 'txt'] }))
ipcMain.handle('pick-shared-lexicon', async (_evt, create) => {
  const paths = await pickCustom({ title: create ? '创建共享术语库副本' : '连接共享术语库', mode: create ? 'save' : 'open', multiple: false,
    name: create ? 'StarTranslator-Glossary.xlsx' : '', extensions: ['xlsx', 'xlsm', 'csv', 'tsv', 'json'] })
  return paths[0] || ''
})
// 由渲染进程把拖入文件的路径传回来（Electron 沙箱下拿不到真实路径）
ipcMain.handle('path-for-file', (_evt, file) => {
  try {
    const { webUtils } = require('electron')
    return webUtils.getPathForFile(file)
  } catch (_) {
    return file.path || ''
  }
})

/* ---------- 无边框窗口控制 ---------- */
ipcMain.handle('window-minimize', () => mainWindow && mainWindow.minimize())

ipcMain.handle('window-maximize', () => {
  if (!mainWindow) return false
  if (mainWindow.isMaximized()) mainWindow.unmaximize()
  else mainWindow.maximize()
  return mainWindow.isMaximized()
})

ipcMain.handle('window-close', () => !maintenanceBusy && mainWindow && mainWindow.close())
ipcMain.handle('window-close-ready', event => windowCloseGuard?.ready(event.sender) || false)
ipcMain.handle('window-close-answer', (event, token, accepted) => windowCloseGuard?.answer(event.sender, token, accepted) || false)

/* ---------- 导出目录 ---------- */
ipcMain.handle('pick-directory', async (_evt, defaultPath) => {
  const paths = await pickCustom({ title: '选择导出位置', mode: 'directory', directory: defaultPath || '', extensions: [] })
  return paths[0] || ''
})
/* ---------- 术语表来源持久化 ---------- */
function glossarySourcesFile() {
  return path.join(app.getPath('userData'), 'glossary-sources.json')
}

ipcMain.handle('get-glossary-sources', () => {
  try {
    const raw = fs.readFileSync(glossarySourcesFile(), 'utf-8')
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch (_) {
    return []
  }
})

ipcMain.handle('set-glossary-sources', (_evt, sources) => {
  try {
    const arr = Array.isArray(sources) ? sources : []
    fs.writeFileSync(glossarySourcesFile(), JSON.stringify(arr, null, 2), 'utf-8')
    return true
  } catch (e) {
    runtimeLog.error('[glossary-sources]', e)
    return false
  }
})

function createWindow() {
  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
  const size = require('./lib/window-size').defaultWindowSize(display.workAreaSize)
  mainWindow = new BrowserWindow({
    ...size,
    center: true,
    frame: false,          // 无边框，顶栏由渲染进程自绘
    show: false,           // 等首帧画好再显示，避免白闪
    title: `星译官 v${app.getVersion()} — 中英技术文档翻译与审校工作台`,
    icon: iconPath(),
    backgroundColor: '#0f1720',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  mainWindow.setMenuBarVisibility(false)
  mainWindow.once('ready-to-show', () => {
    mainWindow.unmaximize()
    mainWindow.setSize(size.width, size.height)
    mainWindow.center()
    mainWindow.show()
  })
  mainWindow.on('maximize', () => mainWindow.webContents.send('window-maximized', true))
  mainWindow.on('unmaximize', () => mainWindow.webContents.send('window-maximized', false))
  windowCloseGuard = require('./lib/window-close').installWindowCloseGuard(mainWindow)
  mainWindow.on('close', event => { if (maintenanceBusy) event.preventDefault() })
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'))
}

app.whenReady().then(async () => {
  // 让任务栏按 appId 归组并取用快捷方式图标（Windows）
  if (process.platform === 'win32') app.setAppUserModelId('tech.novastar.novaterm')
  pickCustom = installFilePicker(() => mainWindow, iconPath)
  createWindow()
  try {
    await startBackend()
    modelMonitor.start()
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('backend-ready', backendPort)
  } catch (e) {
    modelMonitor.backendUnavailable('后端启动失败，请重新启动软件。')
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('backend-error', String(e.message || e))
  }
})

app.on('window-all-closed', () => {
  stopBackend()
  app.quit()
})

app.on('will-quit', stopBackend)

}
