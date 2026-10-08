const currencies = {
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

const ranges = [
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
];

const chartSize = {
  width: 188,
  height: 23
};

const els = {
  card: document.getElementById('card'),
  changeLabel: document.getElementById('changeLabel'),
  changeGroup: document.getElementById('changeGroup'),
  targetStatus: document.getElementById('targetStatus'),
  targetLine: document.getElementById('targetLine'),
  rangeText: document.getElementById('rangeText'),
  healthText: document.getElementById('healthText'),
  chartTitle: document.getElementById('chartTitle'),
  sourceText: document.getElementById('sourceText'),
  pairTitle: document.getElementById('pairTitle'),
  priceText: document.getElementById('priceText'),
  changeText: document.getElementById('changeText'),
  linePath: document.getElementById('linePath'),
  areaPath: document.getElementById('areaPath'),
  dot: document.getElementById('dot'),
  chartMessage: document.getElementById('chartMessage'),
  settingsPanel: document.getElementById('settingsPanel'),
  closeSettings: document.getElementById('closeSettings'),
  opacitySlider: document.getElementById('opacitySlider'),
  opacityValue: document.getElementById('opacityValue'),
  blurSlider: document.getElementById('blurSlider'),
  blurValue: document.getElementById('blurValue'),
  resetPanelSettings: document.getElementById('resetPanelSettings')
};

const params = new URLSearchParams(location.search);
const defaultPanelSettings = {
  opacity: 5,
  blur: 20
};

function loadPanelSettings() {
  try {
    return { ...defaultPanelSettings, ...JSON.parse(localStorage.getItem('panelSettings') || '{}') };
  } catch {
    return { ...defaultPanelSettings };
  }
}

const state = {
  baseCurrency: params.get('base') || localStorage.getItem('baseCurrency') || '英镑',
  quoteCurrency: params.get('quote') || localStorage.getItem('quoteCurrency') || '人民币',
  rangeLabel: '30min',
  rangeSeconds: 30 * 60,
  previousPrice: null,
  previousSource: null,
  currentQuote: null,
  cached: false,
  alerts: null,
  rateToken: 0,
  historyToken: 0,
  currentTimer: null,
  history: [],
  dragging: false,
  lastMouseX: 0,
  lastMouseY: 0,
  panelSettings: loadPanelSettings(),
  offline: false
};

function code(currency) {
  return currencies[currency]?.code || currency;
}

function pairTitle() {
  return `${code(state.baseCurrency)}/${code(state.quoteCurrency)}`;
}

function alertKey() {
  return `alerts:${state.baseCurrency}:${state.quoteCurrency}`;
}

function loadAlerts() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(alertKey()) || '{}') || {}; } catch {}
  state.alerts = {
    threshold: Number.isFinite(saved.threshold) && saved.threshold >= 0 ? saved.threshold : 0.5,
    cooldown: Number.isFinite(saved.cooldown) && saved.cooldown > 0 && Number.isFinite(saved.cooldown * 60000) ? saved.cooldown : 5,
    targetPrice: Number.isFinite(saved.targetPrice) && saved.targetPrice > 0 ? saved.targetPrice : 0,
    direction: saved.direction === 'above' ? 'above' : 'below',
    targetTriggered: saved.targetTriggered === true,
    lastChange: Number.isFinite(saved.lastChange) ? saved.lastChange : 0,
    lastTarget: Number.isFinite(saved.lastTarget) ? saved.lastTarget : 0
  };
}

function saveAlerts() {
  localStorage.setItem(alertKey(), JSON.stringify(state.alerts));
  updateTargetStatus();
  renderChart(state.history);
}

