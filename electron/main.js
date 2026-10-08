const { app, BrowserWindow, ipcMain, Menu, Notification, screen } = require('electron');
const path = require('path');
const cheerio = require('cheerio');

const WINDOW_WIDTH = 216;
const WINDOW_HEIGHT = 112;
const SNAP_DISTANCE = 14;
const SNAP_GAP = 0;
const dragBounds = new Map();

const currencyMeta = {
  '人民币': { code: 'CNY', flag: 'CN' },
  '英镑': { code: 'GBP', flag: 'GB' },
  '美元': { code: 'USD', flag: 'US' },
  '欧元': { code: 'EUR', flag: 'EU' },
  '日元': { code: 'JPY', flag: 'JP' },
  '港币': { code: 'HKD', flag: 'HK' },
  '澳大利亚元': { code: 'AUD', flag: 'AU' },
  '加拿大元': { code: 'CAD', flag: 'CA' },
  '瑞士法郎': { code: 'CHF', flag: 'CH' },
  '新加坡元': { code: 'SGD', flag: 'SG' }
};

function currencyCode(name) {
  return currencyMeta[name]?.code || name;
}

function clampBounds(bounds, workArea) {
  return {
    ...bounds,
    x: Math.max(workArea.x, Math.min(bounds.x, workArea.x + workArea.width - bounds.width)),
    y: Math.max(workArea.y, Math.min(bounds.y, workArea.y + workArea.height - bounds.height))
  };
}

function closestSnap(value, targets) {
  let closest = value;
  let distance = SNAP_DISTANCE + 1;
  for (const target of targets) {
    const nextDistance = Math.abs(value - target);
    if (nextDistance <= SNAP_DISTANCE && nextDistance < distance) {
      closest = target;
      distance = nextDistance;
    }
  }
  return closest;
}

function rangesTouch(aStart, aEnd, bStart, bEnd) {
  return aStart <= bEnd + SNAP_DISTANCE && bStart <= aEnd + SNAP_DISTANCE;
}

function snapBounds(win, bounds) {
  const display = screen.getDisplayMatching(bounds);
  const workArea = display.workArea;
  const xTargets = [workArea.x, workArea.x + workArea.width - bounds.width];
  const yTargets = [workArea.y, workArea.y + workArea.height - bounds.height];

  for (const other of BrowserWindow.getAllWindows()) {
    if (other.id === win.id || other.isDestroyed()) continue;
    const otherBounds = other.getBounds();
    if (screen.getDisplayMatching(otherBounds).id !== display.id) continue;

    const overlapsY = rangesTouch(bounds.y, bounds.y + bounds.height, otherBounds.y, otherBounds.y + otherBounds.height);
    const overlapsX = rangesTouch(bounds.x, bounds.x + bounds.width, otherBounds.x, otherBounds.x + otherBounds.width);

    if (overlapsY) {
      xTargets.push(otherBounds.x - SNAP_GAP - bounds.width);
      xTargets.push(otherBounds.x + otherBounds.width + SNAP_GAP);
      xTargets.push(otherBounds.x);
      xTargets.push(otherBounds.x + otherBounds.width - bounds.width);
    }

    if (overlapsX) {
      yTargets.push(otherBounds.y - SNAP_GAP - bounds.height);
      yTargets.push(otherBounds.y + otherBounds.height + SNAP_GAP);
      yTargets.push(otherBounds.y);
      yTargets.push(otherBounds.y + otherBounds.height - bounds.height);
    }
  }

  return clampBounds({
    ...bounds,
    x: closestSnap(bounds.x, xTargets),
    y: closestSnap(bounds.y, yTargets)
  }, workArea);
}

function attachedPosition(parentBounds) {
  const workArea = screen.getDisplayMatching(parentBounds).workArea;
  const candidates = [
    { x: parentBounds.x, y: parentBounds.y + parentBounds.height + SNAP_GAP },
    { x: parentBounds.x + parentBounds.width + SNAP_GAP, y: parentBounds.y },
    { x: parentBounds.x, y: parentBounds.y - WINDOW_HEIGHT - SNAP_GAP },
    { x: parentBounds.x - WINDOW_WIDTH - SNAP_GAP, y: parentBounds.y }
  ];
  const candidate = candidates.find((item) => (
    item.x >= workArea.x &&
    item.y >= workArea.y &&
    item.x + WINDOW_WIDTH <= workArea.x + workArea.width &&
    item.y + WINDOW_HEIGHT <= workArea.y + workArea.height
  )) || candidates[0];
  return clampBounds({ ...candidate, width: WINDOW_WIDTH, height: WINDOW_HEIGHT }, workArea);
}

function createWindow(options = {}) {
  const query = new URLSearchParams({
    base: options.base || '',
    quote: options.quote || '',
    x: String(options.x || ''),
    y: String(options.y || '')
  });

  const win = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    x: options.x,
    y: options.y,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    backgroundColor: '#00000000',
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, 'renderer.html'), { query: Object.fromEntries(query) });
  return win;
}

