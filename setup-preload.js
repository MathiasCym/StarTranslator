const { contextBridge, ipcRenderer } = require('electron')
contextBridge.exposeInMainWorld('setup', {
  info: () => ipcRenderer.invoke('setup-info'),
  pickDirectory: () => ipcRenderer.invoke('setup-pick-directory'),
  start: input => ipcRenderer.invoke('setup-start', input),
  close: () => ipcRenderer.invoke('setup-close'),
  minimize: () => ipcRenderer.invoke('setup-minimize'),
  launch: () => ipcRenderer.invoke('setup-launch'),
  onStatus: callback => ipcRenderer.on('setup-status', (_, value) => callback(value)),
})
