"""Provider regression tests use documented Toss envelopes, never real keys."""
import asyncio
from datetime import datetime, timedelta
import httpx
import pytest
from fastapi import HTTPException
from app.core.config import settings
from app.services.market import Market, KST
from app.services.catalog import BY_SYMBOL

@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings,'data_mode','auto')
    monkeypatch.setattr(settings,'toss_client_id','test-client')
    monkeypatch.setattr(settings,'toss_client_secret','test-secret')
    return Market()

def transport(monkeypatch,handler):
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))

def test_unauthorized_token_refreshed_once(monkeypatch,live):
    tokens=[]
    gets=[]
    def handler(r):
        if r.url.path=='/oauth2/token':
            tokens.append(r)
            return httpx.Response(200,json={'access_token':'renewed','expires_in':86400})
        gets.append(r)
        if len(gets)==1: return httpx.Response(401,json={'error':{'code':'unauthorized'}})
        assert r.headers['authorization']=='Bearer renewed'
        return httpx.Response(200,json={'result':[]})
    transport(monkeypatch,handler)
    live.token='expired-elsewhere'
    live.token_until=10**12
    assert asyncio.run(live.toss('/api/v1/prices',{'symbols':'005930'}))==[]
    assert len(tokens)==1 and len(gets)==2

@pytest.mark.parametrize('status,fragment',[(401,'인증'),(403,'허용 IP'),(429,'요청 한도'),(500,'연결')])
def test_auth_errors_are_safe_and_do_not_retry_forever(monkeypatch,live,status,fragment):
    calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(status,json={'error_description':'sensitive upstream details test-secret'})
    transport(monkeypatch,handler)
    with pytest.raises(HTTPException) as error:
        asyncio.run(live.quotes())
    assert error.value.status_code==502 and fragment in error.value.detail
    assert 'test-secret' not in error.value.detail
    assert len(calls)==1
    assert 'quotes' not in live.cache

@pytest.mark.parametrize('result',[[{'symbol':'005930','lastPrice':'80000','currency':'KRW'}],{'bad':'shape'}])
def test_partial_or_malformed_quotes_never_fill_from_samples(monkeypatch,live,result):
    async def fake(path,params): return result
    monkeypatch.setattr(live,'toss',fake)
    with pytest.raises(HTTPException) as error: asyncio.run(live.quotes())
    assert error.value.status_code==502 and 'quotes' not in live.cache

def test_missing_timestamp_and_previous_close_are_not_fabricated(monkeypatch,live):
    async def fake(path,params):
        if path=='/api/v1/prices':
            return [{'symbol':s,'lastPrice':'72000','currency':'KRW','timestamp':None} for s in BY_SYMBOL]
        return {'candles':[]}
    monkeypatch.setattr(live,'toss',fake)
    rows=asyncio.run(live.quotes())
    assert all(r['change'] is None and r['quote_at'] is None for r in rows)

def test_last_trading_day_change_on_weekend_or_holiday(monkeypatch,live):
    stamp=datetime.now(KST)-timedelta(days=1)
    older=stamp-timedelta(days=1)
    async def fake(path,params):
        if path=='/api/v1/prices':
            return [{'symbol':s,'lastPrice':'80000','currency':'KRW','timestamp':stamp.isoformat()} for s in BY_SYMBOL]
        return {'candles':[{'timestamp':stamp.isoformat(),'closePrice':'80000','volume':'10','currency':'KRW'},{'timestamp':older.isoformat(),'closePrice':'64000','volume':'10','currency':'KRW'}]}
    monkeypatch.setattr(live,'toss',fake)
    assert all(r['change']==25 for r in asyncio.run(live.changes()))

def test_chart_failure_does_not_hide_current_prices(monkeypatch,live):
    stamp=datetime.now(KST)
    older=stamp-timedelta(days=1)
    calls=[]
    async def fake(path,params):
        calls.append(path)
        if path=='/api/v1/prices':
            return [{'symbol':s,'lastPrice':'80000','currency':'KRW','timestamp':stamp.isoformat()} for s in BY_SYMBOL]
        if params['symbol']=='005930':
            raise HTTPException(502,'토스증권 API 요청 한도에 도달했어요.')
        return {'candles':[{'timestamp':older.isoformat(),'closePrice':'64000','volume':'10','currency':'KRW'}]}
    monkeypatch.setattr(live,'toss',fake)
    async def run():
        rows=await live.quotes()
        assert len(rows)==len(BY_SYMBOL)
        assert all(r['price']==80000 and r['source']=='toss' and r['quote_at']==stamp.isoformat() for r in rows)
        assert calls==['/api/v1/prices']
        assert all(r['change'] is None for r in rows)
        changes=await live.changes()
        assert next(r for r in changes if r['symbol']=='005930')['change'] is None
        assert all(r['change']==25 for r in changes if r['symbol']!='005930')
        with pytest.raises(HTTPException):
            await live.chart('005930')
    asyncio.run(run())


