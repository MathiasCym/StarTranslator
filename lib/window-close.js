const { randomUUID } = require('node:crypto')

// Keep Alt+F4, taskbar Close and the title-bar button on the same renderer flow.
function installWindowCloseGuard(win) {
  let ready = false, request = null, approved = false
  const owns = sender => !win.isDestroyed() && sender === win.webContents
  win.on('close', event => {
    if (approved || !ready || win.webContents.isDestroyed()) return
    event.preventDefault()
    if (request) return
    request = randomUUID()
    win.webContents.send('window-close-request', request)
  })
  win.webContents.on('did-start-loading', () => { ready = false; request = null; approved = false })
  win.webContents.on('render-process-gone', () => { ready = false; request = null })
  return {
    ready(sender) { if (!owns(sender)) return false; ready = true; return true },
    answer(sender, token, accepted) {
      if (!owns(sender) || !request || token !== request || typeof accepted !== 'boolean') return false
      request = null
      if (accepted) { approved = true; win.close() }
      return true
    }
  }
}
module.exports = { installWindowCloseGuard }