function checkAlerts(price, previousPrice, updateTime, now = Date.now()) {
  const alerts = state.alerts;
  const cooldown = alerts.cooldown * 60000;
  const pct = previousPrice > 0 ? (price - previousPrice) / previousPrice * 100 : 0;
  if (alerts.threshold > 0 && Math.abs(pct) >= alerts.threshold &&
      (!alerts.lastChange || now - alerts.lastChange >= cooldown)) {
    window.rateMonitor.notify({
      title: `${pairTitle()} ${pct > 0 ? '上涨' : '下跌'}`,
      body: `较上次更新 ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%，现价: ${price.toFixed(4)} (${updateTime})`
    });
    alerts.lastChange = now;
  }
  const reached = alerts.targetPrice > 0 && (alerts.direction === 'above'
    ? price >= alerts.targetPrice : price <= alerts.targetPrice);
  if (!reached) alerts.targetTriggered = false;
  if (reached && !alerts.targetTriggered && (!alerts.lastTarget || now - alerts.lastTarget >= cooldown)) {
    window.rateMonitor.notify({
      title: `${pairTitle()} 达标提醒`,
      body: `已达到或${alerts.direction === 'above' ? '高于' : '低于'} ${alerts.targetPrice}，当前最新价: ${price.toFixed(4)}`
    });
    alerts.targetTriggered = true;
    alerts.lastTarget = now;
  }
  saveAlerts();
}

function saveSettings() {
  localStorage.setItem('baseCurrency', state.baseCurrency);
  localStorage.setItem('quoteCurrency', state.quoteCurrency);
}

function savePanelSettings() {
  localStorage.setItem('panelSettings', JSON.stringify(state.panelSettings));
}

function applyPanelSettings() {
  document.documentElement.style.setProperty('--glass-opacity', String(state.panelSettings.opacity / 100));
  document.documentElement.style.setProperty('--glass-blur', `${state.panelSettings.blur}px`);
  els.opacitySlider.value = state.panelSettings.opacity;
  els.opacityValue.textContent = `${state.panelSettings.opacity}%`;
  els.blurSlider.value = state.panelSettings.blur;
  els.blurValue.textContent = `${state.panelSettings.blur}px`;
}

function showPanelSettings() {
  els.settingsPanel.classList.remove('hidden');
}

function hidePanelSettings() {
  els.settingsPanel.classList.add('hidden');
}

function localKey() {
  return `history:${state.baseCurrency}:${state.quoteCurrency}`;
}

function loadLocalHistory(rangeSeconds) {
  const cutoff = Date.now() - rangeSeconds * 1000;
  const rows = JSON.parse(localStorage.getItem(localKey()) || '[]')
    .filter((point) => point.timestamp >= cutoff);
  return rows;
}

function saveLocalPoint(price, quote) {
  const cutoff = Date.now() - 3 * 365 * 24 * 60 * 60 * 1000;
  const rows = JSON.parse(localStorage.getItem(localKey()) || '[]')
    .filter((point) => point.timestamp >= cutoff);
  rows.push({ timestamp: Date.now(), price, source: quote.source, updateTime: quote.updateTime, fetchedAt: quote.fetchedAt });
  localStorage.setItem(localKey(), JSON.stringify(rows));
}

function applyHeader() {
  els.pairTitle.textContent = pairTitle();
}

function trendColor(change) {
  return change > 0 ? '#ff4b55' : change < 0 ? '#2ed573' : '#d1d5db';
}

function setTrend(change) {
  const line = trendColor(change);
  document.documentElement.style.setProperty('--line', line);
}

function setChange(change) {
  const rounded = Number(change.toFixed(2));
  document.documentElement.style.setProperty('--change', trendColor(rounded));
  document.documentElement.style.setProperty('--pill-bg', rounded > 0 ? 'rgba(255,75,85,0.12)' : rounded < 0 ? 'rgba(46,213,115,0.12)' : 'rgba(209,213,219,0.12)');
  return rounded === 0 ? '0.00%' : `${rounded > 0 ? '+' : ''}${rounded.toFixed(2)}%`;
}

function setNeutralTrend() {
  setTrend(0);
  setChange(0);
}

