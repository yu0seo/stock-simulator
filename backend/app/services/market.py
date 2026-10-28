import asyncio
import math
import time
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import HTTPException
from app.core.config import settings
from app.services.catalog import STOCKS, BY_SYMBOL

KST = timezone(timedelta(hours=9))

class Market:
    def __init__(self):
        self.token = ''
        self.token_until = 0
        self.cache = {}
        self.lock = asyncio.Lock()
        self.request_lock = asyncio.Lock()

    async def kis(self, path, tr_id, params):
        async with self.request_lock:
            async with httpx.AsyncClient(timeout=15) as client:
                if time.time() >= self.token_until:
                    r = await client.post(settings.kis_base_url + '/oauth2/tokenP', json={'grant_type':'client_credentials','appkey':settings.kis_app_key,'appsecret':settings.kis_app_secret})
                    r.raise_for_status()
                    data = r.json()
                    self.token = data['access_token']
                    self.token_until = time.time() + int(data.get('expires_in', 86400)) - 120
                r = await client.get(settings.kis_base_url + path, params=params, headers={'authorization':f'Bearer {self.token}','appkey':settings.kis_app_key,'appsecret':settings.kis_app_secret,'tr_id':tr_id,'custtype':'P'})
                r.raise_for_status()
                data = r.json()
                if data.get('rt_cd') != '0':
                    raise HTTPException(502, '한국투자증권에서 시세를 가져오지 못했습니다. 키의 권한과 API 이용 상태를 확인해주세요.')
                await asyncio.sleep(0.12)
                return data

    async def quotes(self):
        async with self.lock:
            if self.cache.get('quotes_until', 0) > time.time():
                return self.cache['quotes']
            now = datetime.now(KST)
            rows = []
            for stock in STOCKS:
                row = {k:stock[k] for k in ['symbol','name','sector','color']}
                if settings.live_market:
                    try:
                        d = (await self.kis('/uapi/domestic-stock/v1/quotations/inquire-price','FHKST01010100',{'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':stock['symbol']}))['output']
                        row.update(price=int(d['stck_prpr']), change=float(d['prdy_ctrt']), per=self.number(d.get('per')), pbr=self.number(d.get('pbr')), volume=int(d.get('acml_vol',0)), halted=d.get('temp_stop_yn')=='Y')
                    except HTTPException:
                        raise
                    except (httpx.HTTPError, KeyError, ValueError):
                        raise HTTPException(502, '실제 시세 연결에 실패했습니다. 샘플 시세로 주문을 처리하지 않습니다.')
                else:
                    row.update({k:stock[k] for k in ['price','change','per','pbr']}, volume=0)
                row.update(source='kis' if settings.live_market else 'sample', updated_at=now.isoformat())
                rows.append(row)
            self.cache.update(quotes=rows, quotes_until=time.time()+10)
            return rows

    @staticmethod
    def number(value):
        try: return float(value) if value not in ('', None) else None
        except (ValueError, TypeError): return None

    async def chart(self, symbol):
        if settings.live_market:
            now = datetime.now(KST)
            try:
                d = await self.kis('/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice','FHKST03010100',{'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':symbol,'FID_INPUT_DATE_1':(now-timedelta(days=110)).strftime('%Y%m%d'),'FID_INPUT_DATE_2':now.strftime('%Y%m%d'),'FID_PERIOD_DIV_CODE':'D','FID_ORG_ADJ_PRC':'0'})
                points = [{'date':p['stck_bsop_date'],'value':int(p['stck_clpr'])} for p in reversed(d['output2']) if p.get('stck_clpr')]
                return {'source':'kis','points':points}
            except (httpx.HTTPError, KeyError, ValueError):
                raise HTTPException(502, '차트 조회에 실패했습니다.')
        price = BY_SYMBOL[symbol]['price']
        points = [{'date':(datetime.now(KST)-timedelta(days=59-i)).strftime('%Y-%m-%d'),'value':round(price*(0.91+0.09*i/59+0.018*math.sin(i*0.65)+0.008*math.sin(i*1.9)))} for i in range(60)]
        points[-1]['value'] = price
        return {'source':'sample','points':points}

    async def financials(self, symbol):
        stock = BY_SYMBOL[symbol]
        if not settings.opendart_api_key:
            return {k:stock[k] for k in ['revenue','profit','equity','debt','roe']} | {'source':'sample','year':'학습용 예시','rows':[]}
        key = 'financial:'+symbol
        if key in self.cache: return self.cache[key]
        year = settings.dart_business_year or str(datetime.now(KST).year-1)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json', params={'crtfc_key':settings.opendart_api_key,'corp_code':stock['corp'],'bsns_year':year,'reprt_code':'11011','fs_div':'CFS'})
                r.raise_for_status()
                d = r.json()
            if d.get('status') != '000': raise HTTPException(502, f'{year}년 연결 재무제표를 조회할 수 없습니다. 공시 여부와 OpenDART 키를 확인해주세요.')
            rows = d['list']
            def amount(ids):
                for item in rows:
                    if item.get('account_id') in ids:
                        return self.number(item.get('thstrm_amount','').replace(',',''))
                return None
            revenue=amount(['ifrs-full_Revenue','ifrs-full_RevenueFromContractsWithCustomers'])
            profit=amount(['ifrs-full_ProfitLoss'])
            equity=amount(['ifrs-full_Equity'])
            liabilities=amount(['ifrs-full_Liabilities'])
            result={'source':'opendart','year':year,'revenue':revenue/1e12 if revenue is not None else None,'profit':profit/1e12 if profit is not None else None,'equity':equity/1e12 if equity is not None else None,'debt':liabilities/equity*100 if liabilities is not None and equity and equity>0 else None,'roe':None,'rows':[{'name':x['account_nm'],'amount':x.get('thstrm_amount',''),'statement':x.get('sj_nm','')} for x in rows]}
            # No ROE estimate from closing equity: average equity / attributable income are needed.
            self.cache[key]=result
            return result
        except (httpx.HTTPError, KeyError, ValueError):
            raise HTTPException(502, 'OpenDART 재무제표 연결에 실패했습니다.')

    def is_open(self):
        now=datetime.now(KST)
        return now.weekday()<5 and (9,0) <= (now.hour,now.minute) < (15,30)

    async def check_trading_day(self, symbol):
        try:
            d=await self.kis('/uapi/domestic-stock/v1/quotations/inquire-daily-price','FHKST01010400',{'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':symbol,'FID_PERIOD_DIV_CODE':'D','FID_ORG_ADJ_PRC':'0'})
            today=datetime.now(KST).strftime('%Y%m%d')
            latest=d['output'][0]
            if latest['stck_bsop_date']!=today or int(latest.get('acml_vol',0))<=0:
                raise HTTPException(400,'오늘 거래가 확인되지 않는 종목이에요. 휴장일 또는 거래정지 여부를 확인해주세요.')
        except (httpx.HTTPError,KeyError,ValueError,IndexError):
            raise HTTPException(502,'거래일을 확인할 수 없어 주문을 중단했어요.')

market=Market()