async function fetchBocRates() {
  const url = `https://www.boc.cn/sourcedb/whpj/index.html?_t=${Date.now()}`;
  const response = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      'Referer': 'https://www.boc.cn/sourcedb/whpj/',
      'Cache-Control': 'no-cache',
      'Pragma': 'no-cache'
    },
    signal: AbortSignal.timeout(8000)
  });

  const html = await response.text();
  const $ = cheerio.load(html);
  const rates = { '人民币': { rate: 1, updateTime: '' } };

  $('tr').each((_, row) => {
    const cells = $(row).find('td').map((__, cell) => $(cell).text().trim()).get();
    if (cells.length >= 8 && currencyMeta[cells[0]] && cells[0] !== '人民币') {
      const sellRate = Number.parseFloat(cells[3]);
      if (Number.isFinite(sellRate)) {
        const date = cells[6].match(/\d{4}[-/]\d{2}[-/]\d{2}/)?.[0] || '';
        rates[cells[0]] = { rate: sellRate / 100, updateTime: `${date} ${cells[7]}`.trim() };
      }
    }
  });

  return rates;
}

async function fetchMarketLatest(baseCurrency, quoteCurrency) {
  const base = currencyCode(baseCurrency);
  const quote = currencyCode(quoteCurrency);
  if (base === quote) {
    return { price: 1, updateTime: 'same currency' };
  }

  const params = new URLSearchParams({ base, symbols: quote });
  const response = await fetch(`https://api.frankfurter.dev/v1/latest?${params}`, {
    signal: AbortSignal.timeout(12000)
  });
  if (!response.ok) {
    throw new Error(`Market fallback failed: ${response.status}`);
  }

  const payload = await response.json();
  const price = Number(payload?.rates?.[quote]);
  return {
    price: Number.isFinite(price) ? price : null,
    updateTime: payload?.date || '',
    source: 'frankfurter',
    fetchedAt: Date.now()
  };
}

ipcMain.handle('rates:get-current', async (_event, { baseCurrency, quoteCurrency }) => {
  if (baseCurrency === quoteCurrency) {
    return { price: 1, updateTime: '', source: 'identity', fetchedAt: Date.now() };
  }
  try {
    const rates = await fetchBocRates();
    const base = rates[baseCurrency];
    const quote = rates[quoteCurrency];
    if (base && quote && quote.rate !== 0) {
      const times = [base.updateTime, quote.updateTime].filter(Boolean);
      return {
        price: base.rate / quote.rate,
        updateTime: [...new Set(times)].join(' / '),
        source: baseCurrency === '人民币' ? 'boc-inverse' : quoteCurrency === '人民币' ? 'boc-sell' : 'boc-cross',
        fetchedAt: Date.now()
      };
    }
  } catch {
    // Fall through to the market-rate fallback below.
  }

  return fetchMarketLatest(baseCurrency, quoteCurrency);
});

ipcMain.handle('rates:get-history', async (_event, { baseCurrency, quoteCurrency, days }) => {
  const base = currencyCode(baseCurrency);
  const quote = currencyCode(quoteCurrency);
  const end = new Date();
  const start = new Date(end.getTime() - Math.max(1, days) * 24 * 60 * 60 * 1000);
  const startText = start.toISOString().slice(0, 10);
  const endText = end.toISOString().slice(0, 10);

  if (base === quote) {
    const points = [];
    for (let timestamp = Date.parse(`${startText}T00:00:00Z`); timestamp <= Date.parse(`${endText}T00:00:00Z`); timestamp += 86400000) {
      points.push({ timestamp, price: 1, source: 'identity' });
    }
    return points;
  }

  const params = new URLSearchParams({
    from: startText,
    to: endText,
    base,
    quotes: quote
  });
  const response = await fetch(`https://api.frankfurter.dev/v2/rates?${params}`, {
    signal: AbortSignal.timeout(12000)
  });
  const payload = await response.json();
  return payload
    .filter((item) => item.quote === quote && item.rate != null)
    .map((item) => ({
      timestamp: new Date(`${item.date}T00:00:00Z`).getTime(),
      price: Number(item.rate),
      source: 'frankfurter'
    }));
});

ipcMain.on('window:create', (event, options = {}) => {
  const parent = BrowserWindow.fromWebContents(event.sender);
  const bounds = parent?.getBounds() || { x: 100, y: 100, height: WINDOW_HEIGHT };
  const position = attachedPosition({
    ...bounds,
    width: bounds.width || WINDOW_WIDTH,
    height: bounds.height || WINDOW_HEIGHT
  });
  createWindow({
    base: options.base || '美元',
    quote: options.quote || '人民币',
    x: position.x,
    y: position.y
  });
});

ipcMain.on('window:drag-start', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win) return;
  dragBounds.set(win.id, win.getBounds());
});

