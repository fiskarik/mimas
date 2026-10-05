const form = document.getElementById('pair-form');
const code = document.getElementById('code');
const statusBox = document.getElementById('status');
const disconnect = document.getElementById('disconnect');

async function send(action, extra = {}) {
  const reply = await chrome.runtime.sendMessage({action, ...extra});
  if (!reply?.ok) throw new Error(reply?.error || 'Ошибка расширения.');
  return reply.value;
}

function show(value) {
  form.hidden = value.connected;
  disconnect.hidden = !value.connected;
  statusBox.className = value.lastError ? 'error' : '';
  statusBox.textContent = value.lastError || (value.connected
    ? `Подключено к интервью. Каталог: ${value.catalogCount} продуктов.`
    : 'Не подключено. Получите код перед интервью.');
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  statusBox.textContent = 'Подключаем…';
  try { show(await send('connect', {code: code.value.trim()})); code.value = ''; }
  catch (error) { statusBox.className = 'error'; statusBox.textContent = error.message; }
});

disconnect.addEventListener('click', async () => {
  try { show(await send('disconnect')); }
  catch (error) { statusBox.className = 'error'; statusBox.textContent = error.message; }
});

send('status').then(show, error => { statusBox.className = 'error'; statusBox.textContent = error.message; });