def test_pending_daily_changes_do_not_block_price_refresh(monkeypatch,live):
    async def run():
        started=asyncio.Event()
        release=asyncio.Event()
        async def fake(path,params):
            assert path=='/api/v1/prices'
            return [{'symbol':s,'lastPrice':'80000','currency':'KRW'} for s in BY_SYMBOL]
        async def candles(symbol):
            started.set()
            await release.wait()
            return []
        monkeypatch.setattr(live,'toss',fake)
        monkeypatch.setattr(live,'candles',candles)
        pending=asyncio.create_task(live.changes())
        try:
            await asyncio.wait_for(started.wait(),1)
            live.cache['quotes_until']=0
            rows=await asyncio.wait_for(live.quotes(),1)
            assert len(rows)==len(BY_SYMBOL) and all(r['price']==80000 for r in rows)
        finally:
            release.set()
            await pending
    asyncio.run(run())


def test_expired_chart_cache_keeps_same_day_previous_close(monkeypatch,live):
    stamp=datetime.now(KST)
    day=stamp.date().isoformat()
    yesterday=(stamp-timedelta(days=1)).date().isoformat()
    async def fake(path,params):
        if path=='/api/v1/prices':
            return [{'symbol':s,'lastPrice':'80000','currency':'KRW','timestamp':stamp.isoformat()} for s in BY_SYMBOL]
        raise HTTPException(502,'차트 요청 한도')
    monkeypatch.setattr(live,'toss',fake)
    for symbol in BY_SYMBOL:
        key='candles:'+symbol
        live.cache[key]=[{'date':yesterday,'value':64000,'volume':10}]
        live.cache[key+':day']=day
        live.cache[key+':until']=0
    async def run():
        assert all(q['change']==25 for q in await live.quotes())
        assert all(q['change']==25 for q in await live.changes())
        for symbol in BY_SYMBOL: live.cache['candles:'+symbol+':day']=yesterday
        live.cache['quotes_until']=0
        assert all(q['change'] is None for q in await live.quotes())
    asyncio.run(run())


def test_holiday_calendar_and_cache(monkeypatch,live):
    calls=[]
    async def fake(path,params):
        calls.append(path)
        return {'today':{'date':datetime.now(KST).date().isoformat(),'integrated':None}}
    monkeypatch.setattr(live,'toss',fake)
    async def run():
        assert not await live.trading_open()
        assert not await live.trading_open()
        with pytest.raises(HTTPException) as error:
            await live.check_trading_day('005930',{'quote_at':datetime.now(KST).isoformat()})
        assert error.value.status_code==400
    asyncio.run(run())
    assert calls==['/api/v1/market-calendar/KR']

def test_delayed_open_uses_provider_calendar(monkeypatch,live):
    now=datetime.now(KST)
    async def fake(path,params):
        return {'today':{'date':now.date().isoformat(),'integrated':{'regularMarket':{'startTime':(now-timedelta(minutes=1)).isoformat(),'endTime':(now+timedelta(minutes=1)).isoformat()}}}}
    monkeypatch.setattr(live,'toss',fake)
    assert asyncio.run(live.trading_open())

@pytest.mark.parametrize('age,halted,status',[(0,False,200),(180,False,400),(0,True,400),(None,False,502)])
def test_order_checks_status_and_quote_freshness(monkeypatch,live,age,halted,status):
    async def open_now(): return True
    async def fake(path,params):
        assert path=='/api/v1/stocks' and params=={'symbols':'005930'}
        return [{'symbol':'005930','status':'ACTIVE','koreanMarketDetail':{'krxTradingSuspended':halted,'nxtTradingSuspended':halted,'nxtSupported':True}}]
    monkeypatch.setattr(live,'trading_open',open_now)
    monkeypatch.setattr(live,'toss',fake)
    quote={'quote_at':(datetime.now(KST)-timedelta(seconds=age)).isoformat() if age is not None else None}
    if status==200:
        asyncio.run(live.check_trading_day('005930',quote))
    else:
        with pytest.raises(HTTPException) as error: asyncio.run(live.check_trading_day('005930',quote))
        assert error.value.status_code==status

@pytest.mark.parametrize('value',['NaN','Infinity','-1','0','72000.5'])
def test_invalid_krw_prices_rejected(value):
    with pytest.raises(ValueError): Market.price(value)
