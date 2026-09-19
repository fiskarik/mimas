const {chromium} = require(process.argv[2]);
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  fs.mkdirSync('data/qa-design', {recursive:true});
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://localhost:3000');
    await page.getByRole('button',{name:'Посмотреть демо',exact:true}).waitFor();
    await page.screenshot({path:'data/qa-design/landing.png',fullPage:true});
    await page.getByRole('button',{name:'Посмотреть демо',exact:true}).click();
    await page.getByRole('button',{name:'Слушает',exact:true}).click();
    assert.equal(await page.locator('.preview-agent .orb-listening').count(),1);
    await page.getByRole('button',{name:'Следующий вопрос',exact:true}).click();
    await page.locator('.preview-validation').waitFor();
    await page.getByPlaceholder('Я бы начал с того, что…').fill('Тест просмотра');
    await page.getByRole('button',{name:'Следующий вопрос',exact:true}).click();
    await page.getByText('Python Backend · вопрос 2 из 3',{exact:true}).waitFor();
    await page.screenshot({path:'data/qa-design/preview.png',fullPage:true});
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog').count(),0);
    assert.equal(await page.getByRole('button',{name:'Посмотреть демо',exact:true}).evaluate(el=>el===document.activeElement),true);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'data/qa-design/mobile.png',fullPage:true});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile overflow');
    await page.getByRole('button',{name:'Посмотреть демо',exact:true}).click();
    await page.screenshot({path:'data/qa-design/preview-mobile.png',fullPage:true});
    await page.keyboard.press('Escape');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.locator('.hero-art .orb-sculpture').evaluate(el=>getComputedStyle(el).animationName),'none');
    await page.getByRole('button',{name:'Войти в кабинет',exact:true}).click();
    await page.getByRole('button',{name:'Открыть кабинет',exact:true}).waitFor();
    assert.deepEqual(errors,[]);
    console.log('PASS: landing, preview, states, validation, next question, focus, mobile, reduced motion, company route');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
