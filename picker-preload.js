const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('picker', {
  options: () => ipcRenderer.invoke('picker-options'),
  list: directory => ipcRenderer.invoke('picker-list', directory),
  mkdir: (directory, name) => ipcRenderer.invoke('picker-mkdir', directory, name),
  confirm: input => ipcRenderer.invoke('picker-confirm', input),
  cancel: () => ipcRenderer.invoke('picker-cancel'),
})
