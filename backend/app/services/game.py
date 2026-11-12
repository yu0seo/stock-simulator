"""Historical campaign. Wall time is used only during an active connection."""
import calendar
import copy
import hashlib
import json
import math
import time
import uuid
from datetime import date
from fastapi import HTTPException
from app.core.config import settings

PROCESS_ID = uuid.uuid4().hex
LEASE_SECONDS = 12


def rules():
    payments = settings.stage_payments
    if (len(payments) != 12 or any(type(x) is not int or x <= 0 for x in payments)
            or settings.initial_capital <= 0 or not math.isfinite(settings.stage_minutes) or settings.stage_minutes <= 0
            or not 2016 <= settings.game_year <= 2100):
        raise HTTPException(503, '게임 설정을 확인해주세요. 상환금은 양의 정수 12개가 필요해요.')
    return {'year': settings.game_year, 'initial': settings.initial_capital,
            'stage_seconds': settings.stage_minutes * 60, 'payments': list(payments),
            'version': 2, 'execution': 'daily-close-no-fees', 'calendar': '30-minutes-per-month'}


def create_account(dataset_id):
    r = rules()
    r['dataset_id'] = dataset_id
    key = rules_key(r)
    return {'schema': 2, 'id': uuid.uuid4().hex, 'rules': r, 'rules_id': key,
            'stage': 1, 'elapsed': 0.0, 'phase': 'strategy', 'last_tick': None,
            'process_id': PROCESS_ID, 'initial': r['initial'], 'cash': r['initial'],
            'positions': {}, 'trades': [], 'payments': [], 'strategies': {},
            'completed': [], 'started_at': time.time(), 'failure_reason': None,
            'debug_used': False, 'debug_events': []}


def rules_key(r):
    return hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest()[:20]


def jump_to_month_end(a, settle=False, now=None):
    if a['phase'] not in ('running', 'paused'):
        raise HTTPException(400, '먼저 스테이지를 시작해주세요. 진행·일시정지 상태에서 월말로 이동할 수 있어요.')
    days = calendar.monthrange(a['rules']['year'], a['stage'])[1]
    before = {'stage': a['stage'], 'date': game_date(a), 'elapsed': a['elapsed']}
    a['elapsed'] = a['rules']['stage_seconds'] if settle else max(a['elapsed'], a['rules']['stage_seconds'] * (days-1)/days + 0.001)
    a['phase'] = 'settlement' if settle else 'running'
    a['last_tick'] = None if settle else (time.time() if now is None else now)
    a['process_id'] = PROCESS_ID
    a['debug_used'] = True
    a.setdefault('debug_events', []).append({**before, 'target': 'settlement' if settle else 'last_day', 'at': time.time()})


def game_date(a):
    days = calendar.monthrange(a['rules']['year'], a['stage'])[1]
    day = min(days, 1 + int(a['elapsed'] / a['rules']['stage_seconds'] * days))
    return date(a['rules']['year'], a['stage'], day).isoformat()


def tick(a, now=None):
    now = time.time() if now is None else now
    if a['phase'] != 'running':
        return
    gap = max(0, now - (a['last_tick'] if a['last_tick'] is not None else now))
    if a.get('process_id') != PROCESS_ID or gap > LEASE_SECONDS:
        a['phase'] = 'paused'
        a['last_tick'] = None
        return
    a['elapsed'] = min(a['rules']['stage_seconds'], a['elapsed'] + gap)
    a['last_tick'] = now
    if a['elapsed'] >= a['rules']['stage_seconds']:
        a['phase'] = 'settlement'
        a['last_tick'] = None


def resume(a, now=None):
    if a['phase'] == 'running':
        return  # Another browser tab may already have resumed the same saved game.
    if a['phase'] not in ('ready', 'strategy', 'paused'):
        raise HTTPException(400, '현재 단계에서는 시작할 수 없어요.')
    a.update(phase='running', last_tick=time.time() if now is None else now, process_id=PROCESS_ID)


