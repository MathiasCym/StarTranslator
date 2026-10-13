const { BrowserWindow, ipcMain, app, shell, screen } = require('electron')
const fs = require('node:fs/promises'), path = require('node:path')
const { isTemporaryOfficeFile, temporaryFileMessage } = require('../renderer/document-input')

function installFilePicker(getParent, icon) {
  const sessions = new Map()
  const get = event => {
    const session = sessions.get(event.sender.id)
    if (!session) throw new Error('文件窗口已关闭。')
    return session
  }
  const absolute = value => {
    if (typeof value !== 'string' || !path.isAbsolute(value) || value.includes('\0')) throw new Error('请输入完整的文件夹路径。')
    return path.normalize(value)
  }
  const resolveShortcut = async value => {
    let target = absolute(value)
    const seen = new Set()
    for (let depth = 0; path.extname(target).toLowerCase() === '.lnk'; depth++) {
      const identity = target.toLowerCase()
      if (depth >= 8 || seen.has(identity)) throw new Error('快捷方式目标无效或存在循环。')
      seen.add(identity)
      let link
      try { link = shell.readShortcutLink(target) } catch { throw new Error('无法读取这个快捷方式。') }
      if (!link.target) throw new Error('快捷方式没有可用目标。')
      target = absolute(path.isAbsolute(link.target) ? link.target : path.resolve(link.cwd || path.dirname(target), link.target))
    }
    return target
  }
  const preferences = path.join(app.getPath('userData'), 'file-picker.json')
  let lastDirectory = ''
  fs.readFile(preferences, 'utf8').then(raw => { lastDirectory = JSON.parse(raw).directory || '' }).catch(() => {})
  ipcMain.handle('picker-options', async event => {
    const { options } = get(event)
    const locations = ['desktop', 'documents', 'downloads', 'home'].map(key => ({
      name: { desktop: '桌面', documents: '文档', downloads: '下载', home: '用户文件夹' }[key], path: app.getPath(key),
    }))
    if (lastDirectory) locations.unshift({ name: '最近位置', path: lastDirectory })
    const drives = await Promise.all(Array.from({ length: 24 }, (_, i) => String.fromCharCode(67 + i) + ':\\').map(async dir => {
      try { await fs.access(dir); return { name: dir.slice(0, 2) + ' 磁盘', path: dir } } catch { return null }
    }))
    let directory = options.directory || lastDirectory || app.getPath('desktop')
    try { directory = await resolveShortcut(directory) } catch {}
    // Installation targets may not exist yet; browse from their nearest parent.
    while (!(await fs.stat(directory).catch(() => null))?.isDirectory()) {
      const parent = path.dirname(directory)
      if (parent === directory) { directory = app.getPath('desktop'); break }
      directory = parent
    }
    return { ...options, directory, locations: [...locations, ...drives.filter(Boolean)] }
  })
  ipcMain.handle('picker-list', async (event, directory) => {
    const { options } = get(event)
    directory = await resolveShortcut(directory)
    const entries = await fs.readdir(directory, { withFileTypes: true })
    const files = []
    // Bound metadata reads so large/shared folders do not start thousands of requests at once.
    for (let offset = 0; offset < entries.length; offset += 24) {
      const batch = await Promise.all(entries.slice(offset, offset + 24).map(async entry => {
        // Read link targets without executing shortcut programs or arguments.
        let folder = entry.isDirectory(), regular = entry.isFile()
        const shortcut = regular && path.extname(entry.name).toLowerCase() === '.lnk'
        let target = path.join(directory, entry.name)
        let stat
        if (entry.isSymbolicLink() || shortcut) {
          try { if (shortcut) target = await resolveShortcut(target); stat = await fs.stat(target); folder = stat.isDirectory(); regular = stat.isFile() } catch { return null }
        }
        if (!folder && (!regular || options.mode === 'directory' || (shortcut && options.mode === 'save') || !options.extensions.includes(path.extname(target).slice(1).toLowerCase()))) return null
        if (!folder && isTemporaryOfficeFile(target)) return null
        stat ||= await fs.stat(target).catch(() => null)
        return { name: shortcut ? entry.name.slice(0, -4) : entry.name, path: target, directory: folder, shortcut,
          targetName: shortcut && !folder ? path.basename(target) : undefined,
          modified: stat?.mtimeMs ?? null, size: folder ? null : stat?.size ?? null,
          type: folder ? '' : path.extname(target).slice(1).toLowerCase() }
      }))
      files.push(...batch.filter(Boolean))
    }
    files.sort((a, b) => Number(b.directory) - Number(a.directory) || a.name.localeCompare(b.name, 'zh-CN', { numeric: true }))
    return { directory, parent: path.dirname(directory), files }
  })
  ipcMain.handle('picker-mkdir', async (event, directory, name) => {
    get(event)
    if (typeof name !== 'string' || !name.trim() || /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name) || name === '.' || name === '..' || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(name)) throw new Error('文件夹名称无效。')
    const target = path.join(absolute(directory), name)
    await fs.mkdir(target)
    return target
  })
  ipcMain.handle('picker-confirm', async (event, input) => {
    const session = get(event), { options } = session
    let paths, directory
    if (options.mode === 'save') {
      directory = absolute(input.directory)
      let name = String(input.name || '').trim()
      if (!name || /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(name)) throw new Error('请输入有效的文件名。')
      if (!path.extname(name)) name += '.' + options.extensions[0]
      if (!options.extensions.includes(path.extname(name).slice(1).toLowerCase())) throw new Error('请选择支持的文件类型。')
      const target = path.join(directory, name)
      if (isTemporaryOfficeFile(name)) throw new Error('请使用不带“~$”前缀的文件名。')
      await fs.access(directory)
      let existing
      try { existing = await fs.stat(target) } catch (error) { if (error.code !== 'ENOENT') throw error }
      if (existing) {
        if (!existing.isFile()) throw new Error('此名称已被文件夹占用。')
        if (!input.overwrite) { session.overwrite = target; return { overwrite: true, name } }
        if (session.overwrite !== target) throw new Error('文件名已改变，请重新确认覆盖。')
      }
      await fs.access(directory, require('node:fs').constants.W_OK)
      paths = [target]
    } else {
      paths = options.mode === 'directory' ? [await resolveShortcut(input.directory)] : Array.isArray(input.paths) ? [...new Set(await Promise.all(input.paths.map(resolveShortcut)))] : []
      if (!paths.length || (!options.multiple && paths.length !== 1)) throw new Error('请选择文件。')
      for (const target of paths) {
        if (options.mode !== 'directory' && isTemporaryOfficeFile(target)) throw new Error(temporaryFileMessage)
        const stat = await fs.stat(target)
        if (options.mode === 'directory' ? !stat.isDirectory() : !stat.isFile()) throw new Error('选择的文件或文件夹无效。')
        if (options.mode !== 'directory' && !options.extensions.includes(path.extname(target).slice(1).toLowerCase())) throw new Error('选择的文件类型不受支持。')
        await fs.access(target, require('node:fs').constants.R_OK)
      }
      directory = options.mode === 'directory' ? paths[0] : path.dirname(paths[0])
    }
    lastDirectory = directory
    await fs.writeFile(preferences, JSON.stringify({ directory })).catch(() => {})
    // Let the renderer receive its successful result before destroying its window.
    setTimeout(() => session.finish(paths), 80)
    return { done: true }
  })
  ipcMain.handle('picker-cancel', event => { const session = get(event); setTimeout(() => session.finish([]), 80); return true })
  return options => new Promise(resolve => {
    const parent = getParent()
    const work = (parent ? screen.getDisplayMatching(parent.getBounds()) : screen.getDisplayNearestPoint(screen.getCursorScreenPoint())).workArea
    const width = Math.min(1060, Math.max(600, work.width - 64)), height = Math.min(760, Math.max(420, work.height - 64))
    const win = new BrowserWindow({ parent, modal: true, width, height, minWidth: Math.min(700, width), minHeight: Math.min(500, height),
      x: work.x + Math.round((work.width - width) / 2), y: work.y + Math.round((work.height - height) / 2),
      frame: false, show: false, resizable: true, backgroundColor: '#102238', icon: icon(),
      webPreferences: { preload: path.join(__dirname, '../picker-preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
    })
    const id = win.webContents.id
    let settled = false
    const finish = paths => {
      if (settled) return
      settled = true; sessions.delete(id); resolve(paths)
      if (!win.isDestroyed()) win.close()
    }
    sessions.set(id, { options, finish })
    win.on('closed', () => finish([]))
    win.once('ready-to-show', () => win.show())
    win.loadFile(path.join(__dirname, '../renderer/file-picker.html')).catch(() => finish([]))
  })
}
module.exports = { installFilePicker }
