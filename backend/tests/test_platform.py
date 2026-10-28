import asyncio
import copy
import time
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services.game import create_account,accrue,summary,trade,repay
from app.services.market import market,Market
from app.services.store import store
from app.api.routes.platform import auth_attempts

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'database_path',str(tmp_path/'test.sqlite3'))
    monkeypatch.setattr(settings,'auth_mode','local')
    monkeypatch.setattr(settings,'data_mode','demo')
    monkeypatch.setattr(settings,'opendart_api_key','')
    market.cache.clear()
    auth_attempts.clear()
    with TestClient(app) as c: yield c

def signup(c,email='learner@example.com',nickname='새싹투자자'):
    r=c.post('/api/auth/signup',json={'email':email,'nickname':nickname,'password':'study-test-password'})
    assert r.status_code==200,r.text
    return r.json()['user']

def start(c):
    signup(c)
    assert c.post('/api/game/start',json={'difficulty':'easy'}).status_code==200

def test_signup_unique_nickname_password_and_logout(client):
    u=signup(client)
    assert client.get('/api/auth/me').json()['id']==u['id']
    assert 'HttpOnly' in client.post('/api/auth/login',json={'email':'learner@example.com','password':'study-test-password'}).headers['set-cookie']
    r=client.post('/api/auth/signup',json={'email':'other@example.com','nickname':'새싹투자자','password':'another-password'})
    assert r.status_code==409
    with store.connect() as db:
        assert 'study-test-password' not in db.execute('select password from users').fetchone()[0]
    assert client.post('/api/auth/logout',json={}).status_code==200
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={'email':'learner@example.com','password':'wrong-password'}).status_code==401

def test_trade_and_repay_end_to_end(client):
    start(client)
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':2,'price':1}).status_code==200
    a=client.get('/api/portfolio').json()['account']
    assert a['cash']==20000000-72800*2
    assert a['positions'][0]['quantity']==2
    assert client.post('/api/trades',json={'symbol':'005930','side':'sell','quantity':3}).status_code==400
    assert client.post('/api/trades',json={'symbol':'005930','side':'sell','quantity':1}).status_code==200
    assert client.post('/api/loans/repay',json={'amount':1000000}).status_code==200
    a=client.get('/api/portfolio').json()['account']
    assert 9000000<=a['principal']<9000001
    assert a['positions'][0]['quantity']==1
    assert len(a['trades'])==2

def test_invalid_orders_and_unauthenticated(client):
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':1}).status_code==401
    start(client)
    for q in [0,-1,1.5,True]:
        assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':q}).status_code==422
    assert client.post('/api/trades',json={'symbol':'000000','side':'buy','quantity':1}).status_code==404
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':1000000}).status_code==400
    assert client.post('/api/loans/repay',json={'amount':999999999}).status_code==400

def test_quiz_reward_once_and_ranking_excludes_reward(client):
    start(client)
    lessons=client.get('/api/lessons').json()
    assert 'answer' not in lessons[0] and 'explanation' not in lessons[0]
    assert client.post('/api/lessons/per/answer',json={'answer':0}).json()['reward']==0
    assert client.post('/api/lessons/per/answer',json={'answer':1}).json()['reward']==50000
    assert client.post('/api/lessons/per/answer',json={'answer':1}).json()['reward']==0
    a=client.get('/api/portfolio').json()['account']
    assert a['rewards']==50000 and a['completed']==['per']
    ranks=client.get('/api/ranking').json()['items']
    assert ranks[0]['nickname']=='새싹투자자'
    assert abs(ranks[0]['return_rate'])<0.001
    assert client.get('/api/ranking?difficulty=hard').json()['items']==[]

def test_isolation_and_reset(client):
    first=signup(client)
    client.post('/api/game/start',json={'difficulty':'easy'})
    client.post('/api/auth/logout',json={})
    signup(client,'second@example.com','두번째투자자')
    assert client.get('/api/portfolio').json()['account'] is None
    client.post('/api/game/start',json={'difficulty':'hard'})
    assert client.get('/api/portfolio').json()['account']['principal']==50000000
    assert client.post('/api/game/start',json={'difficulty':'easy'}).status_code==409
    assert client.post('/api/game/restart',json={'difficulty':'normal'}).status_code==200
    assert client.get('/api/portfolio').json()['account']['principal']==30000000
    assert len(client.get('/api/ranking').json()['items'])==2

def test_concurrent_write_rejected(client):
    u=signup(client)
    a=create_account('easy','sample')
    asyncio.run(store.save(u['id'],a,0))
    a,v=asyncio.run(store.account(u['id']))
    asyncio.run(store.save(u['id'],a,v))
    with pytest.raises(HTTPException) as e: asyncio.run(store.save(u['id'],a,v))
    assert e.value.status_code==409

def test_real_elapsed_interest():
    a=create_account('hard','sample')
    start=a['accrued_at']
    accrue(a,start+365*86400)
    assert a['interest']==9000000
    a['cash']=20000000
    repay(a,10000000)
    assert a['interest']==0 and a['principal']==49000000
    accrue(a,start+2*365*86400)
    assert a['interest']==8820000

def test_market_mode_change_protected(client,monkeypatch):
    start(client)
    monkeypatch.setattr(settings,'data_mode','auto')
    monkeypatch.setattr(settings,'toss_client_id','test')
    monkeypatch.setattr(settings,'toss_client_secret','test')
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':1}).status_code==409

def test_data_and_cluster_contracts(client):
    stocks=client.get('/api/market').json()['stocks']
    assert len(stocks)==8 and all(s['source']=='sample' for s in stocks)
    chart=client.get('/api/market/005930/chart').json()
    assert chart['points'][-1]['value']==stocks[0]['price']
    f=client.get('/api/companies/005930/financials').json()
    assert f['source']=='sample'
    similar=client.get('/api/companies/005930/similar').json()
    assert len(similar['items'])==3 and '005930' not in [x['symbol'] for x in similar['items']]

def test_csrf_origin(client):
    assert client.post('/api/auth/logout',json={},headers={'origin':'https://unknown.example'}).status_code==403

def test_live_provider_failure_never_uses_sample(client,monkeypatch):
    monkeypatch.setattr(settings,'data_mode','auto')
    monkeypatch.setattr(settings,'toss_client_id','fake')
    monkeypatch.setattr(settings,'toss_client_secret','fake')
    async def fail(*args,**kwargs): raise HTTPException(502,'provider failure')
    monkeypatch.setattr(market,'toss',fail)
    assert client.get('/api/market').status_code==502

def test_expired_game_rejects_trade_and_rewards(client):
    start(client)
    uid=client.get('/api/auth/me').json()['id']
    a,v=asyncio.run(store.account(uid))
    a['ends_at']=time.time()-1
    asyncio.run(store.save(uid,a,v))
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':1}).status_code==400
    assert client.post('/api/lessons/per/answer',json={'answer':1}).status_code==400
