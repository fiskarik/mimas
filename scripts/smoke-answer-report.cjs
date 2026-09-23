// Uses a synthetic report; makes no Groq requests and changes no real interview.
const {chromium}=require(process.argv[2]);
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
  const data=JSON.parse(fs.readFileSync('data/qa-answer-report/fixture.json','utf8'));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>sessionStorage.setItem('ai-access',JSON.stringify({id:'score-fixture',token:'test-only'})));
    await page.route('**/api/ai/sessions/score-fixture',route=>route.fulfill({json:data}));
    await page.goto('http://localhost:3000/?view=ai');
    await page.getByRole('heading',{name:'Баллы и разбор каждого ответа'}).waitFor();
    assert.equal(await page.locator('.answer-review').count(),5);
    assert.equal(await page.getByLabel('Балл за ответ: 0 из 5',{exact:true}).count(),1);
    assert.equal(await page.getByLabel('Балл за ответ: 2 из 5',{exact:true}).count(),1);
    assert.equal(await page.getByLabel('Балл за ответ: 5 из 5',{exact:true}).count(),1);
    assert.equal(await page.getByLabel('Ответ не оценён',{exact:true}).count(),2);
    assert.equal(await page.locator('.review-answer mark').first().innerText(),'asyncio запускает вычисления на нескольких ядрах');
    await page.getByText('Как считаются баллы от 0 до 5',{exact:true}).click();
    await page.getByText('Не оценено — отказ, ответ не по теме, недостаточно оснований или сбой AI.',{exact:true}).waitFor();
    await page.screenshot({path:'data/qa-answer-report/desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow');
    await page.screenshot({path:'data/qa-answer-report/mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('PASS: 0/2/5 points, two unrated answers, exact error highlight, rubric, mobile, no JS errors');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