ipcMain.on('window:move-by', (event, { dx, dy }) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win) return;
  const bounds = win.getBounds();
  const virtualBounds = dragBounds.get(win.id) || bounds;
  const nextVirtualBounds = {
    ...virtualBounds,
    width: bounds.width,
    height: bounds.height,
    x: virtualBounds.x + dx,
    y: virtualBounds.y + dy
  };
  const workArea = screen.getDisplayMatching(nextVirtualBounds).workArea;
  const clampedVirtualBounds = clampBounds(nextVirtualBounds, workArea);
  dragBounds.set(win.id, clampedVirtualBounds);
  const next = snapBounds(win, clampedVirtualBounds);
  win.setBounds(next, false);
});

ipcMain.on('window:drag-end', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win) return;
  dragBounds.delete(win.id);
});

ipcMain.on('menu:show', (event, alerts = {}) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const template = [
    {
      label: '选择基准货币',
      submenu: Object.keys(currencyMeta).map((currency) => ({
        label: currency,
        type: 'radio',
        checked: currency === alerts.baseCurrency,
        click: () => event.sender.send('menu:action', { type: 'base', value: currency })
      }))
    },
    {
      label: '选择报价货币',
      submenu: Object.keys(currencyMeta).map((currency) => ({
        label: currency,
        type: 'radio',
        checked: currency === alerts.quoteCurrency,
        click: () => event.sender.send('menu:action', { type: 'quote', value: currency })
      }))
    },
    {
      label: '线图范围',
      submenu: [
        ['30min', 30 * 60],
        ['1h', 60 * 60],
        ['2h', 2 * 60 * 60],
        ['1d', 24 * 60 * 60],
        ['2d', 2 * 24 * 60 * 60],
        ['1周', 7 * 24 * 60 * 60],
        ['1个月', 30 * 24 * 60 * 60],
        ['3个月', 90 * 24 * 60 * 60],
        ['6个月', 180 * 24 * 60 * 60],
        ['1年', 365 * 24 * 60 * 60],
        ['2年', 2 * 365 * 24 * 60 * 60],
        ['3年', 3 * 365 * 24 * 60 * 60]
      ].map(([label, seconds]) => ({
        label,
        type: 'radio',
        checked: seconds === alerts.rangeSeconds,
        click: () => event.sender.send('menu:action', { type: 'range', label, seconds })
      }))
    },
    { type: 'separator' },
    {
      label: '面板设置',
      click: () => event.sender.send('menu:action', { type: 'settings' })
    },
    {
      label: '涨跌提醒',
      submenu: [
        ...[0, 0.1, 0.3, 0.5, 1].map((value) => ({
          label: value === 0 ? '关闭' : `${value}%`,
          type: 'radio',
          checked: alerts.threshold === value,
          click: () => event.sender.send('menu:action', { type: 'threshold', value })
        })),
        {
          label: '自定义' + (![0, 0.1, 0.3, 0.5, 1].includes(alerts.threshold) ? ` (${alerts.threshold}%)` : ''),
          type: 'radio',
          checked: ![0, 0.1, 0.3, 0.5, 1].includes(alerts.threshold),
          click: () => event.sender.send('menu:action', { type: 'custom-threshold' })
        }
      ]
    },
    {
      label: '提醒冷却时间',
      submenu: [...[1, 5, 15, 30, 60].map((value) => ({
        label: `${value} 分钟`, type: 'radio', checked: alerts.cooldown === value,
        click: () => event.sender.send('menu:action', { type: 'cooldown', value })
      })), {
        label: '自定义' + (![1, 5, 15, 30, 60].includes(alerts.cooldown) ? ` (${alerts.cooldown} 分钟)` : ''),
        type: 'radio',
        checked: ![1, 5, 15, 30, 60].includes(alerts.cooldown),
        click: () => event.sender.send('menu:action', { type: 'custom-cooldown' })
      }]
    },
    {
      label: alerts.targetPrice > 0 ? `目标提醒 (${alerts.direction === 'above' ? '≥' : '≤'} ${alerts.targetPrice})` : '目标汇率提醒',
      submenu: [
        { label: '关闭', type: 'radio', checked: !alerts.targetPrice,
          click: () => event.sender.send('menu:action', { type: 'target-off' }) },
        ...[['above', '达到或高于'], ['below', '达到或低于']].map(([value, label]) => ({
          label, type: 'radio', checked: alerts.targetPrice > 0 && alerts.direction === value,
          click: () => event.sender.send('menu:action', { type: 'target', value })
        }))
      ]
    },
    { type: 'separator' },
    {
      label: '新增监控浮窗',
      click: () => event.sender.send('menu:action', { type: 'new-window' })
    },
    {
      label: '关闭当前浮窗',
      click: () => event.sender.send('menu:action', { type: 'close' })
    }
  ];
  Menu.buildFromTemplate(template).popup({ window: win });
});

ipcMain.on('notify', (_event, { title, body }) => {
  if (Notification.isSupported()) {
    new Notification({ title, body }).show();
  }
});

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  app.quit();
});
