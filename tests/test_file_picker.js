const test = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs/promises'), path = require('node:path'), os = require('node:os'), vm = require('node:vm')
const policy = require('../renderer/document-input')

test('custom picker hides owner files and rejects a forced selection before reading it', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'star-picker-'))
  try {
    const lock = path.join(root, '~$中文原稿.pptx'), source = path.join(root, '中文原稿.pptx')
    await fs.writeFile(lock, 'Office owner record'); await fs.writeFile(source, 'Real document fixture')
    const modified = new Date('2026-10-01T08:00:00Z')
    await fs.utimes(source, modified, modified)
    await fs.mkdir(path.join(root, '~$folder'))
    const handlers = new Map(), module = { exports: {} }, windows = []
    class Window {
      constructor() { this.webContents = { id: windows.length + 1 }; windows.push(this); this.destroyed = false }
      on() {} once() {} loadFile() { return Promise.resolve() } isDestroyed() { return this.destroyed } close() { this.destroyed = true }
    }
    const mock = { BrowserWindow:Window, ipcMain:{ handle:(name, fn) => handlers.set(name, fn) }, app:{ getPath:() => root } }
    vm.runInNewContext(await fs.readFile(path.resolve(__dirname, '../lib/file-picker.js'), 'utf8'), {
      module, __dirname:path.resolve(__dirname, '../lib'), setTimeout,
      require:name => name === 'electron' ? mock : name === '../renderer/document-input' ? policy : require(name),
    })
    const picker = module.exports.installFilePicker(() => null, () => undefined)
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
