import copy
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from app.core.config import settings
from app.services.catalog import BY_SYMBOL, LESSONS
from app.services.market import market
from app.services.store import store
from app.services import game
from app.services.clusters import build_clusters

router = APIRouter()
auth_attempts = {}


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(default='투자자', min_length=2, max_length=12, pattern=r'^[가-힣a-zA-Z0-9_]+$')

    @field_validator('email')
    @classmethod
    def email_valid(cls, v):
        v = v.strip().lower()
        if '@' not in v or '.' not in v.split('@')[-1]:
            raise ValueError('올바른 이메일을 입력해주세요.')
        return v


class Order(BaseModel):
    symbol: str
    side: Literal['buy', 'sell']
    quantity: int = Field(gt=0, le=1000000, strict=True)


class Strategy(BaseModel):
    notes: str = Field(default='', max_length=3000)
    watchlist: list[str] = Field(default_factory=list, max_length=50)


class DebugJump(BaseModel):
    settle: bool = Field(default=False, strict=True)


class Answer(BaseModel):
    answer: int = Field(ge=0, le=2, strict=True)


async def current_user(request: Request, response: Response):
    return await store.user(request, response)


async def optional_user(request: Request, response: Response):
    return await store.user(request, response) if request.cookies.get('daega_session') else None


def throttle(request):
    key = request.client.host if request.client else 'local'
    now = time.time()
    values = [t for t in auth_attempts.get(key, []) if t > now - 60]
    if len(values) >= 15:
        raise HTTPException(429, '잠시 후 다시 시도해주세요.')
    auth_attempts[key] = values + [now]


def check_symbol(symbol):
    if symbol not in BY_SYMBOL:
        raise HTTPException(404, '지원하지 않는 종목이에요.')


def envelope(data):
    if data and data.get('schema') == 2 and 'campaign' in data:
        return data
    return {'schema': 2, 'campaign': None, 'archives': [data] if data else []}


async def context(user, advance=True):
    raw, version = await store.account(user['id']) if user else (None, 0)
    doc = envelope(raw)
    a = doc['campaign']
    if a:
        before = copy.deepcopy(a)
        ds = market.dataset(a['rules']['year'])
        if ds['id'] != a['rules']['dataset_id']:
            if a['rules']['dataset_id'] not in ds['manifest'].get('compatible_predecessors', []):
                raise HTTPException(409, '저장된 게임의 데이터 버전과 현재 파일이 달라요. 원래 데이터를 복원하거나 새 게임을 시작해주세요.')
            a.setdefault('dataset_upgrades', []).append({'from':a['rules']['dataset_id'],'to':ds['id'],'at':time.time()})
            a['rules']['dataset_id'] = ds['id']
            a['rules_id'] = game.rules_key(a['rules'])
        if advance:
            game.tick(a)
        day = game.game_date(a)
        quotes = market.quotes(day, a['rules']['year'])
        game.assess(a, quotes)
        if advance and a != before:
            await store.save(user['id'], doc, version)
            version += 1
    else:
        day = f'{settings.game_year}-01-01'
        quotes = market.quotes(day, settings.game_year)
    return doc, version, quotes, day


def require_campaign(doc):
    a = doc['campaign']
    if not a:
        raise HTTPException(400, '먼저 새 투자 여정을 만들어주세요.')
    return a


def research_allowed(doc):
    a = doc['campaign']
    return not a or a['phase'] in ('strategy','running','bankrupt','completed')


def check_research(doc):
    if not research_allowed(doc):
        raise HTTPException(403, '일시정지·다음 달 준비·월말 정산 중에는 기업 분석을 볼 수 없어요. 진행을 재개하거나 분기 전략 시간을 이용해주세요.')


async def check_paused_user(user):
    if user:
        raw, _ = await store.account(user['id'])
        a = envelope(raw)['campaign']
        if a and a['phase'] == 'paused':
            raise HTTPException(403, '일시정지 중에는 다른 탭을 이용할 수 없어요. 게임을 이어서 진행해주세요.')


def state(doc, quotes, day):
    a = doc['campaign']
    visible = quotes if research_allowed(doc) else ({s:q for s,q in quotes.items() if s in a['positions']} if a['phase']=='settlement' else {})
    return {'account': game.summary(a, quotes) if a else None, 'stocks': list(visible.values()),
            'date': day, 'legacy_saved': any(x.get('schema') != 2 for x in doc['archives']),
            'history_count': len(doc['archives'])}


