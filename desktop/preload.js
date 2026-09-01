/** Bridge between the VoiceOS renderer and the Electron shell. */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('voiceosDesktop', {
  platform: process.platform,
  quit: () => ipcRenderer.send('voiceos:quit'),
});