def trade(a, symbol, side, quantity, quote):
    settlement = a['phase'] == 'settlement'
    if a['phase'] != 'running' and not (settlement and side == 'sell'):
        raise HTTPException(400, '진행 중에만 거래할 수 있어요. 월말 정산에서는 매도만 가능해요.')
    if not quote['tradable'] and not settlement:
        raise HTTPException(400, '게임 속 휴장일 또는 거래정지일이에요. 다음 거래일까지 기다려주세요.')
    if settlement and not quote.get('liquidatable', True):
        raise HTTPException(400, '월말 기준 거래정지된 종목은 정산 매도를 할 수 없어요.')
    price = quote['price']
    amount = quantity * price
    p = a['positions'].get(symbol, {'quantity': 0, 'average': 0})
    if side == 'buy':
        if amount > a['cash']:
            raise HTTPException(400, '주문 가능한 현금이 부족해요.')
        p['average'] = (p['quantity'] * p['average'] + amount) / (p['quantity'] + quantity)
        p['quantity'] += quantity
        a['cash'] -= amount
    else:
        if quantity > p['quantity']:
            raise HTTPException(400, '보유 수량보다 많이 팔 수 없어요.')
        p['quantity'] -= quantity
        a['cash'] += amount
    if p['quantity']:
        a['positions'][symbol] = p
    else:
        a['positions'].pop(symbol, None)
    a['trades'].insert(0, {'id': uuid.uuid4().hex, 'symbol': symbol, 'side': side,
                          'quantity': quantity, 'price': price, 'amount': amount,
                          'created_at': time.time(), 'date': game_date(a), 'stage': a['stage'],
                          'settlement': settlement, 'price_date': quote['price_date']})


def assess(a, quotes):
    if a['phase'] != 'settlement':
        return
    liquid = a['cash'] + sum(p['quantity'] * quotes[s]['price'] for s, p in a['positions'].items()
                            if quotes[s].get('liquidatable', True))
    if liquid < a['rules']['payments'][a['stage'] - 1]:
        a['phase'] = 'bankrupt'
        a['failure_reason'] = '보유 주식을 매도해도 이번 달 상환금을 마련할 수 없어요.'


def pay(a):
    if a['phase'] != 'settlement':
        raise HTTPException(400, '스테이지 종료 후 상환할 수 있어요.')
    amount = a['rules']['payments'][a['stage'] - 1]
    if a['cash'] < amount:
        raise HTTPException(400, '보유 주식을 매도해 상환할 현금을 마련해주세요.')
    a['cash'] -= amount
    a['payments'].append({'stage': a['stage'], 'amount': amount, 'date': game_date(a), 'paid_at': time.time()})
    if a['stage'] == 12:
        a['phase'] = 'completed'
    else:
        a['stage'] += 1
        a['elapsed'] = 0.0
        a['phase'] = 'strategy' if a['stage'] in (4, 7, 10) else 'ready'
    a['last_tick'] = None


def summary(a, quotes):
    result = {k: copy.deepcopy(v) for k, v in a.items() if k not in ('last_tick', 'process_id')}
    result['date'] = game_date(a)
    result['positions'] = []
    for symbol, p in a['positions'].items():
        q = quotes[symbol]
        result['positions'].append({**p, 'symbol': symbol, 'name': q['name'], 'color': q['color'],
                                   'price': q['price'], 'value': p['quantity'] * q['price'],
                                   'profit': (q['price'] - p['average']) * p['quantity']})
    assets = sum(p['value'] for p in result['positions'])
    paid = sum(p['amount'] for p in a['payments'])
    total = a['cash'] + assets
    profit = total + paid - a['initial']
    result.update(stock_value=assets, net_assets=total, paid=paid, profit=round(profit),
                  return_rate=round(profit / a['initial'] * 100, 4),
                  current_payment=a['rules']['payments'][a['stage'] - 1],
                  cleared=len(a['payments']), remaining_seconds=max(0, a['rules']['stage_seconds'] - a['elapsed']))
    return result
