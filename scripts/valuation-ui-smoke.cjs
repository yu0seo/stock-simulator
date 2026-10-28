// Runs against a local Vite server; all API responses are fixtures, no real keys used.
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE||'playwright');
const fs=require('node:fs');
const path=require('node:path');
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const stock={symbol:'005930',name:'삼성전자',sector:'반도체',color:'#2057ad',price:20000,change:1.2,per:null,pbr:null,source:'toss',updated_at:new Date().toISOString()};
  let value={symbol:stock.symbol,price:20000,per:10,pbr:20,source:'opendart',year:'2025',as_of:'2025-12-31',statement:'연결',eps:2000,bps:1000,eps_source:'재무제표 기본 EPS',per_reason:null,pbr_reason:null,filing_url:'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260317000001'};
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url());let data,status=200;
    switch(url.pathname){
      case '/api/config':data={market_mode:'toss',auth_mode:'local',financial_mode:'opendart',initial_capital:10000000,game_days:90,market_open:true,poll_seconds:15,difficulties:{easy:{label:'차근차근',loan:10000000,rate:.04}}};break;
      case '/api/market':data={stocks:[stock],source:'toss',market_open:true};break;
      case '/api/market/valuations':data={items:[value]};break;
      case '/api/auth/me':status=401;data={detail:'로그인해주세요.'};break;
      case '/api/lessons':data=[];break;
      case '/api/market/005930/chart':data={source:'toss',points:[{date:'2026-10-27',value:19000},{date:'2026-10-28',value:20000}]};break;
      default:status=404;data={detail:'fixture not defined'};
    }
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  });
  try{
    await page.goto('http://127.0.0.1:5173',{waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:'종목 탐색',exact:true}).click();
    await page.getByRole('cell',{name:'10.00배 2025 연간',exact:true}).waitFor();
    await page.getByRole('cell',{name:'20.00배 2025 연간',exact:true}).waitFor();
    await page.getByRole('button',{name:'삼성전자 상세 보기'}).click();
    const dialog=page.getByRole('dialog');
    await dialog.getByText('2025년 연간 공시 기준',{exact:true}).waitFor();
    await dialog.getByRole('link',{name:'계산에 사용한 DART 공시 보기 ↗'}).waitFor();
    await dialog.getByText('기본 EPS 2,000원',{exact:true}).waitFor();
    fs.mkdirSync('artifacts',{recursive:true});
    await page.screenshot({path:path.resolve('artifacts/annual-valuation-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.resolve('artifacts/annual-valuation-mobile.png'),fullPage:true});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Mobile overflow');
    await page.getByRole('button',{name:'닫기',exact:true}).click();
    value={...value,per:null,pbr:null,per_reason:'EPS가 0 이하라 PER을 산출하지 않아요.',pbr_reason:'우선주 자본 배분 근거가 부족해요.'};
    await page.reload({waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:'삼성전자 상세 보기'}).click();
    await page.getByText('PER 산출 불가: EPS가 0 이하라 PER을 산출하지 않아요.',{exact:true}).waitFor();
    await page.getByText('PBR 산출 불가: 우선주 자본 배분 근거가 부족해요.',{exact:true}).waitFor();
    if(errors.length)throw new Error(errors.join('\n'));
    console.log('Annual valuation UI passed: ratios, annual year, EPS/BPS, filing link, missing-data reasons, desktop and mobile.');
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