@router.get('/config')
async def config():
    r = game.rules()
    return {'market_mode': 'historical', 'auth_mode': 'supabase' if settings.cloud_auth else 'local',
            'year': r['year'], 'initial_capital': r['initial'], 'stage_seconds': r['stage_seconds'],
            'payments': r['payments'], 'poll_seconds': 4, 'debug_tools':settings.enable_debug_tools,
            'stock_count':len(BY_SYMBOL), 'dataset': market.status(r['year'])}


@router.post('/auth/signup')
async def signup(body: Credentials, request: Request, response: Response):
    throttle(request)
    return await store.signup(body.email, body.password, body.nickname, response)


@router.post('/auth/login')
async def login(body: Credentials, request: Request, response: Response):
    throttle(request)
    return await store.login(body.email, body.password, response)


@router.get('/auth/me')
async def me(user=Depends(current_user)):
    return user


@router.post('/auth/logout')
async def logout(request: Request, response: Response):
    await store.logout(request, response)
    return {'ok': True}


@router.get('/game/state')
async def snapshot(user=Depends(optional_user)):
    doc, _, quotes, day = await context(user)
    return state(doc, quotes, day)


@router.get('/portfolio')
async def portfolio(user=Depends(current_user)):
    doc, _, quotes, day = await context(user)
    if doc['campaign'] and doc['campaign']['phase']=='paused':
        check_research(doc)
    return state(doc,quotes,day)


@router.post('/game/heartbeat')
async def heartbeat(user=Depends(current_user)):
    doc, _, quotes, day = await context(user)
    return state(doc, quotes, day)


@router.post('/game/start')
async def start(user=Depends(current_user)):
    raw, version = await store.account(user['id'])
    doc = envelope(raw)
    if doc['campaign']:
        raise HTTPException(409, '이미 진행 중인 여정이 있어요. 새 여정 메뉴를 이용해주세요.')
    doc['campaign'] = game.create_account(market.dataset(settings.game_year)['id'])
    await store.save(user['id'], doc, version)
    return {'ok': True}


@router.post('/game/restart')
async def restart(user=Depends(current_user)):
    raw, version = await store.account(user['id'])
    doc = envelope(raw)
    if doc['campaign']:
        old = doc['campaign']
        game.tick(old)
        if old['phase'] == 'running':
            old['phase'] = 'paused'
        doc['archives'].append(old)
    doc['campaign'] = game.create_account(market.dataset(settings.game_year)['id'])
    await store.save(user['id'], doc, version)
    return {'ok': True}