function showQuoteDetails(quote, cached = false) {
  state.currentQuote = quote;
  state.cached = cached;
  const labels = {
    'boc-sell': '中行现汇卖出', 'boc-cross': '中行交叉参考',
    'boc-inverse': '中行卖出价倒数', frankfurter: 'Frankfurter 参考', identity: '同币种'
  };
  const label = labels[quote.source] || '来源未知';
  els.sourceText.textContent = cached ? '本地缓存' : label;
  const published = quote.updateTime
    ? `${quote.source?.startsWith('boc-') ? '报价发布：' : '参考汇率日期：'}${quote.updateTime}${quote.source?.startsWith('boc-') ? '（北京时间 UTC+8）' : ''}`
    : '报价发布时间未知';
  const fetched = Number.isFinite(quote.fetchedAt) ? new Date(quote.fetchedAt).toISOString() : '未知';
  els.sourceText.title = `${cached ? '本地缓存 · ' : ''}${label}\n${published}\n最近获取：${fetched}（UTC）`;
  els.priceText.title = els.sourceText.title;
  updateHealth();
  updateTargetStatus();
}

function quoteHealth(quote, cached, offline, now = Date.now()) {
  if (offline) return { text: '网络异常', stale: true, detail: '获取失败，等待恢复；不代表休市。' };
  if (!quote) return { text: '等待报价', stale: true, detail: '尚未取得报价。' };
  if (cached) return { text: '本地缓存', stale: true, detail: '尚未刷新，目标距离仅供参考。' };
  if (!Number.isFinite(quote.fetchedAt) || now - quote.fetchedAt > 120000) {
    return { text: '获取已延迟', stale: true, detail: '超过 2 分钟未成功获取新数据。' };
  }
  if (quote.source === 'identity') return { text: '同币种', stale: false, detail: '同币种汇率恒为 1。' };
  let published;
  let limit;
  if (quote.source?.startsWith('boc-')) {
    const matches = [...(quote.updateTime || '').matchAll(/(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{2}:\d{2}:\d{2})/g)];
    published = matches.length ? Math.min(...matches.map(m => Date.parse(`${m[1]}-${m[2]}-${m[3]}T${m[4]}+08:00`))) : NaN;
    limit = 30 * 60000;
  } else {
    published = /^\d{4}-\d{2}-\d{2}$/.test(quote.updateTime || '') ? Date.parse(`${quote.updateTime}T00:00:00Z`) : NaN;
    limit = 4 * 86400000;
  }
  if (!Number.isFinite(published)) return { text: '时间未知', stale: true, detail: '无法确定报价发布时间。' };
  if (now - published > limit) return {
    text: '数据未更新', stale: true,
    detail: `报价时间距今超过${limit === 1800000 ? ' 30 分钟' : ' 4 天'}。仅为陈旧提示，不判断是否休市。`
  };
  return { text: quote.source === 'frankfurter' ? '参考日线' : '已获取', stale: false, detail: '已获取数据，报价发布时间请悬停查看来源。' };
}

function updateHealth() {
  const health = quoteHealth(state.currentQuote, state.cached, state.offline);
  const quote = state.currentQuote;
  const times = [...(quote?.updateTime || '').matchAll(/\d{2}:\d{2}:\d{2}/g)].map(m => m[0].slice(0, 5));
  const label = quote?.source?.startsWith('boc-') && times.length
    ? `更新 ${[...new Set(times)].join('/')}（北京）`
    : quote?.updateTime ? `更新 ${quote.updateTime}` : '更新时间未知';
  els.healthText.textContent = state.offline ? '网络异常' : label;
  els.healthText.title = `${els.sourceText.title}\n${health.text}：${health.detail}`;
  els.healthText.setAttribute('data-stale', String(health.stale));
  els.card.setAttribute('data-stale', String(health.stale));
  els.priceText.title = `${els.sourceText.title}\n${health.text}：${health.detail}`;
}

