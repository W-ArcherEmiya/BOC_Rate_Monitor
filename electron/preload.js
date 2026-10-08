const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('rateMonitor', {
  getCurrentRate: (payload) => ipcRenderer.invoke('rates:get-current', payload),
  getHistory: (payload) => ipcRenderer.invoke('rates:get-history', payload),
  startDrag: () => ipcRenderer.send('window:drag-start'),
  moveBy: (payload) => ipcRenderer.send('window:move-by', payload),
  endDrag: () => ipcRenderer.send('window:drag-end'),
  createWindow: (payload) => ipcRenderer.send('window:create', payload),
  showMenu: (payload) => ipcRenderer.send('menu:show', payload),
  onMenuAction: (callback) => ipcRenderer.on('menu:action', (_event, payload) => callback(payload)),
  notify: (payload) => ipcRenderer.send('notify', payload)
});
