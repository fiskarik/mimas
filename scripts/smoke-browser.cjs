// Run against python run_demo.py. Uses Chromium's synthetic camera/microphone only.
// node scripts/smoke-browser.cjs <path-to-playwright-module>
const { chromium } = require(process.argv[2] || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const artifacts = path.resolve(__dirname, '../data/qa-browser');
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({
    channel: 'msedge', headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'],
  });
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1100}, permissions: ['camera', 'microphone']});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.setDefaultTimeout(60000);
    await page.goto('http://localhost:3000/?view=company');
    await page.getByRole('button', {name: 'Открыть кабинет'}).click();
    await page.getByPlaceholder('Например, Алексей Иванов').fill('Автотест — синтетическая камера');
    await page.getByRole('button', {name: 'Создать приглашение'}).click();
    const invite = page.getByLabel('Ссылка приглашения');
    await invite.waitFor();
    const url = await invite.inputValue();
    await page.screenshot({path: path.join(artifacts, 'dashboard.png'), fullPage: true});
    const candidate = await context.newPage();
    candidate.setDefaultTimeout(60000);
    candidate.on('pageerror', error => errors.push(error.message));
    await candidate.goto(url);
    await candidate.getByRole('button', {name: 'Проверить устройства'}).click();
    await candidate.getByText('Камера подключена', {exact: true}).waitFor();
    await candidate.getByRole('checkbox').check();
    await candidate.getByRole('button', {name: 'Начать интервью'}).click();
    await candidate.getByText('Этап 1 / 5', {exact: true}).waitFor();
    // Exercise the real paste handler with a synthetic clipboard event.
    await candidate.getByPlaceholder('Запишите голосовой ответ или напишите здесь…').evaluate(el => {
      const transfer = new DataTransfer(); transfer.setData('text/plain', 'Synthetic clipboard text');
      el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: transfer, bubbles: true}));
    });
    await candidate.getByRole('alert').filter({hasText: 'Вставка в ответ'}).waitFor();
    await candidate.screenshot({path: path.join(artifacts, 'interview.png'), fullPage: true});
    const answers = ['Аргументы по умолчанию создаются один раз. Использую None и создаю список внутри функции.',
      'CPU-bound работа блокирует event loop. Вынесу её в отдельный процесс.',
      'Индекс полезен для селективного поиска. При записи его нужно обновлять.'];
    for (let index = 0; index < answers.length; index++) {
      await candidate.getByPlaceholder('Запишите голосовой ответ или напишите здесь…').fill(answers[index]);
      await candidate.getByRole('button', {name: 'Отправить ответ'}).click();
      await candidate.getByText(`Этап ${index + 2} / 5`, {exact: true}).waitFor();
    }
    await candidate.getByLabel('Python-код').fill('def group_users(users):\n    result = {}\n    for user in users:\n        result.setdefault(user["city"], []).append(user["name"])\n    return result');
    await candidate.getByRole('button', {name: 'Отправить ответ'}).click();
    await candidate.getByText('Этап 5 / 5', {exact: true}).waitFor();
    await candidate.getByPlaceholder('Запишите голосовой ответ или напишите здесь…').fill('Обхожу пользователей один раз, O(n). append сохраняет порядок имён. Без city будет KeyError.');
    await candidate.getByRole('button', {name: 'Отправить ответ'}).click();
    await candidate.getByRole('button', {name: 'Завершить и сохранить'}).click();
    await candidate.getByText('ИНТЕРВЬЮ ЗАВЕРШЕНО', {exact: true}).waitFor();
    await candidate.getByText('Видео сохранено', {exact: true}).waitFor();
    await page.bringToFront();
    await page.getByRole('button', {name: 'Обновить', exact: true}).click();
    await page.getByRole('button', {name: 'Отчёт', exact: true}).first().click();
    await page.getByText('ОТЧЁТ ОБ ИНТЕРВЬЮ', {exact: true}).waitFor();
    await page.getByRole('button', {name: 'Запись и события', exact: true}).click();
    const video = page.locator('.video-report video');
    await video.waitFor();
    await page.waitForFunction(() => {
      const video = document.querySelector('.video-report video');
      return video && video.readyState >= 2 && video.videoWidth > 0;
    });
    assert.equal(await page.getByText('Не оценено', {exact: true}).count(), 5);
    assert.ok(await page.locator('.timeline-event').count() >= 1);
    await video.evaluate(async el => {el.muted = true; await el.play();});
    await page.waitForFunction(() => document.querySelector('.video-report video').currentTime > 0);
    await page.screenshot({path: path.join(artifacts, 'report.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(artifacts, 'report-mobile.png'), fullPage: true});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Mobile layout overflow');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({result: 'PASS', checks: ['invite', 'synthetic camera and microphone', 'paste warning', '5 answers', 'chunk upload', 'recording playback', 'report', 'mobile layout', 'no page errors'], artifacts}));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