function updateTargetStatus() {
  const alerts = state.alerts;
  if (!alerts) return;
  const change = alerts.threshold > 0 ? `涨跌提醒：${alerts.threshold}%` : '涨跌提醒关闭';
  let text = '目标提醒未开启';
  let difference = '';
  let highlight = false;
  if (alerts.targetPrice > 0) {
    const prefix = `目标 ${alerts.direction === 'above' ? '≥' : '≤'} ${alerts.targetPrice.toFixed(4)}`;
    const price = state.currentQuote?.price;
    const health = quoteHealth(state.currentQuote, state.cached, state.offline);
    if (!(price > 0) || state.offline) text = `${prefix} · 等待报价`;
    else {
      const reached = alerts.direction === 'above' ? price >= alerts.targetPrice : price <= alerts.targetPrice;
      highlight = reached && !health.stale;
      difference = `绝对差值 ${Math.abs(alerts.targetPrice - price).toFixed(4)}\n${health.text}：${health.detail}`;
      const distance = Math.abs((alerts.targetPrice / price - 1) * 100);
      const distanceText = distance > 0 && distance < 0.01 ? '<0.01' : distance.toFixed(2);
      const status = reached ? '已达标'
        : `还差 ${distanceText}%`;
      text = `${prefix} · ${status}`;
    }
  }
  els.targetStatus.textContent = text;
  els.card.setAttribute('data-reached', String(highlight));
  els.targetStatus.title = `${text}\n${difference}\n${change} · 冷却 ${alerts.cooldown} 分钟\n按当前报价来源判断；持续达标不重复通知。`;
}

function applyCachedPrice() {
  const rows = JSON.parse(localStorage.getItem(localKey()) || '[]');
  const latest = rows[rows.length - 1];
  state.previousSource = null;
  state.previousPrice = null;
  state.currentQuote = null;
  state.cached = false;
  state.offline = false;
  els.priceText.textContent = 'Loading';
  els.changeText.textContent = '--';
  els.sourceText.textContent = '等待报价';
  els.sourceText.title = '';
  els.priceText.title = '';
  setNeutralTrend();
  updateHealth();
  updateTargetStatus();
  if (!latest) return;
  els.priceText.textContent = Number(latest.price).toFixed(4);
  showQuoteDetails(latest, true);
}

async function refreshRate() {
  const token = ++state.rateToken;
  try {
    const result = await window.rateMonitor.getCurrentRate({
      baseCurrency: state.baseCurrency,
      quoteCurrency: state.quoteCurrency
    });
    if (token !== state.rateToken) return;
    if (!Number.isFinite(result.price) || result.price <= 0) {
      showNetworkError();
      return;
    }
    applyRate(result.price, result.updateTime, result);
  } catch {
    if (token === state.rateToken) showNetworkError();
  }
}

function showNetworkError() {
  state.offline = true;
  els.priceText.textContent = 'Net Error';
  els.changeText.textContent = '--';
  els.sourceText.textContent = '网络异常';
  els.sourceText.title = '获取失败，当前没有新的报价';
  els.priceText.title = '';
  setNeutralTrend();
  updateHealth();
  updateTargetStatus();
  updateTargetLine();
}

function applyRate(price, updateTime, quote = {}) {
  state.offline = false;
  const priceText = Number(price).toFixed(4);
  const comparable = quote.source && quote.source === state.previousSource ? state.previousPrice : null;

  els.priceText.textContent = priceText;
  showQuoteDetails({ ...quote, price, updateTime });
  saveLocalPoint(price, { ...quote, updateTime });
  refreshHistory(false);
  loadAlerts();
  checkAlerts(price, comparable, `${updateTime} · ${els.sourceText.textContent}`);
  state.previousPrice = price;
  state.previousSource = quote.source;
}

function scheduleRefresh() {
  clearTimeout(state.currentTimer);
  state.currentTimer = setTimeout(async () => {
    await refreshRate();
    scheduleRefresh();
  }, 20000 + Math.floor(Math.random() * 25000));
}

async function refreshHistory(forceExternal) {
  if (!forceExternal && state.rangeSeconds >= 24 * 60 * 60) return;
  state.historyToken += 1;
  const token = state.historyToken;
  if (state.rangeSeconds < 24 * 60 * 60) {
    renderChart(loadLocalHistory(state.rangeSeconds), '暂无本地记录');
    return;
  }

  if (!forceExternal) return;
  renderChart([], '加载中');
  try {
    const days = Math.max(1, Math.floor(state.rangeSeconds / (24 * 60 * 60)));
    const points = await window.rateMonitor.getHistory({
      baseCurrency: state.baseCurrency,
      quoteCurrency: state.quoteCurrency,
      days
    });
    if (token !== state.historyToken) return;
    renderChart(points, '暂无日线记录');
  } catch {
    if (token === state.historyToken) renderChart([], '历史数据获取失败');
  }
}

