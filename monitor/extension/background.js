import {observationsForTabs, transitions} from './matcher.js';

const BASES = new Set(['https://mimas-staging.onrender.com', 'https://mimas.onrender.com']);
const DEFAULT_BASE = 'https://mimas-staging.onrender.com';
function checkedBase(base) {
  if (!BASES.has(base)) throw new Error('Выберите адрес интервью MIMAS.');
  return base;
}
const STATE_KEY = 'mimasMonitor';
const ALARM = 'mimas-monitor-check';
let serial = Promise.resolve();
let debounce;

function queue(task) {
  serial = serial.catch(() => {}).then(task);
  return serial;
}

async function readState() {
  return (await chrome.storage.session.get(STATE_KEY))[STATE_KEY] || null;
}

async function writeState(state) {
  await chrome.storage.session.set({[STATE_KEY]: state});
}

async function request(path, method = 'GET', body, token, base = DEFAULT_BASE) {
  const response = await fetch(`${checkedBase(base)}${path}`, {
    method,
    headers: {
      ...(body === undefined ? {} : {'Content-Type': 'application/json'}),
      ...(token ? {'X-Monitor-Token': token} : {})
    },
    ...(body === undefined ? {} : {body: JSON.stringify(body)})
  });
  if (response.status === 401 || response.status === 403 || response.status === 409) {
    const error = new Error(response.status === 409
      ? 'Интервью завершено. Проверка остановлена.'
      : 'Срок подключения истёк. Получите новый код в MIMAS.');
    error.status = response.status;
    throw error;
  }
  if (!response.ok) throw new Error(`MIMAS вернул HTTP ${response.status}`);
  return response.status === 204 ? null : response.json();
}

async function ensureAlarm() {
  await chrome.alarms.create(ALARM, {periodInMinutes: 0.5});
}

async function cycle() {
  const state = await readState();
  if (!state?.token) return;
  try {
    const now = Date.now();
    if (!state.catalog || now - (state.catalogFetchedAt || 0) > 5 * 60_000) {
      state.catalog = await request('/api/monitor/catalog', 'GET', undefined, state.token, state.base);
      state.catalogFetchedAt = now;
    }
    if (now - (state.lastHeartbeatAt || 0) > 20_000) {
      await request('/api/monitor/heartbeat', 'POST', {}, state.token, state.base);
      state.lastHeartbeatAt = now;
    }

    const [tabs, focused] = await Promise.all([
      chrome.tabs.query({}),
      chrome.windows.getLastFocused().catch(() => null)
    ]);
    const focusedWindowId = focused?.focused ? focused.id : -1;
    const current = observationsForTabs(state.catalog.products || [], tabs, focusedWindowId);
    const changes = transitions(state.activeKeys || [], current);
    state.activeKeys = [...current.keys()];
    state.pending = [...(state.pending || []), ...changes.map(change => ({event_id: crypto.randomUUID(), ...change}))];
    if (state.pending.length > 1000) {
      state.lastError = 'Очередь событий переполнена. Переподключите расширение.';
      await writeState(state);
      return;
    }
    await writeState(state); // Survive service-worker suspension before the upload.
    while (state.pending.length) {
      await request('/api/monitor/observations', 'POST', state.pending[0], state.token, state.base);
      state.pending.shift();
      await writeState(state);
    }
    state.lastError = '';
    await writeState(state);
  } catch (error) {
    state.lastError = error instanceof Error ? error.message : 'Нет связи с MIMAS.';
    if ([401, 403, 409].includes(error?.status)) {
      // Expired tokens never remain in storage; re-pair explicitly in the popup.
      state.token = '';
      state.activeKeys = [];
      state.pending = [];
    }
    await writeState(state);
  }
}

async function connect(code, base) {
  checkedBase(base);
  const claim = await request('/api/monitor/claim', 'POST', {code: code.trim(), component: 'extension'}, undefined, base);
  if (!claim?.token || !claim?.session_id) throw new Error('Сервер не вернул данные подключения.');
  const state = {
    token: claim.token,
    base,
    sessionId: claim.session_id,
    expiresAt: claim.expires_at,
    catalog: null,
    catalogFetchedAt: 0,
    lastHeartbeatAt: 0,
    activeKeys: [],
    pending: [],
    lastError: ''
  };
  await writeState(state);
  await ensureAlarm();
  await cycle();
  return status();
}

async function status() {
  const state = await readState();
  return {
    connected: Boolean(state?.token),
    base: state?.base || null,
    sessionId: state?.sessionId || null,
    lastError: state?.lastError || '',
    catalogCount: state?.catalog?.products?.length || 0,
    lastHeartbeatAt: state?.lastHeartbeatAt || null
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const operation = queue(async () => {
    if (message?.action === 'connect') return connect(String(message.code || ''), String(message.base || ''));
    if (message?.action === 'disconnect') {
      const state = await readState();
      let warning = '';
      if (state?.token) {
        try { await request('/api/monitor/disconnect', 'POST', {}, state.token, state.base); }
        catch { warning = 'Проверка остановлена здесь. Если сеть недоступна, сервер обновит статус после тайм-аута.'; }
      }
      await chrome.storage.session.remove(STATE_KEY);
      await chrome.alarms.clear(ALARM);
      return {...await status(), lastError: warning};
    }
    if (message?.action === 'status') return status();
    if (message?.action === 'scan') { await cycle(); return status(); }
    throw new Error('Неизвестная команда расширения.');
  });
  operation.then(value => sendResponse({ok: true, value}), error =>
    sendResponse({ok: false, error: error instanceof Error ? error.message : 'Ошибка подключения.'}));
  return true;
});

function scheduleCycle() {
  clearTimeout(debounce);
  debounce = setTimeout(() => { void queue(cycle); }, 400);
}

chrome.tabs.onCreated.addListener(scheduleCycle);
chrome.tabs.onRemoved.addListener(scheduleCycle);
chrome.tabs.onUpdated.addListener(scheduleCycle);
chrome.tabs.onActivated.addListener(scheduleCycle);
chrome.tabs.onAttached.addListener(scheduleCycle);
chrome.windows.onFocusChanged.addListener(scheduleCycle);
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void queue(cycle); });
chrome.runtime.onStartup.addListener(() => { void queue(async () => { if (await readState()) { await ensureAlarm(); await cycle(); } }); });
void queue(async () => { if (await readState()) { await ensureAlarm(); await cycle(); } });
