// Browser -> real FastAPI -> SQLite -> runtime, with an explicitly scripted LLM on :8001.
const {chromium}=require(process.argv[2]||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/ai/sessions**',async route=>{
      const url=new URL(route.request().url());url.hostname='127.0.0.1';url.port='8001';
      const response=await route.fetch({url:url.toString()});await route.fulfill({response});
    });
    await page.goto('http://localhost:3000/?view=ai');
    await page.getByRole('button',{name:'Начать AI-интервью',exact:true}).click();
    await page.locator('.ai-question h2').waitFor();
    async function answer(text,count){
      await page.getByLabel('Ваш ответ или код').fill(text);
      await page.getByRole('button',{name:'Отправить ответ',exact:true}).click();
      await page.getByText(`сохранено ответов: ${count}`,{exact:false}).waitFor();
    }
    await answer('не знаю',1);
    await answer('Генератор возвращает элементы по мере запроса.',2);
    const pasted='Объект хранит состояние между вызовами. '.repeat(25);
    await page.getByLabel('Ваш ответ или код').evaluate((el,text)=>{
      const data=new DataTransfer();data.setData('text/plain',text);
      el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true}));
    },pasted);
    await answer(pasted,3);
    assert.match(await page.locator('.ai-question h2').innerText(),/Объясните ключевую мысль/);
    const question=await page.locator('.ai-question h2').innerText();
    await page.reload();
    await page.locator('.ai-question h2').waitFor();
    assert.equal(await page.locator('.ai-question h2').innerText(),question);
    await answer('Следующий вызов продолжает выполнение с сохранённой позиции.',4);
    await page.getByRole('button',{name:'Завершить и показать отчёт',exact:true}).click();
    await page.getByRole('heading',{name:'Отчёт по интервью',exact:true}).waitFor();
    await page.getByText('Понимание подтверждено',{exact:true}).waitFor();
    assert.ok(await page.getByText('Большая вставка текста',{exact:true}).isVisible());
    fs.mkdirSync('data/qa-runtime-browser',{recursive:true});
    await page.screenshot({path:'data/qa-runtime-browser/report.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:'data/qa-runtime-browser/mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({result:'PASS',provider:'SCRIPTED',checks:['no answer','positive evidence','paste event','automatic verification','reload','resolved verification','final report','mobile']}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
