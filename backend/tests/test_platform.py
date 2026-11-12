import asyncio
import copy
import hashlib
import json
from datetime import date, timedelta
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services import game
from app.services.catalog import BY_SYMBOL
from app.services.market import market, HistoricalMarket
from app.services.store import store
from app.api.routes.platform import auth_attempts


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'historical_data_path', str(tmp_path/'history'))
    monkeypatch.setattr(settings, 'game_year', 2024)
    monkeypatch.setattr(settings, 'initial_capital', 10000000)
    monkeypatch.setattr(settings, 'stage_minutes', 30)
    monkeypatch.setattr(settings, 'stage_payments', [500000+i*100000 for i in range(12)])
    root = tmp_path/'history'/'2024'
    root.mkdir(parents=True)
    days = []
    d = date(2023, 9, 1)
    while d <= date(2024, 12, 31):
        if d.weekday() < 5 and d.isoformat() != '2024-01-01':
            days.append(d.isoformat())
        d += timedelta(days=1)
    files = {}
    for symbol in BY_SYMBOL:
        files[symbol+'.csv'] = ('Date,Open,High,Low,Close,Volume\n' +
            '\n'.join(f'{d},100000,100000,100000,100000,10' for d in days)).encode()
    files['calendar.json'] = json.dumps(days).encode()
    reports = [dict(title='2023 3분기',receipt='20231114000001',published_at='2023-11-14',period_end='2023-09-30',rows=[dict(rcept_no='20231114000001')]),
               dict(title='2023 연간',receipt='20240320000001',published_at='2024-03-20',period_end='2023-12-31',rows=[dict(rcept_no='20240320000001')]),
               dict(title='2024 1분기',receipt='20240515000001',published_at='2024-05-15',period_end='2024-03-31',rows=[dict(rcept_no='20240515000001')]),
               dict(title='미래 정정',receipt='20260101000001',published_at='2026-01-01',period_end='2023-09-30',rows=[dict(rcept_no='20260101000001')])]
    files['financials.json'] = json.dumps({s:reports for s in BY_SYMBOL}).encode()
    for name, raw in files.items():
        (root/name).write_bytes(raw)
    (root/'manifest.json').write_text(json.dumps({'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}}))
    market.cache.clear()
    yield root
    market.cache.clear()


@pytest.fixture
def client(tmp_path, monkeypatch, dataset):
    monkeypatch.setattr(settings,'database_path',str(tmp_path/'test.sqlite3'))
    monkeypatch.setattr(settings,'auth_mode','local')
    auth_attempts.clear()
    with TestClient(app) as c:
        yield c


def signup(c, email='learner@example.com', nickname='새싹투자자'):
    r=c.post('/api/auth/signup',json={'email':email,'nickname':nickname,'password':'study-test-password'})
    assert r.status_code==200,r.text
    return r.json()['user']['id']


def start(c):
    uid=signup(c)
    assert c.post('/api/game/start',json={}).status_code==200
    return uid


def edit(uid, **values):
    doc,v=asyncio.run(store.account(uid))
    doc['campaign'].update(values)
    asyncio.run(store.save(uid,doc,v))


def test_auth_uniqueness_password_hash_and_isolation(client):
    uid=start(client)
    assert client.get('/api/auth/me').json()['id']==uid
    r=client.post('/api/auth/login',json={'email':'learner@example.com','password':'study-test-password'})
    assert 'HttpOnly' in r.headers['set-cookie']
    assert client.post('/api/auth/signup',json={'email':'other@example.com','nickname':'새싹투자자','password':'another-password'}).status_code==409
    with store.connect() as db:
        assert 'study-test-password' not in db.execute('select password from users').fetchone()[0]
    client.post('/api/auth/logout',json={})
    assert client.get('/api/game/history').status_code==401
    signup(client,'second@example.com','두번째계정')
    assert client.get('/api/game/state').json()['account'] is None


def test_snapshot_and_strategy_no_future_leak(client):
    start(client)
    s=client.get('/api/game/state').json()
    assert s['account']['phase']=='strategy' and s['account']['cash']==10000000
    assert s['date']=='2024-01-01'
    assert 'last_tick' not in s['account'] and not any(x['tradable'] for x in s['stocks'])
    points=client.get('/api/market/005930/chart?date=2024-12-31').json()['points']
    assert all(x['date']<='2024-01-01' for x in points)
    f=client.get('/api/companies/005930/financials').json()
    assert f['report']['title']=='2023 3분기'
    assert client.get('/api/companies/005930/financials?receipt=20240515000001').status_code==404
    assert client.post('/api/game/strategy',json={'notes':'현금 확보','watchlist':['005930']}).status_code==200
    assert client.get('/api/game/state').json()['account']['strategies']['1']['notes']=='현금 확보'


def test_holidays_invalid_orders_and_authoritative_price(client):
    uid=start(client)
    assert client.post('/api/game/resume',json={}).status_code==200
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':1}).status_code==400
    edit(uid, elapsed=100, phase='paused')  # Jan 2, a trading day
    client.post('/api/game/resume',json={})
    for q in [0,-1,1.5,True]:
        assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':q}).status_code==422
    assert client.post('/api/trades',json={'symbol':'000000','side':'buy','quantity':1}).status_code==404
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':2,'price':1}).status_code==200
    a=client.get('/api/game/state').json()['account']
    assert a['cash']==9800000 and a['positions'][0]['average']==100000
    assert client.post('/api/trades',json={'symbol':'005930','side':'sell','quantity':3}).status_code==400
    assert client.post('/api/game/pause',json={}).status_code==200
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':1}).status_code==400


def test_settlement_sale_opportunity_and_single_payment(client):
    uid=start(client)
    edit(uid,stage=3,elapsed=1800,phase='settlement',cash=100000,positions={'005930':{'quantity':10,'average':100000}})
    a=client.get('/api/game/state').json()['account']
    assert a['date']=='2024-03-31' and a['phase']=='settlement' # Sunday
    assert client.post('/api/game/pay',json={}).status_code==400
    assert client.post('/api/trades',json={'symbol':'005930','side':'buy','quantity':1}).status_code==400
    assert client.post('/api/trades',json={'symbol':'005930','side':'sell','quantity':6}).status_code==200
    assert client.post('/api/game/pay',json={}).status_code==200
    a=client.get('/api/game/state').json()['account']
    assert a['stage']==4 and a['phase']=='strategy' and a['cash']==0
    assert a['payments'][0]['amount']==700000 and a['positions'][0]['quantity']==4
    assert client.post('/api/game/pay',json={}).status_code==400


def test_insolvent_at_month_end_is_saved(client):
    uid=start(client)
    edit(uid,phase='settlement',elapsed=1800,cash=499999)
    assert client.get('/api/game/state').json()['account']['phase']=='bankrupt'
    doc,_=asyncio.run(store.account(uid))
    assert doc['campaign']['phase']=='bankrupt'
    assert client.post('/api/game/resume',json={}).status_code==400


def test_quiz_no_money_and_rank_rules_separated(client,monkeypatch):
    start(client)
    before=client.get('/api/game/state').json()['account']['cash']
    assert 'answer' not in client.get('/api/lessons').json()[0]
    for _ in range(2):
        assert client.post('/api/lessons/per/answer',json={'answer':1}).json()['reward']==0
    a=client.get('/api/game/state').json()['account']
    assert a['cash']==before and a['completed']==['per']
    assert len(client.get('/api/ranking').json()['items'])==1
    monkeypatch.setattr(settings,'stage_payments',[1]*12)
    assert client.get('/api/ranking').json()['items']==[]
    assert client.get('/api/game/state').json()['account']['rules']['payments'][0]==500000


def test_legacy_and_restarts_preserve_owned_history(client):
    uid=signup(client)
    legacy={'difficulty':'easy','cash':888,'positions':{'005930':{'quantity':3,'average':70000}},'trades':[{'id':'old'}]}
    asyncio.run(store.save(uid,copy.deepcopy(legacy),0))
    assert client.get('/api/game/state').json()['legacy_saved']
    assert client.post('/api/game/start',json={}).status_code==200
    assert client.post('/api/game/start',json={}).status_code==409
    assert client.post('/api/game/restart',json={}).status_code==200
    history=client.get('/api/game/history').json()['items']
    assert len(history)==2 and history[0]==legacy and history[1]['schema']==2


def test_cas_and_csrf(client):
    uid=start(client)
    data,v=asyncio.run(store.account(uid))
    asyncio.run(store.save(uid,data,v))
    with pytest.raises(HTTPException) as e:
        asyncio.run(store.save(uid,data,v))
    assert e.value.status_code==409
    assert client.post('/api/game/pause',json={},headers={'origin':'https://unknown.example'}).status_code==403


def test_exact_month_boundaries_leap_year_and_twelve_payments(dataset):
    a=game.create_account(market.dataset(2024)['id'])
    a['cash']=20000000
    for month in range(1,13):
        assert a['stage']==month and a['phase']==('strategy' if month in (1,4,7,10) else 'ready')
        game.resume(a,now=0)
        for second in range(10,1801,10):
            game.tick(a,now=second)
        assert a['phase']=='settlement' and game.game_date(a)==f'2024-{month:02d}-{[31,29,31,30,31,30,31,31,30,31,30,31][month-1]}'
        game.pay(a)
    assert a['phase']=='completed' and len(a['payments'])==12
    assert a['cash']==20000000-12600000
    with pytest.raises(HTTPException):
        game.pay(a)


def test_disconnect_pause_and_process_restart_never_consume_offline_days(dataset):
    a=game.create_account('test')
    game.resume(a,now=100)
    game.tick(a,now=104)
    assert a['elapsed']==4
    game.tick(a,now=86400)
    assert a['elapsed']==4 and a['phase']=='paused'
    game.resume(a,now=86400)
    a['process_id']='previous-server'
    game.tick(a,now=86404)
    assert a['elapsed']==4 and a['phase']=='paused'


def test_financial_receipt_dates_corrections_and_hash_validation(dataset):
    assert market.financials('005930','2024-03-19',2024)['report']['title']=='2023 3분기'
    assert market.financials('005930','2024-03-20',2024)['report']['title']=='2023 연간'
    assert market.financials('005930','2024-05-15',2024)['report']['title']=='2024 1분기'
    reports=market.dataset(2024)['financials']['005930']
    reports[0]['rows'][0]['rcept_no']='20260101000001'
    assert market.financials('005930','2024-01-01',2024)['report'] is None
    (dataset/'005930.csv').write_text('broken')
    with pytest.raises(HTTPException) as e:
        HistoricalMarket().dataset(2024)
    assert e.value.status_code==503


def test_missing_dataset_no_sample_substitution(client,monkeypatch,tmp_path):
    monkeypatch.setattr(settings,'historical_data_path',str(tmp_path/'missing'))
    assert not client.get('/api/config').json()['dataset']['ready']
    assert client.get('/api/market').status_code==503
