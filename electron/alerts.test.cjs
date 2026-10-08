const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fixture() {
  const notifications = [];
  const storage = new Map();
  const elements = new Map();
  const styles = new Map();
  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, { textContent: '', attributes: {}, addEventListener() {}, setAttribute(key, value) { this.attributes[key] = value; }, classList: { add() {}, remove() {} } });
    return elements.get(id);
  };
  const context = vm.createContext({
    URLSearchParams, location: { search: '' },
    document: { getElementById: getElement, addEventListener() {}, documentElement: { style: { setProperty: (key, value) => styles.set(key, value) } } },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    window: { addEventListener() {}, rateMonitor: { onMenuAction() {}, notify: (value) => notifications.push(value) } }
  });
  const source = fs.readFileSync(require.resolve('./renderer.js'), 'utf8');
  vm.runInContext(source.slice(0, source.lastIndexOf('\nloadAlerts();')), context);
  const run = (code) => vm.runInContext(code, context);
  run('loadAlerts()');
  return { run, notifications, elements, styles };
}

test('change threshold includes equality, both directions, cooldown and disabled state', () => {
  const { run, notifications } = fixture();
  run('checkAlerts(100.49, 100, "", 1000000)');
  assert.equal(notifications.length, 0);
  run('checkAlerts(100.5, 100, "", 1000000)');
  run('checkAlerts(99, 100, "", 1000001)');
  assert.equal(notifications.length, 1);
  run('checkAlerts(99.5, 100, "", 1300000)');
  assert.equal(notifications.length, 2);
  run('state.alerts.threshold = 0; checkAlerts(120, 100, "", 1600000)');
  assert.equal(notifications.length, 2);
});

test('targets include equality, latch while reached, and rearm after cooldown', () => {
  for (const direction of ['above', 'below']) {
    const { run, notifications } = fixture();
    run(`state.alerts.threshold = 0; state.alerts.targetPrice = 100; state.alerts.direction = '${direction}'`);
    run('checkAlerts(100, null, "", 1000000); checkAlerts(100, null, "", 1400000)');
    assert.equal(notifications.length, 1);
    run(`checkAlerts(${direction === 'above' ? 99 : 101}, null, "", 1400001)`);
    run('checkAlerts(100, null, "", 1400002)');
    assert.equal(notifications.length, 2);
    run(`checkAlerts(${direction === 'above' ? 99 : 101}, null, "", 1400003)`);
    run('checkAlerts(100, null, "", 1400004)');
    assert.equal(notifications.length, 2);
    run('checkAlerts(100, null, "", 1700002)');
    assert.equal(notifications.length, 3);
  }
});

test('settings persist per pair and malformed storage falls back to defaults', () => {
  const { run } = fixture();
  run('state.alerts.threshold = 0.23; state.alerts.cooldown = 15; state.alerts.targetPrice = 1.2; state.alerts.direction = "above"; saveAlerts()');
  run('state.baseCurrency = "美元"; loadAlerts()');
  assert.equal(run('state.alerts.threshold'), 0.5);
  assert.equal(run('state.alerts.targetPrice'), 0);
  run('state.baseCurrency = "英镑"; loadAlerts()');
  assert.equal(run('state.alerts.threshold'), 0.23);
  assert.equal(run('state.alerts.cooldown'), 15);
  assert.equal(run('state.alerts.direction'), 'above');
  assert.equal(run('state.alerts.targetPrice'), 1.2);
  run('localStorage.setItem(alertKey(), "invalid"); loadAlerts()');
  assert.equal(run('state.alerts.threshold'), 0.5);
});

test('custom fractional cooldown persists and suppresses alerts until expiry', () => {
  const { run, notifications } = fixture();
  run('state.alerts.cooldown = 2.5; saveAlerts(); loadAlerts()');
  assert.equal(run('state.alerts.cooldown'), 2.5);
  run('checkAlerts(101, 100, "", 1000000)');
  run('checkAlerts(101, 100, "", 1149999)');
  assert.equal(notifications.length, 1);
  run('checkAlerts(101, 100, "", 1150000)');
  assert.equal(notifications.length, 2);
  for (const cooldown of [0, -1, '5', 1e308]) {
    run(`localStorage.setItem(alertKey(), JSON.stringify({ cooldown: ${JSON.stringify(cooldown)} })); loadAlerts()`);
    assert.equal(run('state.alerts.cooldown'), 5);
  }
});