function chartBounds(now = Date.now()) {
  const end = state.rangeSeconds < 86400 ? now : Math.floor(now / 86400000) * 86400000;
  return { start: end - state.rangeSeconds * 1000, end };
}

function chartScale(points) {
  const prices = points.map(point => Number(point.price));
  if (state.alerts?.targetPrice > 0) prices.push(state.alerts.targetPrice);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  return { min, max };
}

function chartCoords(points, bounds = chartBounds()) {
  const scale = chartScale(points);
  return points.map(point => ({
    x: 3 + (chartSize.width - 6) * (point.timestamp - bounds.start) / (bounds.end - bounds.start),
    y: chartY(point.price, scale)
  }));
}

function chartY(price, { min, max }) {
  return max === min ? chartSize.height / 2 : 3 + (chartSize.height - 6) * (max - price) / (max - min);
}

function chartSegments(points) {
  const segments = [];
  const gapLimit = state.rangeSeconds < 86400 ? 120000 : 1.5 * 86400000;
  for (const point of points) {
    const last = segments[segments.length - 1];
    const previous = last?.[last.length - 1];
    if (!previous || point.timestamp - previous.timestamp > gapLimit || point.source !== previous.source) {
      segments.push([point]);
    } else last.push(point);
  }
  return segments;
}

function updateTargetLine() {
  els.targetLine.setAttribute('d', '');
  const target = state.alerts?.targetPrice;
  const points = state.history;
  if (!(target > 0) || !points.length) return;
  const y = chartY(target, chartScale(points));
  els.targetLine.setAttribute('d', `M 3,${y} H ${chartSize.width - 3}`);
}

function updateRangeChange() {
  const points = state.history;
  els.changeLabel.textContent = `近${state.rangeLabel}`;
  const valid = points.length > 1 && points[0].source && points.every(p => p.source === points[0].source);
  els.changeText.textContent = valid ? setChange((points[points.length - 1].price / points[0].price - 1) * 100) : '--';
  if (!valid) setChange(0);
  els.changeGroup.title = `${state.rangeLabel} · ${state.rangeSeconds < 86400 ? '本地记录' : 'Frankfurter 日线'}\n${valid ? '所选区间内首个与最后一个有效报价的变化，非当前中行报价与昨收比较。' : '记录不足或含不同来源，无法计算区间涨跌幅。'}\n涨跌提醒仍按相邻两次同来源报价计算。`;
}

