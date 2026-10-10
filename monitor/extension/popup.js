const form = document.getElementById('pair-form');
const code = document.getElementById('code');
const base = document.getElementById('base');
const statusBox = document.getElementById('status');
const disconnect = document.getElementById('disconnect');

async function send(action, extra = {}) {
  const reply = await chrome.runtime.sendMessage({action, ...extra});
  if (!reply?.ok) throw new Error(reply?.error || 'Ошибка расширения.');
  return reply.value;
}

function show(value) {
  if (value.base) base.value = value.base;
  form.hidden = value.connected;
  disconnect.hidden = !value.connected;
  statusBox.className = value.lastError ? 'error' : '';
  statusBox.textContent = value.lastError || (value.connected
    ? `Подключено к интервью. Каталог: ${value.catalogCount} продуктов.`
    : 'Не подключено. Выберите тот же адрес, на котором открыто интервью, и получите код.');
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  statusBox.textContent = 'Подключаем…';
  try { show(await send('connect', {code: code.value.trim(), base: base.value})); code.value = ''; }
  catch (error) { statusBox.className = 'error'; statusBox.textContent = error.message; }
});

disconnect.addEventListener('click', async () => {
  try { show(await send('disconnect')); }
  catch (error) { statusBox.className = 'error'; statusBox.textContent = error.message; }
});

send('status').then(show, error => { statusBox.className = 'error'; statusBox.textContent = error.message; });
