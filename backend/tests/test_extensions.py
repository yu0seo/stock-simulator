import asyncio
import copy
import hashlib
import json
import math
from datetime import date
import pytest
from app.core.config import settings
from app.services.catalog import BY_SYMBOL
from app.services.clusters import build_clusters, distance, extract, kmeans, pca
from app.services.market import market
from app.services.store import store
from test_platform import client, dataset, edit, start


def fact_report(i=0, receipt='20231114000001', published='2023-11-14'):
    asset=1e12*(1+i%5)
    leverage=[.15,.4,.7][i%3]
    profit=[-.02,.03,.08][i%3]*asset
    return {'title':'2023 3분기','receipt':receipt,'published_at':published,'period_end':'2023-09-30',
            'report_code':'11014','statement':'CFS','rows':[
                {'account_id':account,'sj_div':statement,'thstrm_amount':str(value),'rcept_no':receipt,'currency':'KRW'}
                for account,statement,value in [('ifrs-full_Assets','BS',asset),('ifrs-full_Liabilities','BS',asset*leverage),('ifrs-full_ProfitLoss','IS',profit)]]}


def seed_financials():
    ds=market.dataset(2024)
    for i,s in enumerate(BY_SYMBOL):
        ds['financials'][s]=[fact_report(i)]


def test_fifty_stocks_are_in_quotes_and_cluster_candidates(client):
    assert len(BY_SYMBOL)==50
    assert len(client.get('/api/market').json()['stocks'])==50
    seed_financials()
    data=client.get('/api/market/clusters?symbol=005930').json()
    assert data['total']==50 and len(data['nodes'])==50 and len(data['clusters'])==5
    assert len(data['recommendations'])==6
    assert all(n['symbol']!='005930' for n in data['recommendations'])
    assert [n['distance'] for n in data['recommendations']]==sorted(n['distance'] for n in data['recommendations'])
    assert all(n['published_at']<='2024-01-01' for n in data['nodes'])


def test_paused_server_blocks_all_analysis_and_other_tabs(client):
    start(client)
    client.post('/api/game/resume',json={})
    assert client.post('/api/game/pause',json={}).status_code==200
    for path in ['/market','/market/clusters','/market/005930/chart','/companies/005930/financials','/portfolio','/lessons','/ranking','/game/history']:
        assert client.get('/api'+path).status_code==403,path
    s=client.get('/api/game/state').json()
    assert s['stocks']==[] and s['account']['phase']=='paused'
    assert client.post('/api/lessons/per/answer',json={'answer':1}).status_code==403
    assert client.post('/api/game/resume',json={}).status_code==200
    assert client.get('/api/market').status_code==200


def test_nonquarter_ready_and_settlement_do_not_offer_free_research(client):
    uid=start(client)
    for phase in ['ready','settlement']:
        edit(uid,phase=phase)
        for path in ['/market','/market/clusters','/companies/005930/financials','/market/005930/chart']:
            assert client.get('/api'+path).status_code==403


def test_debug_flag_auth_prices_and_ranking_exclusion(client,monkeypatch,dataset):
    monkeypatch.setattr(settings,'enable_debug_tools',False)
    assert client.post('/api/game/debug/last-day',json={}).status_code==401
    uid=start(client)
    assert client.post('/api/game/debug/last-day',json={}).status_code==404
    monkeypatch.setattr(settings,'enable_debug_tools',True)
    assert client.post('/api/game/debug/last-day',json={}).status_code==400
    # Distinct last-day price verifies the jump actually changes the server's quote date.
    p=dataset/'005930.csv'
    p.write_bytes(p.read_bytes().replace(b'2024-01-31,100000,100000,100000,100000,10',b'2024-01-31,110000,110000,110000,110000,10'))
    manifest=json.loads((dataset/'manifest.json').read_text())
    manifest['files']['005930.csv']=hashlib.sha256(p.read_bytes()).hexdigest()
    (dataset/'manifest.json').write_text(json.dumps(manifest))
    market.cache.clear()
    doc,v=asyncio.run(store.account(uid))
    doc['campaign']['rules']['dataset_id']=market.dataset(2024)['id']
    asyncio.run(store.save(uid,doc,v))
    edit(uid,phase='paused',elapsed=100)
    client.post('/api/game/resume',json={})
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':2}).status_code==200
    assert client.post('/api/game/debug/last-day',json={'settle':False}).status_code==200
    s=client.get('/api/game/state').json()
    assert s['date']=='2024-01-31' and s['account']['phase']=='running'
    assert s['account']['positions'][0]['price']==110000 and s['account']['profit']==20000
    assert s['account']['cash']==9800000 and s['account']['debug_used']
    assert client.get('/api/ranking').json()['items']==[]
    assert client.post('/api/game/debug/last-day',json={'settle':True}).status_code==200
    assert client.post('/api/game/pay',json={}).status_code==200
    a=client.get('/api/game/state').json()['account']
    assert a['stage']==2 and a['cash']==9300000 and a['payments'][0]['amount']==500000


