// JARVIS Electron Preload - Secure bridge
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvis', {
  // System
  getVersion: () => ipcRenderer.invoke('get-version'),
  getStatus: () => ipcRenderer.invoke('get-status'),
  
  // Ollama
  checkOllama: () => ipcRenderer.invoke('check-ollama'),
  startOllama: () => ipcRenderer.invoke('start-ollama'),
  
  // Window controls
  minimize: () => ipcRenderer.send('minimize'),
  maximize: () => ipcRenderer.send('maximize'),
  close: () => ipcRenderer.send('close'),
  hide: () => ipcRenderer.send('hide-to-tray'),
  
  // Voice
  toggleVoice: () => ipcRenderer.invoke('toggle-voice'),
  
  // Settings
  getSettings: () => ipcRenderer.invoke('get-settings'),
  setSettings: (key, value) => ipcRenderer.invoke('set-settings', key, value),
  
  // Events from main
  onShow: (cb) => ipcRenderer.on('show-window', cb),
  onTrayClick: (cb) => ipcRenderer.on('tray-click', cb),
  
  // Shell
  openExternal: (url) => ipcRenderer.invoke('open-external', url)
});
