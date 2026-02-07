const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("api", {
  // Window controls
  minimize: () => ipcRenderer.send("window:minimize"),
  maximize: () => ipcRenderer.send("window:maximize"),
  close: () => ipcRenderer.send("window:close"),

  // Folder/file pickers
  openDirectory: (opts) => ipcRenderer.invoke("dialog:openDirectory", opts),
  openFile: (opts) => ipcRenderer.invoke("dialog:openFile", opts),

  // Python bridge
  scan: (args) => ipcRenderer.invoke("python:scan", args),
  process: (args) => ipcRenderer.invoke("python:process", args),
  kill: () => ipcRenderer.send("python:kill"),
  onProgress: (callback) => {
    const handler = (_event, line) => callback(line);
    ipcRenderer.on("python:progress", handler);
    return () => ipcRenderer.removeListener("python:progress", handler);
  },

  // Persistent settings
  getSetting: (key) => ipcRenderer.invoke("settings:get", key),
  setSetting: (key, value) => ipcRenderer.invoke("settings:set", key, value),
  getAllSettings: () => ipcRenderer.invoke("settings:getAll"),
});