def test_debug_twelve_stage_repayments_with_no_cash_grant(client,monkeypatch):
    monkeypatch.setattr(settings,'enable_debug_tools',True)
    uid=start(client)
    edit(uid,cash=20000000) # Test setup, never granted by the debug endpoint.
    for month in range(1,13):
        assert client.post('/api/game/resume',json={}).status_code==200
        assert client.post('/api/game/debug/last-day',json={'settle':True}).status_code==200
        s=client.get('/api/game/state').json()['account']
        assert s['stage']==month and s['phase']=='settlement'
        assert client.post('/api/game/pay',json={}).status_code==200
    a=client.get('/api/game/state').json()['account']
    assert a['phase']=='completed' and a['cash']==7400000 and len(a['payments'])==12
    assert client.post('/api/game/pay',json={}).status_code==400


def test_additive_dataset_upgrade_preserves_account_and_is_saved(client):
    uid=start(client)
    a,v=asyncio.run(store.account(uid))
    a['campaign']['cash']=1234567
    a['campaign']['rules']['dataset_id']='old-eight-stock-snapshot'
    asyncio.run(store.save(uid,a,v))
    ds=market.dataset(2024)
    ds['manifest']['compatible_predecessors']=['old-eight-stock-snapshot']
    current=client.get('/api/game/state').json()['account']
    assert current['cash']==1234567 and current['rules']['dataset_id']==ds['id']
    doc,_=asyncio.run(store.account(uid))
    assert len(doc['campaign']['dataset_upgrades'])==1
    client.get('/api/game/state')
    doc,_=asyncio.run(store.account(uid))
    assert len(doc['campaign']['dataset_upgrades'])==1


def test_future_financials_and_missing_data_cannot_enter_clusters(dataset):
    seed_financials()
    baseline=build_clusters(market,'2024-01-01',2024,'005930')
    market.dataset(2024)['financials']['005930'].append(fact_report(8,'20260101000001','2026-01-01'))
    assert build_clusters(market,'2024-01-01',2024,'005930')==baseline
    market.dataset(2024)['financials']['005930']=[]
    result=build_clusters(market,'2024-01-01',2024,'005930')
    assert len(result['nodes'])==49 and result['recommendations']==[]
    assert result['excluded'][0]['symbol']=='005930'


def test_pca_projection_and_deterministic_kmeans():
    vectors=[[-1,0,0],[1,0,0],[0,1,0],[0,-1,0]]
    coords,explained=pca(vectors)
    assert sum(explained)==pytest.approx(1)
    assert distance(coords[0],coords[1])==pytest.approx(distance(vectors[0],vectors[1]))
    a=kmeans(vectors)
    assert a==kmeans(vectors)
    labels,_=kmeans([[0,0,0]]*50)
    assert len(set(labels))==1
    coords,explained=pca([[0,0,0]]*50)
    assert all(math.isfinite(x) for c in coords for x in c)
    correlated=[[-2,-4,1],[-1,-2,-1],[1,2,-1],[2,4,1]]
    projection,explained=pca(correlated)
    assert sum(explained)==pytest.approx(1)
    for i in range(4):
        for j in range(4):
            assert distance(projection[i],projection[j])==pytest.approx(distance(correlated[i],correlated[j]))


def test_nonstandard_profit_label_and_cumulative_annualization():
    report=fact_report()
    row=report['rows'][-1]
    row.update(account_id='-표준계정코드 미사용-',account_nm='당분기순이익(손실)',thstrm_add_amount='9000000000')
    assert extract(report)['raw'][2]==pytest.approx(1.2)
    report['rows'].append({**row,'thstrm_amount':'1','thstrm_add_amount':'1'})
    assert extract(report) is None
