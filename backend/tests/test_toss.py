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
    assert all(r['change']==25 for r in asyncio.run(live.quotes()))

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
