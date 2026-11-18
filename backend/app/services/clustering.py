"""Shared financial clustering for the company map and similar-company list."""
import math


def cluster_companies(companies):
    valid=[]
    excluded=[]
    for company in companies:
        f=company.get('financials')
        values=[f.get(k) for k in ('revenue','profit','equity','debt')] if f else []
        if len(values)!=4 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in values) or values[0]<=0 or values[2]<=0 or values[3]<0:
            excluded.append({'symbol':company['symbol'],'name':company['name'],'reason':'비교에 필요한 매출·순이익·자본·부채비율을 확인할 수 없어요.'})
            continue
        revenue,profit,equity,debt=values
        metrics=[profit/revenue*100,profit/equity*100,debt]
        valid.append({**{k:company[k] for k in ('symbol','name','sector')},'profit_margin':metrics[0],'equity_return':metrics[1],'debt_ratio':metrics[2],'year':f['year'],'statement':f.get('statement'),'vector':[math.copysign(math.log1p(abs(v)),v) for v in metrics]})
    if len(valid)<4: return {'items':[],'excluded':excluded,'method':'비교 가능한 기업이 4개 이상 필요해요.'}
    means=[sum(p['vector'][j] for p in valid)/len(valid) for j in range(3)]
    scales=[(sum((p['vector'][j]-means[j])**2 for p in valid)/len(valid))**.5 or 1 for j in range(3)]
    for point in valid: point['vector']=[(point['vector'][j]-means[j])/scales[j] for j in range(3)]
    centers=[p['vector'][:] for p in valid[::max(1,len(valid)//3)][:3]]
    def distance(a,b): return sum((x-y)**2 for x,y in zip(a,b))
    labels=[]
    for _ in range(20):
        updated=[min(range(len(centers)),key=lambda i:distance(p['vector'],centers[i])) for p in valid]
        if updated==labels: break
        labels=updated
        for i in range(len(centers)):
            group=[p['vector'] for p,label in zip(valid,labels) if label==i]
            if group: centers[i]=[sum(v[j] for v in group)/len(group) for j in range(3)]
    for point,label in zip(valid,labels): point['cluster']=label
    return {'items':valid,'excluded':excluded,'method':f'순이익률·기말자본 대비 이익률·부채비율 표준화 / K-means 3개 군집 / {len(companies)}개 기업 내 비교 (기말자본 대비 이익률은 ROE와 다름)'}
