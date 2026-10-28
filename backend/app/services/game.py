import time
from fastapi import HTTPException
from app.core.config import settings
from app.services.catalog import DIFFICULTIES

def create_account(difficulty,source):
    d=DIFFICULTIES[difficulty]
    return {'difficulty':difficulty,'initial':settings.initial_capital,'cash':settings.initial_capital+d['loan'],'principal':d['loan'],'rate':d['rate'],'interest':0.0,'accrued_at':time.time(),'started_at':time.time(),'ends_at':time.time()+settings.game_days*86400,'rewards':0,'positions':{},'trades':[],'completed':[],'source':source}

def accrue(a,now=None):
    now=time.time() if now is None else now
    a['interest']+=a['principal']*a['rate']*max(0,now-a['accrued_at'])/(365*86400)
    a['accrued_at']=now

def summary(a,quotes):
    prices={q['symbol']:q for q in quotes}
    positions=[]
    for symbol,p in a['positions'].items():
        q=prices[symbol]
        positions.append(dict(symbol=symbol,name=q['name'],quantity=p['quantity'],average=p['average'],price=q['price'],value=p['quantity']*q['price'],profit=(q['price']-p['average'])*p['quantity'],color=q['color']))
    assets=sum(p['value'] for p in positions)
    net=a['cash']+assets-a['principal']-a['interest']
    basis=a['initial']+a['rewards']
    return {**a,'positions':positions,'stock_value':assets,'net_assets':round(net),'profit':round(net-basis),'return_rate':round((net-basis)/basis*100,4),'daily_interest':round(a['principal']*a['rate']/365),'days_left':max(0,int((a['ends_at']-time.time())/86400)+1),'status':'bankrupt' if net<=0 else 'ended' if time.time()>=a['ends_at'] else 'active'}

def trade(a,symbol,side,quantity,price):
    if time.time()>=a['ends_at']: raise HTTPException(400,'투자 기간이 종료됐어요.')
    amount=quantity*price
    p=a['positions'].get(symbol,{'quantity':0,'average':0})
    if side=='buy':
        if a['cash']<amount: raise HTTPException(400,'주문할 수 있는 예수금이 부족해요.')
        p['average']=(p['quantity']*p['average']+amount)/(p['quantity']+quantity)
        p['quantity']+=quantity
        a['cash']-=amount
    else:
        if p['quantity']<quantity: raise HTTPException(400,'보유 수량보다 많이 매도할 수 없어요.')
        p['quantity']-=quantity
        a['cash']+=amount
    if p['quantity']: a['positions'][symbol]=p
    else: a['positions'].pop(symbol,None)
    a['trades'].insert(0,{'id':str(time.time_ns()),'symbol':symbol,'side':side,'quantity':quantity,'price':price,'amount':amount,'created_at':time.time()})

def repay(a,amount):
    due=a['principal']+a['interest']
    if amount>a['cash'] or amount>due: raise HTTPException(400,'예수금과 남은 대출금 안에서 상환해주세요.')
    interest_paid=min(amount,a['interest'])
    a['interest']-=interest_paid
    a['principal']-=amount-interest_paid
    a['cash']-=amount
