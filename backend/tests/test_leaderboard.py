import asyncio
import copy
import pytest
from fastapi import HTTPException
from app.core.config import settings
from app.services.store import Store,store
from app.services.game import create_account
from app.services.market import market
from app.services.leaderboard import Leaderboard,REFRESH_SECONDS


def configure(monkeypatch):
    monkeypatch.setattr(settings,'data_mode','demo')
    monkeypatch.setattr(settings,'auth_mode','local')
    monkeypatch.setattr(settings,'supabase_url','')
    async def quotes(): return []
    monkeypatch.setattr(market,'quotes',quotes)


def test_rankings_refresh_after_ten_minutes_without_mutating_accounts(monkeypatch):
    configure(monkeypatch)
    clock=[1000.0]
    monkeypatch.setattr('app.services.leaderboard.time.time',lambda:clock[0])
    account=create_account('easy','sample')
    records=[{'id':'local-user','nickname':'로컬투자자','data':account}]
    calls=[]
    async def accounts():
        calls.append(1)
        return records
    monkeypatch.setattr(store,'ranking_accounts',accounts)
    ranks=Leaderboard()
    async def run():
        original=copy.deepcopy(account)
        first=await ranks.get()
        assert len(first['items'])==1 and first['refresh_seconds']==600
        account['cash']+=1000000
        assert (await ranks.get())['items']==first['items']
        assert len(calls)==1
        clock[0]+=REFRESH_SECONDS+1
        updated=await ranks.get()
        assert updated['items'][0]['net_assets']>first['items'][0]['net_assets']
        assert len(calls)==2
        assert account['interest']==original['interest'] and account['accrued_at']==original['accrued_at']
    asyncio.run(run())


def test_shared_db_snapshot_is_used_and_private_fields_are_not_uploaded(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(settings,'supabase_url','https://example.supabase.co')
    monkeypatch.setattr(settings,'supabase_service_role_key','server-key')
    local=create_account('easy','sample')
    local['trades']=[{'private':'not-for-leaderboard'}]
    async def accounts():return [{'id':'local-user','nickname':'로컬투자자','data':local},{'id':'legacy','nickname':'이전모드','data':{'schema':2,'campaign':{}}}]
    calls=[]
    async def cloud(path,method='GET',payload=None,**kwargs):
        calls.append((path,method,payload))
        assert kwargs.get('admin') is True
        if method=='POST':
            assert path=='/rest/v1/rpc/sync_leaderboard'
            entry=payload['p_entries'][0]
            assert set(entry)=={'user_id','nickname','source','difficulty','net_assets','return_rate','completed','updated_at'}
            return None
        return [{'user_id':'shared-user','nickname':'공용투자자','source':'sample','difficulty':'hard','return_rate':12.5,'net_assets':11250000,'completed':2,'updated_at':'2026-11-18T00:00:00Z'}]
    monkeypatch.setattr(store,'ranking_accounts',accounts)
    monkeypatch.setattr(store,'cloud',cloud)
    ranks=Leaderboard()
    async def run():
        result=await ranks.get('hard')
        assert result['items'][0]['id']=='shared-user' and result['storage']=='supabase'
        assert result['excluded']==1
        ranks.until=0
        async def fail(): raise HTTPException(502,'DB unavailable')
        monkeypatch.setattr(store,'ranking_accounts',fail)
        stale=await ranks.get('hard')
        assert stale['stale'] and stale['items']==result['items']
    asyncio.run(run())
    assert len(calls)==2


@pytest.mark.parametrize('failure',[HTTPException(502,'DB failure'),ValueError('Invalid DB response')])
def test_periodic_job_keeps_running_after_a_db_failure(monkeypatch,failure):
    ranks=Leaderboard()
    monkeypatch.setattr('app.services.leaderboard.time.time',lambda:1000.0)
    calls=[]
    async def refresh():
        calls.append(1)
        if len(calls)==1:raise failure
        ranks.until=1600.0
    async def sleep(seconds):
        assert seconds==600
        if len(calls)==2:raise asyncio.CancelledError()
    monkeypatch.setattr(ranks,'refresh',refresh)
    monkeypatch.setattr(asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):asyncio.run(ranks.run())
    assert len(calls)==2


def test_shared_accounts_are_read_even_with_local_auth(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(settings,'supabase_url','https://example.supabase.co')
    monkeypatch.setattr(settings,'supabase_service_role_key','server-key')
    own=Store()
    async def local():return [{'id':'local-user','nickname':'로컬투자자','data':{}}]
    async def cloud(path,**kwargs):
        assert kwargs['admin'] and path.startswith('/rest/v1/accounts?')
        return [{'user_id':'cloud-user','profiles':{'nickname':'공용투자자'},'data':{}}]
    monkeypatch.setattr(own,'accounts',local)
    monkeypatch.setattr(own,'cloud',cloud)
    assert len(asyncio.run(own.ranking_accounts()))==2


def test_empty_rankings_are_cached_for_ten_minutes(monkeypatch):
    configure(monkeypatch)
    clock=[1000.0]
    monkeypatch.setattr('app.services.leaderboard.time.time',lambda:clock[0])
    calls=[]
    async def accounts():
        calls.append(1)
        return []
    monkeypatch.setattr(store,'ranking_accounts',accounts)
    ranks=Leaderboard()
    async def run():
        assert (await ranks.get())['items']==[]
        assert (await ranks.get())['items']==[]
        assert len(calls)==1
        clock[0]+=REFRESH_SECONDS
        await ranks.get()
        assert len(calls)==2
    asyncio.run(run())


def test_periodic_job_wakes_when_the_current_snapshot_expires(monkeypatch):
    ranks=Leaderboard()
    ranks.until=1250.0
    monkeypatch.setattr('app.services.leaderboard.time.time',lambda:1000.0)
    async def refresh():pass
    async def sleep(seconds):
        assert seconds==250
        raise asyncio.CancelledError()
    monkeypatch.setattr(ranks,'refresh',refresh)
    monkeypatch.setattr(asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):asyncio.run(ranks.run())
