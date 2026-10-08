const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function mainFixture() {
  const handlers = new Map();
  const context = vm.createContext({
    require: name => name === 'electron' ? {
      app: { whenReady: () => ({ then() {} }), on() {} },
      ipcMain: { handle: (name, handler) => handlers.set(name, handler), on() {} }
    } : require(name),
    __dirname, URLSearchParams, AbortSignal,
    fetch: () => { throw new Error('Unexpected network request'); }
  });
  vm.runInContext(fs.readFileSync(require.resolve('./main.js'), 'utf8'), context);
  return handlers;
}

test('same-currency current quote and daily history stay at one without network access', async () => {
  const handlers = mainFixture();
  const pair = { baseCurrency: '英镑', quoteCurrency: '英镑' };
  const current = await handlers.get('rates:get-current')({}, pair);
  assert.equal(current.price, 1);
  assert.equal(current.source, 'identity');
  const history = await handlers.get('rates:get-history')({}, { ...pair, days: 7 });
  assert.equal(history.length, 8);
  assert.ok(history.every(point => point.price === 1 && point.source === 'identity' && point.timestamp % 86400000 === 0));
  assert.equal(history[7].timestamp - history[0].timestamp, 7 * 86400000);
});
