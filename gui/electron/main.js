const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const { PythonBridge } = require("./python-bridge");

let mainWindow;
let pythonBridge;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1024,
    height: 768,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    backgroundColor: "#1a1a2e",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Load built files if they exist, otherwise try Vite dev server
  const fs = require("fs");
  const distIndex = path.join(__dirname, "..", "dist", "index.html");
  if (fs.existsSync(distIndex)) {
    mainWindow.loadFile(distIndex);
  } else {
    mainWindow.loadURL("http://localhost:5173");
  }

  pythonBridge = new PythonBridge();
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (pythonBridge) pythonBridge.kill();
  app.quit();
});

// ---------------------------------------------------------------------------
// Window controls (frameless window)
// ---------------------------------------------------------------------------
ipcMain.on("window:minimize", () => mainWindow?.minimize());
ipcMain.on("window:maximize", () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow?.maximize();
  }
});
ipcMain.on("window:close", () => mainWindow?.close());

// ---------------------------------------------------------------------------
// Folder picker
// ---------------------------------------------------------------------------
ipcMain.handle("dialog:openDirectory", async (_event, opts) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory"],
    title: opts?.title || "Select Folder",
    defaultPath: opts?.defaultPath || undefined,
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle("dialog:openFile", async (_event, opts) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    title: opts?.title || "Select File",
    defaultPath: opts?.defaultPath || undefined,
    filters: opts?.filters || [],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// ---------------------------------------------------------------------------
// Python bridge IPC
// ---------------------------------------------------------------------------
ipcMain.handle("python:scan", async (_event, args) => {
  return pythonBridge.runScanOnly(args);
});

ipcMain.handle("python:process", async (_event, args) => {
  pythonBridge.startProcess(args, (line) => {
    mainWindow?.webContents.send("python:progress", line);
  });
});

ipcMain.on("python:kill", () => {
  pythonBridge.kill();
});

// ---------------------------------------------------------------------------
// Persistent settings
// ---------------------------------------------------------------------------
let store;
async function getStore() {
  if (!store) {
    const ElectronStore = (await import("electron-store")).default;
    store = new ElectronStore({ name: "clothing-tool-settings" });
  }
  return store;
}

ipcMain.handle("settings:get", async (_event, key) => {
  const s = await getStore();
  return s.get(key);
});

ipcMain.handle("settings:set", async (_event, key, value) => {
  const s = await getStore();
  s.set(key, value);
});

ipcMain.handle("settings:getAll", async () => {
  const s = await getStore();
  return s.store;
});
