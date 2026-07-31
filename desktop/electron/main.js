/**
 * J.A.R.V.I.S Electron Desktop - Main Process
 * Stark Industries - Ollama Brain
 */

const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain, shell, dialog, nativeImage } = require('electron');
const path = require('path');
const { spawn, exec } = require('child_process');
const fs = require('fs');
const http = require('http');

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let ollamaProcess = null;
let isQuitting = false;

const isDev = process.argv.includes('--dev');
const WEB_PORT = process.env.WEB_PORT || 8000;
const OLLAMA_HOST = process.env.OLLAMA_HOST || 'http://localhost:11434';

// Store - simple JSON
let store = {
  model: 'jarvis',
  voiceEnabled: false,
  windowBounds: { width: 1200, height: 800 }
};
try {
  const Store = require('electron-store');
  const s = new Store();
  store = { ...store, ...s.store };
  store.save = (k,v) => s.set(k,v);
} catch {
  store.save = () => {};
}

function checkPort(port) {
  return new Promise((resolve) => {
    const req = http.get(`http://localhost:${port}/api/status`, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => { req.destroy(); resolve(false); });
  });
}

async function checkOllama() {
  return new Promise((resolve) => {
    const req = http.get(`${OLLAMA_HOST}/api/tags`, (res) => resolve(res.statusCode === 200));
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => { req.destroy(); resolve(false); });
  });
}

function startPythonBackend() {
  if (pythonProcess) return;
  
  const rootPath = isDev ? path.join(__dirname, '../../') : path.join(process.resourcesPath, 'app');
  const scriptPath = path.join(rootPath, 'web/server.py');
  
  // Find python
  const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
  
  console.log('Starting Python backend:', scriptPath);
  
  pythonProcess = spawn(pythonCmd, [scriptPath], {
    cwd: rootPath,
    env: { ...process.env, WEB_PORT: WEB_PORT, OLLAMA_HOST: OLLAMA_HOST },
    detached: false
  });
  
  pythonProcess.stdout.on('data', (data) => console.log(`[PY] ${data}`));
  pythonProcess.stderr.on('data', (data) => console.error(`[PY-ERR] ${data}`));
  pythonProcess.on('close', (code) => {
    console.log(`Python backend exited with code ${code}`);
    pythonProcess = null;
  });
}

async function createWindow() {
  const iconPath = path.join(__dirname, 'assets/icon.png');
  let icon = undefined;
  if (fs.existsSync(iconPath)) {
    icon = nativeImage.createFromPath(iconPath);
  }
  
  mainWindow = new BrowserWindow({
    width: store.windowBounds?.width || 1200,
    height: store.windowBounds?.height || 800,
    minWidth: 1000,
    minHeight: 600,
    icon: icon,
    title: 'J.A.R.V.I.S',
    backgroundColor: '#0a0e13',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      enableRemoteModule: false
    }
  });
  
  // Loading screen
  mainWindow.loadURL(`data:text/html,
    <body style="background:#0a0e13;color:#00d4ff;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
      <div style="text-align:center">
        <div style="width:80px;height:80px;border:2px solid #00d4ff;border-top:2px solid transparent;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px"></div>
        <style>@keyframes spin{to{transform:rotate(360deg)}}</style>
        <h2 style="font-family:Orbitron">J.A.R.V.I.S</h2>
        <p>Initializing neural pathways...</p>
        <p style="font-size:12px;opacity:0.6" id="status">Checking Ollama...</p>
        <script>
          let dots=0;
          setInterval(()=>{dots=(dots+1)%4; document.getElementById('status').textContent='Checking Ollama'+'.'.repeat(dots)},300)
        </script>
      </div>
    </body>
  `);
  
  // Start backend if not running
  const webRunning = await checkPort(WEB_PORT);
  if (!webRunning) {
    startPythonBackend();
  }
  
  // Wait for web to be ready, then load
  let attempts = 0;
  const waitForWeb = async () => {
    attempts++;
    if (await checkPort(WEB_PORT)) {
      mainWindow.loadURL(`http://localhost:${WEB_PORT}`);
      mainWindow.show();
      mainWindow.focus();
    } else if (attempts < 30) {
      setTimeout(waitForWeb, 1000);
    } else {
      dialog.showErrorBox('JARVIS Error', 'Could not start web backend. Please run manually: python web/server.py');
      mainWindow.loadURL(`http://localhost:${WEB_PORT}`);
      mainWindow.show();
    }
  };
  setTimeout(waitForWeb, 1500);
  
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      if (process.platform === 'darwin') {
        app.dock.hide();
      }
      return false;
    }
  });
  
  mainWindow.on('resize', () => {
    if (mainWindow) {
      store.save('windowBounds', mainWindow.getBounds());
    }
  });
  
  // Dev tools in dev mode
  if (isDev) {
    mainWindow.webContents.openDevTools();
  }
}