function renderChart(points, emptyMessage = '暂无数据') {
  const bounds = chartBounds();
  state.history = (points || []).filter(point =>
    Number.isFinite(point.timestamp) && Number.isFinite(point.price) && point.price > 0 &&
    point.timestamp >= bounds.start && point.timestamp <= bounds.end
  ).sort((a, b) => a.timestamp - b.timestamp);
  updateRangeChange();
  els.rangeText.textContent = `${state.rangeLabel} · ${state.rangeSeconds < 86400 ? '本地' : '日线'}`;
  els.chartMessage.textContent = '';
  els.targetLine.setAttribute('d', '');
  if (!state.history.length) {
    setTrend(0);
    els.linePath.setAttribute('d', '');
    els.areaPath.setAttribute('d', '');
    els.dot.setAttribute('r', 0);
    els.chartMessage.textContent = emptyMessage;
    els.chartTitle.textContent = `${state.rangeLabel}：${emptyMessage}`;
    els.rangeText.title = els.chartTitle.textContent;
    return;
  }

  const coords = chartCoords(state.history, bounds);
  const segments = chartSegments(state.history);
  let index = 0;
  const lines = [];
  const areas = [];
  for (const segment of segments) {
    const group = coords.slice(index, index + segment.length);
    index += segment.length;
    const first = group[0];
    const last = group[group.length - 1];
    // Separate paths preserve missing intervals and source changes; no interpolation across gaps.
    const line = group.length === 1 ? `M ${first.x},${first.y} l 0.01,0`
      : group.map((point, i) => `${i ? 'L' : 'M'} ${point.x},${point.y}`).join(' ');
    lines.push(line);
    if (group.length > 1) areas.push(`${line} L ${last.x},${chartSize.height} L ${first.x},${chartSize.height} Z`);
  }
  els.linePath.setAttribute('d', lines.join(' '));
  els.areaPath.setAttribute('d', areas.join(' '));
  const last = coords[coords.length - 1];
  els.dot.setAttribute('r', 2.2);
  els.dot.setAttribute('cx', last.x);
  els.dot.setAttribute('cy', last.y);
  const singleSource = state.history.every(point => point.source === state.history[0].source);
  setTrend(!state.offline && singleSource ? state.history[state.history.length - 1].price - state.history[0].price : 0);
  const prices = state.history.map(point => point.price);
  const endpoint = state.history[state.history.length - 1];
  const details = [
    `${state.rangeLabel} · ${state.rangeSeconds < 86400 ? '本地采样记录' : 'Frankfurter 参考日线'}`,
    `区间最高 ${Math.max(...prices).toFixed(4)} · 最低 ${Math.min(...prices).toFixed(4)}`,
    `曲线末点 ${endpoint.price.toFixed(4)}（${new Date(endpoint.timestamp).toISOString()}），不一定等于面板现价。`,
    state.currentQuote?.price > 0 ? `面板报价 ${state.currentQuote.price.toFixed(4)}；目标距离和通知按面板报价判断。` : '尚无当前报价。',
    `横轴（UTC）：${new Date(bounds.start).toISOString()} 至 ${new Date(bounds.end).toISOString()}`,
    `断开区间 ${segments.length - 1} 处；空白表示无记录，日线周末及假日可能无报价。`,
    '纵轴包含目标价并自动缩放。',
    state.history.every(p => p.source === state.currentQuote?.source) ? '虚线为目标价。' : '目标虚线仅作参考对照：图表与当前报价来源可能不同，提醒按当前报价判断。',
    '历史穿越不补发通知；程序运行时收到的当前报价满足条件才会触发提醒。'
  ].join('\n');
  els.chartTitle.textContent = details;
  els.rangeText.title = details;
  updateTargetLine();
}

document.addEventListener('contextmenu', (event) => {
  event.preventDefault();
  loadAlerts();
  window.rateMonitor.showMenu({
    ...state.alerts,
    baseCurrency: state.baseCurrency,
    quoteCurrency: state.quoteCurrency,
    rangeSeconds: state.rangeSeconds
  });
});

document.addEventListener('mousedown', (event) => {
  if (event.button !== 0) return;
  if (event.target.closest('.no-drag')) return;
  state.dragging = true;
  state.lastMouseX = event.screenX;
  state.lastMouseY = event.screenY;
  window.rateMonitor.startDrag();
});

document.addEventListener('mousemove', (event) => {
  if (!state.dragging) return;
  const dx = event.screenX - state.lastMouseX;
  const dy = event.screenY - state.lastMouseY;
  state.lastMouseX = event.screenX;
  state.lastMouseY = event.screenY;
  if (dx || dy) {
    window.rateMonitor.moveBy({ dx, dy });
  }
});

function stopDragging() {
  if (!state.dragging) return;
  state.dragging = false;
  window.rateMonitor.endDrag();
}

document.addEventListener('mouseup', stopDragging);
window.addEventListener('blur', stopDragging);