test('price stays unsigned and range change matches chart while rounded zero is neutral', () => {
  const { run, elements, styles } = fixture();
  run('applyRate(100, "2026/10/09 06:40:26", {source: "boc-sell", fetchedAt: 1791528000000})');
  run('applyRate(99.999, "", {source: "boc-sell"})');
  assert.equal(elements.get('priceText').textContent, '99.9990');
  assert.equal(elements.get('changeText').textContent, '0.00%');
  assert.equal(styles.get('--change'), '#d1d5db');
  run('applyRate(101, "", {source: "boc-sell"})');
  run('renderChart([{price: 102, timestamp: Date.now()-30000, source: "boc-sell"}, {price: 101, timestamp: Date.now(), source: "boc-sell"}])');
  assert.equal(styles.get('--change'), '#2ed573');
  assert.equal(elements.get('changeText').textContent, '-0.98%');
  assert.equal(styles.get('--line'), '#2ed573');
});

test('source switches reset comparisons and legacy cache has no fabricated source', () => {
  const { run, elements, notifications } = fixture();
  run('applyRate(100, "", {source: "boc-sell"}); applyRate(110, "2026-10-09", {source: "frankfurter"})');
  assert.equal(elements.get('changeText').textContent, '--');
  assert.equal(notifications.length, 0);
  assert.equal(elements.get('sourceText').textContent, 'Frankfurter 参考');
  assert.match(elements.get('sourceText').title, /参考汇率日期：2026-10-09/);
  run('localStorage.setItem(localKey(), JSON.stringify([{price: 8.9, timestamp: Date.now()}])); applyCachedPrice()');
  assert.equal(elements.get('priceText').textContent, '8.9000');
  assert.match(elements.get('sourceText').title, /来源未知/);
  assert.equal(run('state.previousPrice'), null);
});

test('time axis preserves elapsed intervals, gaps and source boundaries', () => {
  const { run, elements } = fixture();
  const coords = run('chartCoords([{price: 1, timestamp: 0}, {price: 1, timestamp: 10}, {price: 1, timestamp: 100}], {start: 0, end: 100})');
  assert.ok(Math.abs((coords[1].x - coords[0].x) / (coords[2].x - coords[0].x) - 0.1) < 1e-9);
  assert.equal(coords[0].y, 11.5);
  assert.equal(run('chartSegments([{timestamp: 0, source: "boc-sell"}, {timestamp: 30000, source: "boc-sell"}, {timestamp: 180000, source: "boc-sell"}, {timestamp: 210000, source: "frankfurter"}]).length'), 3);
  run('renderChart([{timestamp: Date.now()-300000, price: 1}, {timestamp: Date.now(), price: 2}])');
  assert.equal((elements.get('linePath').attributes.d.match(/M /g) || []).length, 2);
  assert.match(elements.get('rangeText').title, /最高 2.0000 · 最低 1.0000/);
  run('renderChart([])');
  assert.equal(elements.get('dot').attributes.r, 0);
});

test('target line extends scale and mismatched sources are labelled as reference', () => {
  const { run, elements } = fixture();
  run('state.alerts.targetPrice = 101; state.alerts.direction = "above"; state.currentQuote = {price: 100, source: "boc-sell", fetchedAt: Date.now()}; updateTargetStatus()');
  assert.match(elements.get('targetStatus').textContent, /目标 ≥ 101.0000 · 还差 1.00%/);
  assert.match(elements.get('targetStatus').title, /绝对差值 1.0000/);
  run('renderChart([{timestamp: Date.now()-30000, price: 100, source: "boc-sell"}, {timestamp: Date.now(), price: 102, source: "boc-sell"}])');
  assert.notEqual(elements.get('targetLine').attributes.d, '');
  run('state.alerts.targetPrice = 110; updateTargetLine()');
  assert.notEqual(elements.get('targetLine').attributes.d, '');
  assert.equal(run('chartScale(state.history).max'), 110);
  run('state.alerts.targetPrice = 101; state.currentQuote.source = "frankfurter"; renderChart(state.history)');
  assert.notEqual(elements.get('targetLine').attributes.d, '');
  assert.match(elements.get('chartTitle').textContent, /仅作参考对照/);
  run('state.alerts.direction = "below"; state.alerts.targetPrice = 99; updateTargetStatus()');
  assert.match(elements.get('targetStatus').textContent, /还差 1.00%/);
  run('state.offline = true; updateTargetStatus()');
  assert.match(elements.get('targetStatus').textContent, /等待报价/);
});

