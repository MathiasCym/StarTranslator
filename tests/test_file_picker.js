const test = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs/promises'), path = require('node:path'), os = require('node:os'), vm = require('node:vm')
const policy = require('../renderer/document-input')
const { EventEmitter } = require('node:events'), { createRequire } = require('node:module')
const sourceFile = path.resolve(__dirname, '../lib/file-picker.js')
async function harness(root, parent = null) {
  const handlers = new Map(), module = { exports:{} }, windows = [], requirePicker = createRequire(sourceFile)
  class Window extends EventEmitter {
    constructor(options) { super(); this.options = options; this.webContents = { id:windows.length + 1 }; this.destroyed = false; this.focused = true; this.minimized = false; windows.push(this) }
    loadFile() { return Promise.resolve() }
    show() {} isDestroyed() { return this.destroyed } isFocused() { return this.focused } isMinimized() { return this.minimized }
    close() { if (this.blurBeforeClose) this.focused = false; this.emit('close'); this.beforeClosed?.(); this.destroyed = true; this.emit('closed') }
  }
  const display = { scaleFactor:1, workArea:{ x:0, y:0, width:1920, height:1040 } }
  const mock = { BrowserWindow:Window, ipcMain:{ handle:(name, fn) => handlers.set(name, fn) }, app:{ getPath:() => root },
    screen:{ getDisplayMatching:() => display, getDisplayNearestPoint:() => display, getCursorScreenPoint:() => ({ x:0, y:0 }) } }
  vm.runInNewContext(await fs.readFile(sourceFile, 'utf8'), {
    module, __dirname:path.dirname(sourceFile), setTimeout, setImmediate,
    require:name => name === 'electron' ? mock : name === '../renderer/document-input' ? policy : requirePicker(name),
  })
  return { handlers, windows, picker:module.exports.installFilePicker(() => parent, () => undefined) }
}
function owner() {
  return { minimized:false, destroyed:false, visible:true, restored:0, focused:0,
    getBounds:() => ({ x:0, y:0, width:1000, height:700 }),
    isDestroyed() { return this.destroyed }, isVisible() { return this.visible }, isMinimized() { return this.minimized },
    restore() { this.minimized = false; this.restored++ }, focus() { this.focused++ } }
}

test('custom picker hides owner files and rejects a forced selection before reading it', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'star-picker-'))
  try {
    const lock = path.join(root, '~$中文原稿.pptx'), source = path.join(root, '中文原稿.pptx')
    await fs.writeFile(lock, 'Office owner record'); await fs.writeFile(source, 'Real document fixture')
    const modified = new Date('2026-10-01T08:00:00Z')
    await fs.utimes(source, modified, modified)
    await fs.mkdir(path.join(root, '~$folder'))
    const { handlers, windows, picker } = await harness(root)
    const pending = picker({ mode:'open', multiple:true, extensions:['docx','pptx'] }), event = { sender:{ id:1 } }
    const entries = await handlers.get('picker-list')(event, root)
    const document = entries.files.find(f => f.name === '中文原稿.pptx')
    assert(document)
    assert.equal(document.size, Buffer.byteLength('Real document fixture'))
    assert.equal(document.modified, modified.getTime())
    assert.equal(document.type, 'pptx')
    assert(entries.files.some(f => f.name === '~$folder' && f.directory))
    assert(!entries.files.some(f => f.name.startsWith('~$') && !f.directory))
    await assert.rejects(handlers.get('picker-confirm')(event, { paths:[lock] }), /临时锁文件/)
    assert(!windows[0].destroyed, 'An invalid selection should remain recoverable')
    await handlers.get('picker-confirm')(event, { paths:[source] })
    assert.deepEqual(Array.from(await pending), [source])
  } finally {
    assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()))
    assert(path.basename(root).startsWith('star-picker-'))
    await fs.rm(root, { recursive:true, force:true })
  }
})

test('closing an active modal restores its owner after native teardown, before returning', async () => {
  for (const mode of ['cancel', 'native-close', 'open', 'save', 'directory']) {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'star-picker-lifecycle-'))
    try {
      const parent = owner(), { picker, windows, handlers } = await harness(root, parent)
      const pending = picker({ mode:['open','save','directory'].includes(mode) ? mode : 'open', extensions:['txt'], multiple:false })
      const win = windows[0], event = { sender:win.webContents }
      // Native teardown can blur a confirmed picker before emitting close.
      win.blurBeforeClose = ['open','save','directory'].includes(mode)
      assert.equal(win.options.parent, parent)
      assert.equal(win.options.modal, true)
      win.beforeClosed = () => { parent.minimized = true; assert.equal(parent.focused, 0, 'Native modal must finish closing before owner activation') }
      if (mode === 'native-close') win.close()
      else if (mode === 'cancel') handlers.get('picker-cancel')(event)
      else if (mode === 'directory') await handlers.get('picker-confirm')(event, { directory:root })
      else if (mode === 'save') await handlers.get('picker-confirm')(event, { directory:root, name:'new.txt' })
      else { const file = path.join(root, 'source.txt'); await fs.writeFile(file, 'fixture'); await handlers.get('picker-confirm')(event, { paths:[file] }) }
      const chosen = Array.from(await pending)
      assert.equal(parent.minimized, false, mode)
      assert.equal(parent.restored, 1, mode)
      assert.equal(parent.focused, 1, mode)
      assert.equal(win.options.skipTaskbar, true)
      assert.equal(win.options.minimizable, false)
      assert.equal(win.destroyed, true)
      assert.deepEqual(chosen, mode === 'directory' ? [root] : mode === 'save' ? [path.join(root, 'new.txt')] : mode === 'open' ? [path.join(root, 'source.txt')] : [])
      win.emit('closed')
      assert.equal(parent.restored, 1, 'Duplicate teardown must not restore twice')
    } finally {
      assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()))
      assert(path.basename(root).startsWith('star-picker-lifecycle-'))
      await fs.rm(root, { recursive:true, force:true })
    }
  }
})

test('closing an inactive picker does not undo intentional minimization or activate a hidden/destroyed owner', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'star-picker-lifecycle-'))
  try {
    for (const state of ['inactive', 'minimized-picker', 'hidden-owner', 'destroyed-owner', 'no-owner']) {
      const parent = state === 'no-owner' ? null : owner()
      if (state === 'hidden-owner') parent.visible = false
      const { picker, windows } = await harness(root, parent)
      const pending = picker({ mode:'open', extensions:['txt'] }), win = windows[0]
      if (state === 'inactive') { win.focused = false; parent.minimized = true }
      if (state === 'minimized-picker') { win.minimized = true; parent.minimized = true }
      if (state === 'destroyed-owner') parent.destroyed = true
      win.close(); assert.deepEqual(Array.from(await pending), [])
      if (parent) { assert.equal(parent.restored, 0, state); assert.equal(parent.focused, 0, state) }
    }
  } finally {
    assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()))
    assert(path.basename(root).startsWith('star-picker-lifecycle-'))
    await fs.rm(root, { recursive:true, force:true })
  }
})
