import asyncio
import httpx
from app.core.config import settings
from app.services.market import Market
from app.services.store import Store

def test_kis_token_and_price_contract(monkeypatch):
    monkeypatch.setattr(settings,'data_mode','auto')
    monkeypatch.setattr(settings,'kis_app_key','test-app-key')
    monkeypatch.setattr(settings,'kis_app_secret','test-secret')
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.path=='/oauth2/tokenP':
            return httpx.Response(200,json={'access_token':'test-token','expires_in':86400})
        assert request.headers['authorization']=='Bearer test-token'
        assert request.headers['tr_id']=='FHKST01010100'
        assert request.url.params['FID_COND_MRKT_DIV_CODE']=='J'
        return httpx.Response(200,json={'rt_cd':'0','output':{'stck_prpr':'80000','prdy_ctrt':'1.2','per':'10','pbr':'1.3','acml_vol':'123','temp_stop_yn':'N'}})
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(handler),**kwargs))
    rows=asyncio.run(Market().quotes())
    assert len(rows)==8 and all(r['source']=='kis' and r['price']==80000 for r in rows)
    assert sum(r.url.path=='/oauth2/tokenP' for r in requests)==1

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
