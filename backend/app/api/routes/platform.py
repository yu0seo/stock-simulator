import math
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from app.core.config import settings
from app.services.catalog import BY_SYMBOL, STOCKS, LESSONS, DIFFICULTIES
from app.services.market import market
from app.services.store import store
from app.services.game import create_account, accrue, summary, trade, repay

router=APIRouter()
auth_attempts={}

class Credentials(BaseModel):
    email: str = Field(min_length=5,max_length=254)
    password: str = Field(min_length=8,max_length=128)
    nickname: str = Field(default='투자자',min_length=2,max_length=12,pattern=r'^[가-힣a-zA-Z0-9_]+$')
    @field_validator('email')
    @classmethod
    def email_valid(cls,v):
        v=v.strip().lower()
        if '@' not in v or '.' not in v.split('@')[-1]: raise ValueError('올바른 이메일을 입력해주세요.')
        return v

class Start(BaseModel):
    difficulty: Literal['easy','normal','hard']='easy'

class Order(BaseModel):
    symbol: str
    side: Literal['buy','sell']
    quantity: int = Field(gt=0,le=1000000,strict=True)

class Repayment(BaseModel):
    amount: int = Field(gt=0,le=1000000000,strict=True)

class Answer(BaseModel):
    answer: int = Field(ge=0,le=2,strict=True)

def source(): return 'toss' if settings.live_market else 'sample'

async def current_user(request:Request,response:Response):
    return await store.user(request,response)

def throttle(request):
    key=request.client.host if request.client else 'local'
    now=time.time()
    values=[t for t in auth_attempts.get(key,[]) if t>now-60]
    if len(values)>=15: raise HTTPException(429,'잠시 후 다시 시도해주세요.')
    auth_attempts[key]=values+[now]

@router.get('/config')
async def config():
    return {'market_mode':source(),'auth_mode':'supabase' if settings.cloud_auth else 'local','financial_mode':'opendart' if settings.opendart_api_key else 'sample','initial_capital':settings.initial_capital,'game_days':settings.game_days,'difficulties':DIFFICULTIES,'market_open':await market.trading_open(),'poll_seconds':15}

@router.post('/auth/signup')
async def signup(body:Credentials,request:Request,response:Response):
    throttle(request)
    return await store.signup(body.email,body.password,body.nickname,response)

@router.post('/auth/login')
async def login(body:Credentials,request:Request,response:Response):
    throttle(request)
    return await store.login(body.email,body.password,response)

@router.get('/auth/me')
async def me(user=Depends(current_user)): return user

@router.post('/auth/logout')
async def logout(request:Request,response:Response):
    await store.logout(request,response)
    return {'ok':True}

@router.get('/market')
async def quotes(): return {'stocks':await market.quotes(),'source':source(),'market_open':await market.trading_open()}

def check_symbol(symbol):
    if symbol not in BY_SYMBOL: raise HTTPException(404,'지원하지 않는 종목이에요.')

@router.get('/market/{symbol}/chart')
async def chart(symbol:str):
    check_symbol(symbol)
    return await market.chart(symbol)

@router.get('/companies/{symbol}/financials')
async def financials(symbol:str):
    check_symbol(symbol)
    return await market.financials(symbol)

