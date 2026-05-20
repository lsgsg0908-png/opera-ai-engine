const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('opera', {
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  readFile: (p) => ipcRenderer.invoke('read-file', p),
  deleteFile: (p) => ipcRenderer.invoke('delete-file', p),
  submitTask: (d) => ipcRenderer.invoke('submit-task', d),
  getTasks: () => ipcRenderer.invoke('get-tasks'),
  getMemory: () => ipcRenderer.invoke('get-memory'),
  saveMemory: (d) => ipcRenderer.invoke('save-memory', d),
  startEngine: () => ipcRenderer.invoke('start-engine'),
  stopEngine: () => ipcRenderer.invoke('stop-engine'),
  requestApproval: (d) => ipcRenderer.invoke('request-approval', d),
  onTaskUpdate: (cb) => ipcRenderer.on('task-update', (_, d) => cb(d)),
  onEngineLog: (cb) => ipcRenderer.on('engine-log', (_, d) => cb(d)),
  onEngineStatus: (cb) => ipcRenderer.on('engine-status', (_, d) => cb(d)),
});