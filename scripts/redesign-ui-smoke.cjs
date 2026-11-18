// Visual regression checks against the isolated scripts/preview_history.py server.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/dndud/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),assert=require('assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:8091';
  const post=async(path,data={})=>{const r=await page.request.post(base+'/api'+path,{data});assert(r.ok(),path+': '+await r.text());return r;};
  const nav=name=>page.locator('.primary-nav').getByRole('button',{name,exact:true});
  const shot=async name=>{await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'artifacts/'+name,fullPage:true});};
  const fits=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Page overflows the viewport');
  try{
    fs.mkdirSync('artifacts',{recursive:true});
    await post('/auth/signup',{email:'design-'+Date.now()+'@example.com',nickname:'디자인'+String(Date.now()).slice(-6),password:'isolated-design-test'});
    await post('/game/start');await post('/game/resume');await post('/game/debug/last-day');
    await post('/trades',{symbol:'005930',side:'buy',quantity:10});
    await post('/game/debug/last-day',{settle:true});await post('/game/pay');
    for(let month=2;month<=3;month++){await post('/game/resume');await post('/game/debug/last-day',{settle:true});await post('/game/pay');}
    await page.goto(base);await page.getByRole('heading',{name:'분기 전략 수립',exact:true}).waitFor();
    for(const width of [320,390,768,1280,1920]){
      await page.setViewportSize({width,height:width>760?1050:844});
      await fits();
      await shot('redesign-home-'+width+'.png');
    }
    await page.setViewportSize({width:1440,height:1050});
    await nav('자산과 거래').click();await page.getByRole('heading',{name:'보유 종목',exact:true}).waitFor();
    assert.equal(await page.locator('tbody tr').count(),1);
    await shot('redesign-portfolio-desktop.png');
    await page.setViewportSize({width:390,height:844});await fits();await shot('redesign-portfolio-mobile.png');
    await nav('종목·재무 탐색').click();
    await page.getByLabel('종목 검색').fill('삼성전자');assert.equal(await page.locator('tbody tr').count(),1);
    await page.locator('tbody').getByRole('button',{name:'상세·주문',exact:true}).click();
    await page.locator('.chart-wrap svg').waitFor();await fits();await shot('redesign-order-mobile.png');
    await page.getByRole('button',{name:'재무제표',exact:true}).click();await page.locator('.report-meta').waitFor();
    await fits();await shot('redesign-financial-mobile.png');
    await page.keyboard.press('Escape');assert.equal(await page.locator('.stock-modal').count(),0);
    await nav('투자 배움터').click();await page.locator('.lesson-card').first().click();
    await page.locator('.quiz-options button').nth(1).click();await page.getByRole('button',{name:'정답 확인하기',exact:true}).click();
    await page.getByText('정답이에요. 학습을 기록했어요.',{exact:true}).waitFor();
    await fits();await shot('redesign-quiz-mobile.png');await page.keyboard.press('Escape');
    await nav('생존 랭킹').click();await page.getByRole('heading',{name:'끝까지 남은 선택들.',exact:true}).waitFor();
    await fits();await shot('redesign-ranking-mobile.png');
    await page.setViewportSize({width:1440,height:1050});await shot('redesign-ranking-desktop.png');
    await page.getByRole('button',{name:'이전 기록 보관함',exact:true}).click();await page.getByRole('heading',{name:'이전 기록 보관함',exact:true}).waitFor();
    await page.keyboard.press('Escape');
    assert.deepEqual(errors,[]);
    console.log('Passed: 320/390/768/1280/1920 layouts, funded portfolio, stock search, chart/order and financial dialogs, quiz, ranking, history, keyboard dismissal.');
  }catch(e){await page.screenshot({path:'artifacts/redesign-visual-failure.png',fullPage:true});throw e;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