window.rateMonitor.onMenuAction((action) => {
  if (action.type === 'base') changeBase(action.value);
  if (action.type === 'quote') changeQuote(action.value);
  if (action.type === 'range') changeRange(action.label, action.seconds);
  if (action.type === 'settings') showPanelSettings();
  loadAlerts();
  if (action.type === 'target') showAlertEditor('target', action.value);
  if (action.type === 'custom-threshold') showAlertEditor('threshold');
  if (action.type === 'custom-cooldown') showAlertEditor('cooldown');
  if (action.type === 'threshold') state.alerts.threshold = action.value;
  if (action.type === 'cooldown') state.alerts.cooldown = action.value;
  if (action.type === 'target-off') {
    state.alerts.targetPrice = 0;
    state.alerts.targetTriggered = false;
  }
  saveAlerts();
  if (action.type === 'new-window') window.rateMonitor.createWindow({ base: '美元', quote: '人民币' });
  if (action.type === 'close') window.close();
});

els.closeSettings.addEventListener('click', hidePanelSettings);

els.opacitySlider.addEventListener('input', () => {
  state.panelSettings.opacity = Number(els.opacitySlider.value);
  applyPanelSettings();
  savePanelSettings();
});

els.blurSlider.addEventListener('input', () => {
  state.panelSettings.blur = Number(els.blurSlider.value);
  applyPanelSettings();
  savePanelSettings();
});

els.resetPanelSettings.addEventListener('click', () => {
  state.panelSettings = { ...defaultPanelSettings };
  applyPanelSettings();
  savePanelSettings();
});

function changeBase(name) {
  state.baseCurrency = name;
  resetPair();
}

function changeQuote(name) {
  state.quoteCurrency = name;
  resetPair();
}

function changeRange(label, seconds) {
  state.rangeLabel = label;
  state.rangeSeconds = seconds;
  refreshHistory(true);
}

function resetPair() {
  saveSettings();
  state.previousPrice = null;
  loadAlerts();
  document.getElementById('alertEditor').classList.add('hidden');
  applyHeader();
  applyCachedPrice();
  refreshHistory(true);
  refreshRate();
}

let alertEdit = null;
function showAlertEditor(kind, direction) {
  hidePanelSettings();
  alertEdit = { kind, direction, pair: pairTitle() };
  document.getElementById('alertLabel').textContent = kind === 'threshold'
    ? '涨跌阈值 (%)' : kind === 'cooldown' ? '冷却时间 (分钟)' : `${pairTitle()} ${direction === 'above' ? '≥' : '≤'}`;
  const input = document.getElementById('alertValue');
  input.value = (kind === 'target' ? state.alerts.targetPrice : state.alerts[kind]) || '';
  input.setCustomValidity('');
  document.getElementById('alertEditor').classList.remove('hidden');
  input.focus();
  input.select();
}

document.getElementById('cancelAlert').addEventListener('click', () => {
  document.getElementById('alertEditor').classList.add('hidden');
});
document.getElementById('alertValue').addEventListener('input', (event) => event.target.setCustomValidity(''));
document.getElementById('alertEditor').addEventListener('submit', (event) => {
  event.preventDefault();
  const input = document.getElementById('alertValue');
  const value = Number(input.value);
  if (!Number.isFinite(value) || value <= 0) {
    input.setCustomValidity('请输入大于 0 的数值');
    input.reportValidity();
    return;
  }
  if (!alertEdit || alertEdit.pair !== pairTitle()) return;
  if (alertEdit.kind === 'cooldown' && !Number.isFinite(value * 60000)) {
    input.setCustomValidity('冷却时间过大');
    input.reportValidity();
    return;
  }
  loadAlerts();
  if (alertEdit.kind === 'threshold') state.alerts.threshold = value;
  else if (alertEdit.kind === 'cooldown') state.alerts.cooldown = value;
  else {
    state.alerts.targetPrice = value;
    state.alerts.direction = alertEdit.direction;
    state.alerts.targetTriggered = false;
  }
  saveAlerts();
  document.getElementById('alertEditor').classList.add('hidden');
});

loadAlerts();
applyPanelSettings();
applyHeader();
applyCachedPrice();
refreshHistory(true);
refreshRate();
scheduleRefresh();
setInterval(() => {
  loadAlerts();
  updateHealth();
  updateTargetStatus();
  if (state.rangeSeconds < 86400) renderChart(loadLocalHistory(state.rangeSeconds), '暂无本地记录');
  else renderChart(state.history, els.chartMessage.textContent);
}, 15000);