@router.post('/game/resume')
async def resume(body: Strategy, user=Depends(current_user)):
    doc, version, _, _ = await context(user)
    a = require_campaign(doc)
    if any(s not in BY_SYMBOL for s in body.watchlist):
        raise HTTPException(400, '관심 종목을 확인해주세요.')
    if a['phase'] == 'strategy':
        a['strategies'][str((a['stage'] - 1) // 3 + 1)] = body.model_dump()
    game.resume(a)
    await store.save(user['id'], doc, version)
    return {'ok': True}


@router.post('/game/pause')
async def pause(user=Depends(current_user)):
    doc, version, _, _ = await context(user)
    a = require_campaign(doc)
    if a['phase'] == 'running':
        a.update(phase='paused', last_tick=None)
        await store.save(user['id'], doc, version)
    return {'ok': True}


@router.post('/game/strategy')
async def strategy(body: Strategy, user=Depends(current_user)):
    raw, version = await store.account(user['id'])
    doc = envelope(raw)
    a = require_campaign(doc)
    if a['phase'] != 'strategy' or any(s not in BY_SYMBOL for s in body.watchlist):
        raise HTTPException(400, '분기 전략 수립 단계에서 올바른 종목을 선택해주세요.')
    a['strategies'][str((a['stage'] - 1) // 3 + 1)] = body.model_dump()
    await store.save(user['id'], doc, version)
    return {'ok': True}


@router.post('/game/pay')
async def pay(user=Depends(current_user)):
    doc, version, _, _ = await context(user)
    game.pay(require_campaign(doc))
    await store.save(user['id'], doc, version)
    return {'message': '상환을 완료했어요.'}


@router.get('/game/history')
async def history(user=Depends(current_user)):
    await check_paused_user(user)
    raw, _ = await store.account(user['id'])
    return {'items': envelope(raw)['archives']}


@router.post('/trades')
async def order(body: Order, user=Depends(current_user)):
    check_symbol(body.symbol)
    doc, version, quotes, _ = await context(user)
    a = require_campaign(doc)
    game.trade(a, body.symbol, body.side, body.quantity, quotes[body.symbol])
    game.assess(a, quotes)
    await store.save(user['id'], doc, version)
    return {'message': '모의 주문이 체결됐어요.', 'price': quotes[body.symbol]['price']}


@router.get('/market')
async def quotes(user=Depends(optional_user)):
    doc, _, prices, day = await context(user)
    check_research(doc)
    return {'stocks': list(prices.values()), 'source': 'historical', 'date': day}


@router.get('/market/{symbol}/chart')
async def chart(symbol: str, user=Depends(optional_user)):
    check_symbol(symbol)
    doc, _, _, day = await context(user)
    check_research(doc)
    a = doc['campaign']
    return market.chart(symbol, day, a['rules']['year'] if a else settings.game_year)


@router.get('/companies/{symbol}/financials')
async def financials(symbol: str, receipt: str | None = None, user=Depends(optional_user)):
    check_symbol(symbol)
    doc, _, _, day = await context(user)
    check_research(doc)
    a = doc['campaign']
    result = market.financials(symbol, day, a['rules']['year'] if a else settings.game_year)
    if receipt:
        visible = {r['receipt'] for r in result['available_reports']}
        if receipt not in visible:
            raise HTTPException(404, '현재 게임 날짜에 공개되지 않은 보고서예요.')
        result['report'] = next(r for r in market.dataset(a['rules']['year'] if a else settings.game_year)['financials'][symbol] if r['receipt'] == receipt)
    return result


@router.get('/lessons')
async def lessons(user=Depends(optional_user)):
    await check_paused_user(user)
    return [{**{k: v for k, v in x.items() if k not in ('answer', 'explanation')}, 'reward': 0} for x in LESSONS]


@router.post('/lessons/{lesson_id}/answer')
async def answer(lesson_id: str, body: Answer, user=Depends(current_user)):
    await check_paused_user(user)
    lesson = next((x for x in LESSONS if x['id'] == lesson_id), None)
    if not lesson:
        raise HTTPException(404, '학습 콘텐츠를 찾을 수 없어요.')
    raw, version = await store.account(user['id'])
    doc = envelope(raw)
    a = require_campaign(doc)
    correct = body.answer == lesson['answer']
    if correct and lesson_id not in a['completed']:
        a['completed'].append(lesson_id)
        await store.save(user['id'], doc, version)
    return {'correct': correct, 'reward': 0, 'explanation': lesson['explanation']}


@router.get('/ranking')
async def ranking(user=Depends(optional_user)):
    await check_paused_user(user)
    target = game.create_account(market.dataset(settings.game_year)['id'])['rules_id']
    rows = []
    for row in await store.accounts():
        a = envelope(row['data'])['campaign']
        if not a or a.get('debug_used') or a['rules_id'] != target:
            continue
        q = market.quotes(game.game_date(a), a['rules']['year'])
        s = game.summary(a, q)
        rows.append({'id': row['id'], 'nickname': row['nickname'], 'cleared': s['cleared'],
                     'net_assets': s['net_assets'], 'return_rate': s['return_rate'], 'phase': a['phase']})
    rows.sort(key=lambda r: (-r['cleared'], -r['net_assets'], r['nickname']))
    for i, row in enumerate(rows):
        row['rank'] = i + 1
    return {'items': rows[:100], 'rules_id': target}


@router.get('/market/clusters')
async def clusters(symbol: str | None = None, user=Depends(optional_user)):
    if symbol:
        check_symbol(symbol)
    doc, _, _, day = await context(user)
    check_research(doc)
    a = doc['campaign']
    return build_clusters(market,day,a['rules']['year'] if a else settings.game_year,symbol)


@router.post('/game/debug/last-day')
async def debug_last_day(body: DebugJump,user=Depends(current_user)):
    if not settings.enable_debug_tools:
        raise HTTPException(404, '디버깅 기능이 꺼져 있어요.')
    doc, version, _, _ = await context(user)
    a = require_campaign(doc)
    game.jump_to_month_end(a,body.settle)
    game.assess(a,market.quotes(game.game_date(a),a['rules']['year']))
    await store.save(user['id'],doc,version)
    return {'message':'디버깅 이동을 적용했어요. 이 여정은 일반 랭킹에서 제외돼요.'}
