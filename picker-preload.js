const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('picker', {
  options: () => ipcRenderer.invoke('picker-options'),
  list: directory => ipcRenderer.invoke('picker-list', directory),
  mkdir: (directory, name) => ipcRenderer.invoke('picker-mkdir', directory, name),
  confirm: input => ipcRenderer.invoke('picker-confirm', input),
  cancel: () => ipcRenderer.invoke('picker-cancel'),
})

contextBridge.exposeInMainWorld('appearance', {
  initial: ipcRenderer.sendSync('appearance-theme'),
  set: value => ipcRenderer.invoke('set-appearance-theme', value),
  onChange: callback => ipcRenderer.on('appearance-theme-changed', (_event, value) => callback(value)),
})
