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

    async def toss(self, path, params):
        """Server-side read-only Toss adapter. Never calls account or order APIs."""
        async with self.request_lock:
            async with httpx.AsyncClient(timeout=15) as client:
                try:
                    for attempt in range(2):
                        if time.time() >= self.token_until:
                            r = await client.post(settings.toss_base_url.rstrip('/') + '/oauth2/token', data={'grant_type':'client_credentials','client_id':settings.toss_client_id,'client_secret':settings.toss_client_secret})
                            self.check_response(r)
                            data = r.json()
                            token = data['access_token']
                            expires = int(data['expires_in'])
                            if not isinstance(token,str) or not token or expires<=0:
                                raise ValueError('Invalid token response')
                            self.token = token
                            self.token_until = time.time() + max(1, expires-min(120,expires/10))
                        r = await client.get(settings.toss_base_url.rstrip('/') + path, params=params, headers={'authorization':f'Bearer {self.token}'})
                        if r.status_code==401 and attempt==0:
                            self.token_until=0
                            continue
                        self.check_response(r)
                        data=r.json()
                        if not isinstance(data,dict) or 'result' not in data or 'error' in data:
                            raise ValueError('Invalid Toss envelope')
                        return data['result']
                except (httpx.HTTPError,KeyError,ValueError,TypeError):
                    raise HTTPException(502,'토스증권 시세 연결 또는 응답을 확인할 수 없어요. 샘플 시세로 대체하지 않습니다.') from None
                finally:
                    # Shared conservative pacing across API groups, including charts.
                    await asyncio.sleep(0.25)

    @staticmethod
    def check_response(response):
        messages={400:'토스증권 인증정보 또는 요청 형식을 확인해주세요.',401:'토스증권 인증이 만료됐거나 인증정보가 올바르지 않아요.',403:'토스증권 Open API의 허용 IP 등록과 이용 권한을 확인해주세요.',429:'토스증권 API 요청 한도에 도달했어요. 잠시 후 다시 시도해주세요.'}
        if response.is_error:
            raise HTTPException(502,messages.get(response.status_code,'토스증권 시세 서버에 연결하지 못했어요.'))

    @staticmethod
    def timestamp(value):
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is None: raise ValueError('Missing timestamp timezone')
        return parsed.astimezone(KST)

    @classmethod
    def price(cls,value):
        result=cls.number(value)
        if result is None or result<=0 or not result.is_integer():
            raise ValueError('Invalid KRW price')
        return int(result)

    async def candles(self,symbol):
        key='candles:'+symbol
        if self.cache.get(key+':until',0)>time.time(): return self.cache[key]
        result=await self.toss('/api/v1/candles',{'symbol':symbol,'interval':'1d','count':100,'adjusted':'false'})
        try:
            rows=result['candles']
            normalized=[]
            for row in rows:
                if row['currency']!='KRW': raise ValueError('Unsupported currency')
                volume=self.number(row['volume'])
                if volume is None or volume<0: raise ValueError('Invalid volume')
                normalized.append({'date':self.timestamp(row['timestamp']).date().isoformat(),'value':self.price(row['closePrice']),'volume':volume})
            normalized.sort(key=lambda p:p['date'])
        except (KeyError,TypeError,ValueError):
            raise HTTPException(502,'토스증권 차트 응답을 확인할 수 없어요.') from None
        self.cache[key]=normalized
        self.cache[key+':until']=time.time()+60
        return normalized

    async def quotes(self):
        async with self.lock:
            if self.cache.get('quotes_until', 0) > time.time():
                return self.cache['quotes']
            now = datetime.now(KST)
            rows = []
            live={}
            if settings.live_market:
                result=await self.toss('/api/v1/prices',{'symbols':','.join(BY_SYMBOL)})
                try:
                    live={q['symbol']:q for q in result}
                    if not set(BY_SYMBOL).issubset(live): raise ValueError('Missing quote')
                except (KeyError,TypeError,ValueError):
                    raise HTTPException(502,'토스증권에서 일부 종목의 시세가 누락됐어요.') from None
            for stock in STOCKS:
                row = {k:stock[k] for k in ['symbol','name','sector','color']}
                if settings.live_market:
                    try:
                        q=live[stock['symbol']]
                        if q['currency']!='KRW': raise ValueError('Unsupported currency')
                        price=self.price(q['lastPrice'])
                        quote_time=q.get('timestamp')
                        quote_day=self.timestamp(quote_time).date() if quote_time is not None else now.date()
                        candles=await self.candles(stock['symbol'])
                        previous=[p for p in candles if p['date']<quote_day.isoformat()]
                        previous_close=previous[-1]['value'] if previous else None
                        row.update(price=price,change=round((price/previous_close-1)*100,4) if previous_close else None,per=None,pbr=None,quote_at=quote_time)
                    except HTTPException:
                        raise
                    except (httpx.HTTPError, KeyError, ValueError,TypeError):
                        raise HTTPException(502, '실제 시세 연결에 실패했습니다. 샘플 시세로 주문을 처리하지 않습니다.')
                else:
                    row.update({k:stock[k] for k in ['price','change','per','pbr']}, volume=0)
                row.update(source='toss' if settings.live_market else 'sample', updated_at=now.isoformat())
                rows.append(row)
            self.cache.update(quotes=rows, quotes_until=time.time()+10)
            return rows

    @staticmethod
    def number(value):
        try:
            result=float(value) if value not in ('', None) else None
            return result if result is not None and math.isfinite(result) else None
        except (ValueError, TypeError): return None

    async def chart(self, symbol):
        if settings.live_market:
            return {'source':'toss','points':[{'date':p['date'],'value':p['value']} for p in await self.candles(symbol)]}
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

    async def regular_session(self):
        today=datetime.now(KST).date().isoformat()
        key='calendar:'+today
        if self.cache.get(key+':until',0)>time.time(): return self.cache[key]
        result=await self.toss('/api/v1/market-calendar/KR',{'date':today})
        try:
            day=result['today']
            if day['date']!=today: raise ValueError('Unexpected calendar date')
            integrated=day['integrated']
            regular=integrated['regularMarket'] if integrated is not None else None
            session=None
            if regular is not None:
                start=self.timestamp(regular['startTime'])
                end=self.timestamp(regular['endTime'])
                if start.date().isoformat()!=today or end<=start: raise ValueError('Invalid session')
                session=(start,end)
        except (KeyError,TypeError,ValueError):
            raise HTTPException(502,'토스증권 장 운영 정보를 확인할 수 없어요.') from None
        self.cache[key]=session
        self.cache[key+':until']=time.time()+60
        return session

    async def trading_open(self):
        if not settings.live_market: return self.is_open()
        session=await self.regular_session()
        return bool(session and session[0]<=datetime.now(KST)<session[1])

    async def check_trading_day(self,symbol,quote):
        if not await self.trading_open():
            raise HTTPException(400,'휴장일 또는 정규장 운영 시간이 아니에요.')
        result=await self.toss('/api/v1/stocks',{'symbols':symbol})
        try:
            info=next(s for s in result if s['symbol']==symbol)
            detail=info['koreanMarketDetail']
            if not isinstance(detail,dict): raise ValueError('Missing trading status')
            krx=detail['krxTradingSuspended']
            nxt=detail['nxtTradingSuspended']
            supported=detail['nxtSupported']
            if not isinstance(krx,bool) or not isinstance(supported,bool) or (supported and not isinstance(nxt,bool)):
                raise ValueError('Missing trading status')
            halted=krx and (not supported or nxt)
            if info['status']!='ACTIVE' or halted:
                raise HTTPException(400,'상장 상태가 비활성이거나 거래정지된 종목이에요.')
            # Reject old/null quotes rather than fill orders at an inactive price.
            stamp=self.timestamp(quote['quote_at'])
            age=(datetime.now(KST)-stamp).total_seconds()
            if age < -60 or age > 120:
                raise HTTPException(400,'최근 2분 이내의 시세가 없어 주문을 중단했어요.')
        except (KeyError,TypeError,ValueError,StopIteration):
            raise HTTPException(502,'종목 거래 상태 또는 시세 시각을 확인할 수 없어 주문을 중단했어요.') from None

market=Market()