@router.get('/companies/{symbol}/similar')
async def similar(symbol:str):
    check_symbol(symbol)
    # Standardized feature vectors + deterministic K-means; demo sample is labeled.
    features=[]
    for stock in STOCKS:
        f=await market.financials(stock['symbol'])
        values=[f['revenue'],f['profit'],f['equity'],f['debt']]
        if all(v is not None and math.isfinite(v) for v in values) and f['revenue']>0 and f['equity']>0 and f['debt']>=0:
            vals=[f['profit']/f['revenue']*100,f['profit']/f['equity']*100,f['debt']]
            features.append((stock['symbol'],[math.copysign(math.log1p(abs(v)),v) for v in vals]))
    if len(features)<4 or symbol not in dict(features):
        return {'items':[],'source':'live' if settings.opendart_api_key else 'sample','method':'비교 가능한 재무지표가 부족해요.'}
    means=[sum(v[j] for _,v in features)/len(features) for j in range(3)]
    scales=[(sum((v[j]-means[j])**2 for _,v in features)/len(features))**.5 or 1 for j in range(3)]
    vectors={s:[(v[j]-means[j])/scales[j] for j in range(3)] for s,v in features}
    centers=list(vectors.values())[::max(1,len(vectors)//3)][:3]
    def dist(a,b): return sum((x-y)**2 for x,y in zip(a,b))
    labels={}
    for _ in range(20):
        updated={s:min(range(len(centers)),key=lambda i:dist(v,centers[i])) for s,v in vectors.items()}
        if updated==labels: break
        labels=updated
        for i in range(len(centers)):
            group=[v for s,v in vectors.items() if labels[s]==i]
            if group: centers[i]=[sum(v[j] for v in group)/len(group) for j in range(3)]
    candidates=sorted([s for s in vectors if s!=symbol],key=lambda s:(labels[s]!=labels[symbol],dist(vectors[s],vectors[symbol])))[:3]
    return {'items':[{'symbol':s,'name':BY_SYMBOL[s]['name'],'same_cluster':labels[s]==labels[symbol],'distance':round(dist(vectors[s],vectors[symbol])**.5,2)} for s in candidates],'source':'live' if settings.opendart_api_key else 'sample','method':'순이익률·기말자본 대비 이익률·부채비율 표준화 / K-means 3개 군집 / 8개 기업 내 비교 (기말자본 대비 이익률은 ROE와 다름)'}

@router.get('/portfolio')
async def portfolio(user=Depends(current_user)):
    a,_=await store.account(user['id'])
    if not a: return {'account':None}
    accrue(a)
    return {'account':summary(a,await market.quotes())}

@router.post('/game/start')
async def start(body:Start,user=Depends(current_user)):
    a,version=await store.account(user['id'])
    if a: raise HTTPException(409,'이미 투자 여정을 시작했어요.')
    a=create_account(body.difficulty,source())
    await store.save(user['id'],a,version)
    return {'ok':True}

@router.post('/game/restart')
async def restart(body:Start,user=Depends(current_user)):
    _,version=await store.account(user['id'])
    await store.save(user['id'],create_account(body.difficulty,source()),version)
    return {'ok':True}

async def active_account(user):
    a,version=await store.account(user['id'])
    if not a: raise HTTPException(400,'먼저 난이도를 선택하고 여정을 시작해주세요.')
    if a['source']!=source(): raise HTTPException(409,'데이터 모드가 변경됐어요. 설정에서 새 여정을 시작해주세요.')
    accrue(a)
    return a,version

@router.post('/trades')
async def order(body:Order,user=Depends(current_user)):
    check_symbol(body.symbol)
    a,version=await active_account(user)
    quotes=await market.quotes()
    if summary(a,quotes)['net_assets']<=0: raise HTTPException(400,'순자산이 0원 이하예요. 여정 결과를 확인해주세요.')
    q=next(q for q in quotes if q['symbol']==body.symbol)
    if q['price']<=0: raise HTTPException(400,'유효한 주문 가격이 없어요.')
    if settings.live_market:
        await market.check_trading_day(body.symbol,q)
    # No client-provided price is used. Toss never receives an actual order.
    trade(a,body.symbol,body.side,body.quantity,q['price'])
    await store.save(user['id'],a,version)
    return {'message':'모의 주문이 체결됐어요.','price':q['price']}

@router.post('/loans/repay')
async def pay(body:Repayment,user=Depends(current_user)):
    a,version=await active_account(user)
    repay(a,body.amount)
    await store.save(user['id'],a,version)
    return {'message':'대출을 상환했어요.'}

@router.get('/lessons')
async def lessons(): return [{k:v for k,v in x.items() if k not in ('answer','explanation')} for x in LESSONS]

@router.post('/lessons/{lesson_id}/answer')
async def answer(lesson_id:str,body:Answer,user=Depends(current_user)):
    lesson=next((x for x in LESSONS if x['id']==lesson_id),None)
    if not lesson: raise HTTPException(404,'학습 콘텐츠를 찾을 수 없어요.')
    a,version=await active_account(user)
    if time.time()>=a['ends_at']: raise HTTPException(400,'여정이 종료되어 보상을 받을 수 없어요.')
    correct=body.answer==lesson['answer']
    reward=0
    if correct and lesson_id not in a['completed']:
        reward=lesson['reward']
        a['completed'].append(lesson_id)
        a['rewards']+=reward
        a['cash']+=reward
        await store.save(user['id'],a,version)
    return {'correct':correct,'reward':reward,'explanation':lesson['explanation']}

@router.get('/ranking')
async def ranking(difficulty:Literal['all','easy','normal','hard']='all'):
    quotes=await market.quotes()
    rows=[]
    for row in await store.accounts():
        a=row['data']
        if a['source']!=source() or (difficulty!='all' and a['difficulty']!=difficulty): continue
        accrue(a)
        s=summary(a,quotes)
        rows.append({'id':row['id'],'nickname':row['nickname'],'difficulty':a['difficulty'],'return_rate':s['return_rate'],'net_assets':s['net_assets'],'completed':len(a['completed'])})
    rows.sort(key=lambda x:(-x['return_rate'],x['nickname']))
    for i,row in enumerate(rows): row['rank']=i+1
    return {'items':rows[:100],'source':source(),'formula':'(순자산 − 초기 자기자본 − 학습 보상) ÷ (초기 자기자본 + 학습 보상) × 100','count':len(rows)}