function createTray() {
  const iconPath = path.join(__dirname, 'assets/icon.png');
  let trayIcon = nativeImage.createFromPath(iconPath);
  if (process.platform === 'darwin' || process.platform === 'linux') {
    trayIcon = trayIcon.resize({ width: 16, height: 16 });
  }
  
  tray = new Tray(trayIcon);
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show J.A.R.V.I.S', click: () => { mainWindow.show(); mainWindow.focus(); } },
    { label: 'Voice: OFF', id: 'voice-toggle', click: () => toggleVoice() },
    { type: 'separator' },
    { label: 'Ollama Status', click: async () => {
      const ok = await checkOllama();
      dialog.showMessageBox(mainWindow, {
        type: ok ? 'info' : 'warning',
        title: 'Ollama Status',
        message: ok ? 'Ollama is online, Sir.' : 'Ollama offline. Run: ollama serve',
        detail: `Host: ${OLLAMA_HOST}`
      });
    }},
    { label: 'Open Workspace', click: () => {
      const wsPath = isDev ? path.join(__dirname, '../../workspace') : path.join(process.resourcesPath, 'app/workspace');
      shell.openPath(wsPath);
    }},
    { type: 'separator' },
    { label: 'Quit JARVIS', click: () => { isQuitting = true; app.quit(); } }
  ]);
  
  tray.setToolTip('J.A.R.V.I.S - At your service, Sir');
  tray.setContextMenu(contextMenu);
  tray.on('click', () => { mainWindow.show(); mainWindow.focus(); });
  tray.on('double-click', () => { mainWindow.show(); mainWindow.focus(); });
}

function toggleVoice() {
  store.voiceEnabled = !store.voiceEnabled;
  store.save('voiceEnabled', store.voiceEnabled);
  if (tray) {
    const menu = tray.getContextMenu();
    const item = menu.getMenuItemById('voice-toggle');
    if (item) item.label = `Voice: ${store.voiceEnabled ? 'ON' : 'OFF'}`;
    tray.setContextMenu(menu);
  }
  return store.voiceEnabled;
}

// IPC
ipcMain.handle('get-version', () => app.getVersion());
ipcMain.handle('get-status', async () => ({
  ollama: await checkOllama(),
  web: await checkPort(WEB_PORT),
  model: store.model,
  voice: store.voiceEnabled
}));
ipcMain.handle('check-ollama', checkOllama);
ipcMain.handle('toggle-voice', () => toggleVoice());
ipcMain.handle('get-settings', () => store);
ipcMain.handle('set-settings', (e, k, v) => { store[k]=v; store.save(k,v); return true; });
ipcMain.handle('open-external', (e, url) => shell.openExternal(url));
ipcMain.on('minimize', () => mainWindow.minimize());
ipcMain.on('maximize', () => mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize());
ipcMain.on('close', () => mainWindow.close());
ipcMain.on('hide-to-tray', () => mainWindow.hide());

// App lifecycle
app.whenReady().then(() => {
  createWindow();
  createTray();
  
  // Global shortcut - Ctrl+Shift+J / Cmd+Shift+J
  const shortcut = 'CommandOrControl+Shift+J';
  const registered = globalShortcut.register(shortcut, () => {
    if (mainWindow.isVisible()) {
      mainWindow.hide();
    } else {
      mainWindow.show();
      mainWindow.focus();
    }
  });
  console.log(`Global shortcut ${shortcut}: ${registered ? 'registered' : 'failed'}`);
  
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else mainWindow.show();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    // Keep running in tray
  }
});

app.on('before-quit', () => {
  isQuitting = true;
  globalShortcut.unregisterAll();
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
  }
  if (tray) tray.destroy();
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});