test('reached highlighting requires a fresh quote, without repeated stale text', () => {
  const { run, elements } = fixture();
  run('state.alerts.targetPrice = 1; state.alerts.direction = "above"; state.currentQuote = {price: 1, source: "identity", fetchedAt: Date.now()}; updateTargetStatus()');
  assert.equal(elements.get('card').attributes['data-reached'], 'true');
  run('state.cached = true; updateTargetStatus()');
  assert.equal(elements.get('card').attributes['data-reached'], 'false');
  assert.equal(elements.get('targetStatus').textContent, '目标 ≥ 1.0000 · 已达标');
});

test('health distinguishes stale publication, fetch delay, cache and network error', () => {
  const { run } = fixture();
  run('globalThis.healthNow = Date.parse("2026-10-09T01:00:00Z")');
  assert.equal(run('quoteHealth({source: "boc-sell", fetchedAt: healthNow, updateTime: "2026/10/09 08:50:00"}, false, false, healthNow).text'), '已获取');
  assert.equal(run('quoteHealth({source: "boc-cross", fetchedAt: healthNow, updateTime: "2026/10/09 08:00:00 / 2026/10/09 08:50:00"}, false, false, healthNow).text'), '数据未更新');
  assert.equal(run('quoteHealth({source: "frankfurter", fetchedAt: healthNow, updateTime: "2026-10-05"}, false, false, healthNow).text'), '数据未更新');
  assert.equal(run('quoteHealth({fetchedAt: healthNow-120001}, false, false, healthNow).text'), '获取已延迟');
  assert.equal(run('quoteHealth({}, true, false, healthNow).text'), '本地缓存');
  assert.equal(run('quoteHealth({}, false, true, healthNow).text'), '网络异常');
});

test('stale marker persists without hovering and clears on fresh data', () => {
  const { run, elements } = fixture();
  run('state.currentQuote = {price: 1, source: "identity", fetchedAt: Date.now()-120001}; updateHealth()');
  assert.equal(elements.get('card').attributes['data-stale'], 'true');
  assert.match(elements.get('priceText').title, /获取已延迟/);
  run('state.currentQuote.fetchedAt = Date.now(); updateHealth()');
  assert.equal(elements.get('card').attributes['data-stale'], 'false');
  run('state.cached = true; updateHealth()');
  assert.equal(elements.get('card').attributes['data-stale'], 'true');
});

test('endpoint and target share mapping; history crossing does not notify', () => {
  const { run, elements, notifications } = fixture();
  run('state.alerts.threshold = 0; state.alerts.targetPrice = 8.9; state.alerts.direction = "below"; state.currentQuote = {price: 8.9083, source: "boc-sell"}; state.rangeSeconds = 90*86400; state.rangeLabel = "3个月"');
  run('renderChart([{timestamp: chartBounds().end-86400000, price: 9, source: "frankfurter"}, {timestamp: chartBounds().end, price: 8.89, source: "frankfurter"}]); updateTargetStatus()');
  assert.match(elements.get('targetStatus').textContent, /还差 0.09%/);
  assert.match(elements.get('chartTitle').textContent, /曲线末点 8.8900/);
  const targetY = run('chartY(8.9, chartScale(state.history))');
  assert.ok(elements.get('dot').attributes.cy > targetY);
  assert.equal(notifications.length, 0);
  for (const price of [8.89, 8.9, 8.9083]) {
    run(`renderChart([{timestamp: chartBounds().end-86400000, price: 8.8, source: "boc-sell"}, {timestamp: chartBounds().end, price: ${price}, source: "boc-sell"}])`);
    const y = run('chartY(8.9, chartScale(state.history))');
    assert.equal(Math.sign(elements.get('dot').attributes.cy - y), Math.sign(8.9 - price));
  }
  run('checkAlerts(8.9083, null, "", 1000000)');
  assert.equal(notifications.length, 0);
  run('checkAlerts(8.9, null, "", 1000001)');
  assert.equal(notifications.length, 1);
});
