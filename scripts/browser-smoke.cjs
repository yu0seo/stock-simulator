// Optional UI smoke test. Install playwright or set PLAYWRIGHT_PACKAGE to its package path.
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE||'playwright');
const path=require('node:path');
const fs=require('node:fs');
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const context=await browser.newContext({viewport:{width:1440,height:1080}});
  const page=await context.newPage();
  const errors=[];
  let testUserId;
  page.on('response',async r=>{if(r.url().endsWith('/api/auth/signup')&&r.ok()){const d=await r.json();testUserId=d.user?.id;}});
  page.on('pageerror',e=>errors.push(e.message));
  const output=path.resolve('artifacts');fs.mkdirSync(output,{recursive:true});
  try{
    await page.goto('http://127.0.0.1:5173',{waitUntil:'domcontentloaded',timeout:60000});
    const config=await (await context.request.get('http://127.0.0.1:5173/api/config')).json();
    if(config.auth_mode!=='local'||config.market_mode!=='sample')throw new Error('UI smoke requires local auth and sample market data.');
    await page.getByRole('heading',{name:'오늘의 배움, 내일의 투자.'}).waitFor();
    await page.getByRole('button',{name:'삼성전자 상세 보기'}).waitFor();
    await page.screenshot({path:path.join(output,'dashboard-desktop.png'),fullPage:true});
    await page.getByRole('button',{name:'삼성전자 상세 보기'}).click();
    await page.getByRole('heading',{name:/72,800원/}).waitFor();
    await page.getByRole('button',{name:'재무정보',exact:true}).click();
    await page.getByText('매출액',{exact:true}).waitFor();
    await page.getByRole('button',{name:'비슷한 기업',exact:true}).click();
    await page.getByText(/K-means 3개 군집/).waitFor();
    await page.getByRole('button',{name:'닫기',exact:true}).click();
    await page.getByRole('button',{name:/^투자 배움터/}).click();
    await page.getByRole('heading',{name:'어려운 투자, 쉽게 배워요'}).waitFor();
    await page.locator('.lesson-card').first().click();
    await page.getByRole('dialog').getByRole('heading',{name:'PER, 이 회사의 가격표 읽기'}).waitFor();
    await page.getByRole('button',{name:'닫기',exact:true}).click();
    await page.getByRole('button',{name:'투자 랭킹',exact:true}).click();
    await page.getByRole('heading',{name:'함께 배우고, 함께 성장해요'}).waitFor();
    await page.getByRole('button',{name:'로그인 / 회원가입'}).click();
    await page.getByRole('textbox',{name:'닉네임'}).fill('검증'+Date.now().toString().slice(-8));
    await page.getByRole('textbox',{name:'이메일',exact:true}).fill('smoke-'+Date.now()+'@example.com');
    await page.getByLabel('비밀번호',{exact:true}).fill('local-smoke-test-2026');
    await page.getByRole('button',{name:'회원가입하고 시작하기'}).click();
    await page.getByRole('heading',{name:'어떤 여정을 시작할까요?'}).waitFor();
    await page.getByRole('button',{name:'이 조건으로 시작하기'}).click();
    await page.getByRole('button',{name:'대시보드',exact:true}).click();
    await page.getByRole('button',{name:'삼성전자 상세 보기'}).click();
    await page.getByRole('button',{name:'매수하기',exact:true}).click();
    await page.getByRole('status').filter({hasText:'모의 주문이 체결됐어요.'}).waitFor();
    await page.getByRole('button',{name:'닫기',exact:true}).click();
    await page.getByRole('button',{name:'내 투자',exact:true}).click();
    await page.getByText('삼성전자',{exact:true}).first().waitFor();
    await page.screenshot({path:path.join(output,'portfolio-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'메뉴 열기'}).click();
    await page.getByRole('button',{name:'대시보드',exact:true}).click();
    await page.screenshot({path:path.join(output,'dashboard-mobile.png'),fullPage:true});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow)throw new Error('Horizontal overflow at mobile width');
    if(errors.length)throw new Error(errors.join('\n'));
    console.log('UI smoke passed: dashboard, details, financials, clustering, learning, ranking, signup, start, buy, portfolio, mobile.');
  }finally{
    await browser.close();
    if(testUserId){
      // Remove only the account created by this test; no real user records are touched.
      const {spawnSync}=require('node:child_process');
      const cleanup=spawnSync(path.resolve('.venv/Scripts/python.exe'),['-c',"import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); uid=sys.argv[2]; db.execute('DELETE FROM accounts WHERE user_id=?',(uid,)); db.execute('DELETE FROM sessions WHERE user_id=?',(uid,)); db.execute('DELETE FROM users WHERE id=? AND email LIKE ?',(uid,'smoke-%@example.com')); db.commit(); db.close()",path.resolve('backend/data/daega.sqlite3'),testUserId]);
      if(cleanup.status!==0)console.warn('Test account cleanup failed; remove the smoke account from the local development database.');
    }
  }
}
main().catch(e=>{console.error(e);process.exitCode=1;});
