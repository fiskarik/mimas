// Explicit live smoke test: makes Groq calls with synthetic answers only.
const {chromium}=require(process.argv[2]||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    fs.mkdirSync('data/qa-ai-web',{recursive:true});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    page.setDefaultTimeout(120000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://localhost:3000/?view=ai');
    await page.getByRole('button',{name:'Начать AI-интервью',exact:true}).click();
    await page.locator('.ai-question h2').waitFor();
    const first=await page.locator('.ai-question h2').innerText();
    await page.getByLabel('Ваш ответ или код').fill('я не знаю');
    await page.getByRole('button',{name:'Отправить ответ',exact:true}).click();
    await page.getByText(/сохранено ответов: 1/).waitFor();
    const second=await page.locator('.ai-question h2').innerText();
    assert.notEqual(first,second);
    await page.reload();
    await page.getByText(/сохранено ответов: 1/).waitFor();
    assert.equal(await page.locator('.ai-question h2').innerText(),second);
    await page.getByLabel('Ваш ответ или код').fill('A generator yields values lazily when next() is called, retaining its execution state between yields. It avoids materializing the full sequence; an exhausted generator must be recreated for another pass. sys.getsizeof is shallow and does not measure referenced objects.');
    await page.getByRole('button',{name:'Отправить ответ',exact:true}).click();
    await page.getByText(/сохранено ответов: 2/).waitFor();
    await page.screenshot({path:'data/qa-ai-web/interview.png',fullPage:true});
    await page.getByRole('button',{name:'Завершить и показать отчёт',exact:true}).click();
    await page.getByRole('heading',{name:'Отчёт по интервью',exact:true}).waitFor();
    await page.screenshot({path:'data/qa-ai-web/report.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow');
    await page.screenshot({path:'data/qa-ai-web/mobile.png',fullPage:true});
    const session=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('ai-access')).id);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({result:'PASS',session,checks:['live start','abstention','different next question','reload resume','substantive answer','report','mobile','no JS errors']}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
