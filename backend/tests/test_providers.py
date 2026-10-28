import asyncio
import httpx
from urllib.parse import parse_qs
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.core.config import settings
from app.services.market import Market, KST
from app.services.store import Store

def test_toss_token_batch_prices_change_and_chart_contract(monkeypatch):
    monkeypatch.setattr(settings,'data_mode','auto')
    monkeypatch.setattr(settings,'toss_client_id','test-client-id')
    monkeypatch.setattr(settings,'toss_client_secret','test-secret')
    requests=[]
    now=datetime.now(KST)
    yesterday=(now-timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    old=yesterday-timedelta(days=1)
    def handler(request):
        requests.append(request)
        if request.url.path=='/oauth2/token':
            assert request.headers['content-type']=='application/x-www-form-urlencoded'
            assert parse_qs(request.content.decode())=={'grant_type':['client_credentials'],'client_id':['test-client-id'],'client_secret':['test-secret']}
            assert 'authorization' not in request.headers
            return httpx.Response(200,json={'access_token':'test-token','expires_in':86400})
        assert request.headers['authorization']=='Bearer test-token'
        assert 'tr_id' not in request.headers and 'X-Tossinvest-Account' not in request.headers
        assert request.method=='GET'
        if request.url.path=='/api/v1/prices':
            symbols=request.url.params['symbols'].split(',')
            assert len(symbols)==8
            return httpx.Response(200,json={'result':[{'symbol':s,'lastPrice':'80000','timestamp':now.isoformat(),'currency':'KRW'} for s in reversed(symbols)]})
        assert request.url.path=='/api/v1/candles'
        assert request.url.params['interval']=='1d' and request.url.params['adjusted']=='false'
        return httpx.Response(200,json={'result':{'candles':[{'timestamp':now.replace(hour=0).isoformat(),'closePrice':'79000','volume':'10','currency':'KRW'},{'timestamp':yesterday.isoformat(),'closePrice':'64000','volume':'10','currency':'KRW'},{'timestamp':old.isoformat(),'closePrice':'63000','volume':'10','currency':'KRW'}],'nextBefore':None}})
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(handler),**kwargs))
    m=Market()
    async def run():
        rows=await m.quotes()
        assert len(rows)==8 and all(r['source']=='toss' and r['price']==80000 for r in rows)
        assert all(r['change']==25 and r['per'] is None and r['pbr'] is None for r in rows)
        chart=await m.chart('005930')
        assert chart['source']=='toss' and chart['points'][0]['value']==63000
        assert chart['points'][-1]['value']==79000
        assert await m.quotes()==rows
    asyncio.run(run())
    assert sum(r.url.path=='/oauth2/token' for r in requests)==1
    assert sum(r.url.path=='/api/v1/prices' for r in requests)==1
    assert sum(r.url.path=='/api/v1/candles' for r in requests)==8

def test_dart_units_missing_metrics_and_request(monkeypatch):
    monkeypatch.setattr(settings,'opendart_api_key','test-key')
    monkeypatch.setattr(settings,'dart_business_year','2025')
    def handler(request):
        assert request.url.params['corp_code']=='00126380'
        assert request.url.params['fs_div']=='CFS'
        assert request.url.params['reprt_code']=='11011'
        return httpx.Response(200,json={'status':'000','list':[{'account_id':'ifrs-full_Revenue','account_nm':'매출액','thstrm_amount':'1,000,000,000,000'},{'account_id':'ifrs-full_Equity','account_nm':'자본총계','thstrm_amount':'500,000,000,000'},{'account_id':'ifrs-full_Liabilities','account_nm':'부채총계','thstrm_amount':'250,000,000,000'}]})
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(handler),**kwargs))
    result=asyncio.run(Market().financials('005930'))
    assert result['revenue']==1 and result['equity']==.5 and result['debt']==50
    assert result['profit'] is None and result['roe'] is None
    assert result['source']=='opendart'

def test_supabase_service_key_only_for_server_rpc(monkeypatch):
    monkeypatch.setattr(settings,'auth_mode','auto')
    monkeypatch.setattr(settings,'supabase_url','https://test.supabase.co')
    monkeypatch.setattr(settings,'supabase_anon_key','anon-key')
    monkeypatch.setattr(settings,'supabase_service_role_key','server-key')
    def handler(request):
        assert request.url.path=='/rest/v1/rpc/save_account'
        assert request.headers['apikey']=='server-key'
        assert request.headers['authorization']=='Bearer server-key'
        return httpx.Response(200,json=True)
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(handler),**kwargs))
    asyncio.run(Store().save('00000000-0000-0000-0000-000000000001',{'cash':1000},0))
