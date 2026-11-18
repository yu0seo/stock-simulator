import asyncio
import copy
import math
from app.core.config import settings
from app.services.catalog import STOCKS
from app.services.clustering import cluster_companies
from app.services.market import Market


def sample_companies():
    return [{**s,'financials':{**{k:s[k] for k in ('revenue','profit','equity','debt')},'year':'2025'}} for s in STOCKS]


def test_clusters_are_deterministic_and_exclude_unusable_financials():
    companies=sample_companies()
    companies[0]['financials']['equity']=0
    original=copy.deepcopy(companies)
    first=cluster_companies(companies)
    assert first==cluster_companies(companies)
    assert companies==original
    assert len(first['items'])==49 and first['excluded'][0]['symbol']==STOCKS[0]['symbol']
    assert len({p['cluster'] for p in first['items']})==3
    assert all(all(math.isfinite(x) for x in p['vector']) for p in first['items'])
    assert all(0<=p['cluster']<3 for p in first['items'])


def test_constant_financials_do_not_generate_nonfinite_coordinates():
    companies=sample_companies()[:5]
    for company in companies: company['financials']=companies[0]['financials']
    model=cluster_companies(companies)
    assert len(model['items'])==5
    assert all(p['vector']==[0,0,0] for p in model['items'])
    assert cluster_companies(companies[:3])['items']==[]


def test_map_reuses_cached_financial_model(monkeypatch):
    monkeypatch.setattr(settings,'opendart_api_key','')
    market=Market()
    calls=[]
    async def financials(symbol):
        calls.append(symbol)
        stock=next(s for s in STOCKS if s['symbol']==symbol)
        return {**{k:stock[k] for k in ('revenue','profit','equity','debt')},'year':'2025'}
    monkeypatch.setattr(market,'financials',financials)
    async def run():
        first=await market.clusters()
        assert len(first['items'])==50 and first['source']=='sample'
        assert await market.clusters()==first
    asyncio.run(run())
    assert len(calls)==50
