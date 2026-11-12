import asyncio
import httpx
from app.core.config import settings
from app.services.store import Store

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
