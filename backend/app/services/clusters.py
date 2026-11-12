"""Point-in-time financial similarity. K-means operates in 3D; PCA only draws the map."""
import math
from app.services.catalog import BY_SYMBOL

FEATURES = ['총자산 규모', '부채 / 총자산', '연환산 순이익 / 기말총자산']


def number(value):
    if value is None or isinstance(value,bool):
        return None
    try:
        value = str(value).strip().replace(',','').replace(' ','')
        if value.startswith('(') and value.endswith(')'):
            value = '-'+value[1:-1]
        n = float(value)
        return n if math.isfinite(n) else None
    except ValueError:
        return None


def extract(report):
    if not report:
        return None
    rows = report['rows']
    def get(ids, statements):
        found = [r for r in rows if r.get('account_id') in ids and r.get('sj_div') in statements
                 and r.get('currency','KRW') in ('KRW','')]
        # IS preferred over CIS, and ambiguous duplicate facts are not guessed.
        if any(r.get('sj_div')=='IS' for r in found):
            found = [r for r in found if r['sj_div']=='IS']
        vals = {number(r.get('thstrm_amount')) for r in found}
        vals.discard(None)
        if len(vals)!=1:
            return None, None
        value=next(iter(vals))
        return value, next(r for r in found if number(r.get('thstrm_amount'))==value)
    assets, _ = get(['ifrs-full_Assets'],['BS'])
    debt, _ = get(['ifrs-full_Liabilities'],['BS'])
    profit, row = get(['ifrs-full_ProfitLoss'],['IS','CIS'])
    if profit is None:
        names = {prefix+'순이익'+suffix for prefix in ('당기','당분기','분기','당반기','반기','연결당기','연결분기','연결반기') for suffix in ('','손실')}
        fallback=[]
        for r in rows:
            name=''.join(c for c in r.get('account_nm','') if c not in ' ()\n\t')
            if name in names and r.get('sj_div') in ('IS','CIS') and r.get('currency','KRW') in ('KRW',''):
                fallback.append(r)
        if any(r['sj_div']=='IS' for r in fallback):
            fallback=[r for r in fallback if r['sj_div']=='IS']
        vals={number(r.get('thstrm_amount')) for r in fallback}
        vals.discard(None)
        if len(vals)==1:
            profit=next(iter(vals))
            row=next(r for r in fallback if number(r.get('thstrm_amount'))==profit)
    if assets is None or assets<=0 or debt is None or debt<0 or profit is None:
        return None
    code = report.get('report_code','11011')
    if code!='11011':
        cumulative = number(row.get('thstrm_add_amount'))
        profit = cumulative * {'11013':4,'11012':2,'11014':4/3}[code] if cumulative is not None else profit*4
    leverage = debt/assets*100
    earnings = profit/assets*100
    return {'raw':[assets,leverage,earnings],
            'vector':[math.log10(assets),leverage,math.asinh(earnings)],
            'period_end':report['period_end'],'published_at':report['published_at'],
            'statement':report.get('statement',''),'receipt':report['receipt']}


def distance(a,b):
    return sum((x-y)**2 for x,y in zip(a,b))


def kmeans(vectors, k=5):
    centers = [vectors[0][:]]
    for _ in range(min(k,len(vectors))-1):
        far = max(range(len(vectors)),key=lambda i:min(distance(vectors[i],c) for c in centers))
        if min(distance(vectors[far],c) for c in centers)<1e-12:
            break
        centers.append(vectors[far][:])
    labels = None
    for _ in range(100):
        updated = [min(range(len(centers)),key=lambda j:distance(v,centers[j])) for v in vectors]
        if updated==labels:
            break
        labels = updated
        for j in range(len(centers)):
            group=[v for i,v in enumerate(vectors) if labels[i]==j]
            if group:
                centers[j]=[sum(v[d] for v in group)/len(group) for d in range(3)]
    return labels, centers


def pca(vectors):
    # Jacobi eigen decomposition of the symmetric 3x3 covariance matrix.
    n = len(vectors)
    cov = [[sum(v[i]*v[j] for v in vectors)/n for j in range(3)] for i in range(3)]
    basis = [[float(i==j) for j in range(3)] for i in range(3)]
    for _ in range(60):
        p,q = max(((0,1),(0,2),(1,2)),key=lambda pair:abs(cov[pair[0]][pair[1]]))
        if abs(cov[p][q])<1e-12:
            break
        angle = .5*math.atan2(2*cov[p][q],cov[q][q]-cov[p][p])
        c,s = math.cos(angle),math.sin(angle)
        rot = [[float(i==j) for j in range(3)] for i in range(3)]
        rot[p][p]=rot[q][q]=c
        rot[p][q]=s
        rot[q][p]=-s
        def matmul(a,b):
            return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        cov = matmul(matmul(list(map(list,zip(*rot))),cov),rot)
        basis = matmul(basis,rot)
    order = sorted(range(3),key=lambda j:-cov[j][j])
    axes = [[basis[i][j] for i in range(3)] for j in order[:2]]
    for axis in axes:
        if axis[max(range(3),key=lambda i:abs(axis[i]))]<0:
            axis[:] = [-x for x in axis]
    total = sum(max(0,cov[i][i]) for i in range(3))
    explained = [max(0,cov[j][j])/total if total else 0 for j in order[:2]]
    return [[sum(x*y for x,y in zip(v,axis)) for axis in axes] for v in vectors], explained


def build_clusters(market, day, year, selected=None):
    included,excluded = [],[]
    for symbol,stock in BY_SYMBOL.items():
        f = market.financials(symbol,day,year)
        feature = extract(f['report'])
        identity = {k:stock[k] for k in ('symbol','name','sector')}
        if feature:
            included.append({**identity,**feature})
        else:
            excluded.append({**identity,'reason':'현재 날짜에 공개된 비교 가능한 총자산·부채·순이익이 부족해요.'})
    selected = selected or (included[0]['symbol'] if included else next(iter(BY_SYMBOL)))
    if len(included)<3:
        return {'as_of':day,'nodes':[],'excluded':excluded,'clusters':[],'recommendations':[],
                'selected':selected,'features':FEATURES,'explained':[0,0],'total':len(BY_SYMBOL),
                'message':'공개된 비교 가능 재무자료가 3개 기업 이상일 때 군집 지도가 표시돼요.'}
    means=[sum(x['vector'][d] for x in included)/len(included) for d in range(3)]
    scales=[(sum((x['vector'][d]-means[d])**2 for x in included)/len(included))**.5 or 1 for d in range(3)]
    vectors=[[(x['vector'][d]-means[d])/scales[d] for d in range(3)] for x in included]
    labels,centers = kmeans(vectors)
    coords,explained = pca(vectors)
    nodes = [{k:v for k,v in x.items() if k!='vector'} | {'cluster':labels[i],'x':coords[i][0],'y':coords[i][1]} for i,x in enumerate(included)]
    selected_i = next((i for i,x in enumerate(nodes) if x['symbol']==selected),None)
    recommendations=[]
    if selected_i is not None:
        candidates = sorted((i for i in range(len(nodes)) if i!=selected_i),key=lambda i:distance(vectors[selected_i],vectors[i]))[:6]
        recommendations=[{**nodes[i],'distance':round(distance(vectors[selected_i],vectors[i])**.5,3),
                          'same_cluster':labels[i]==labels[selected_i]} for i in candidates]
    groups=[{'id':i,'count':labels.count(i)} for i in range(len(centers)) if labels.count(i)]
    return {'as_of':day,'nodes':nodes,'excluded':excluded,'clusters':groups,'recommendations':recommendations,
            'selected':selected,'features':FEATURES,'explained':explained,'total':len(BY_SYMBOL),
            'message':None if selected_i is not None else '선택한 기업은 현재 공개된 비교 지표가 부족해 유사도를 계산하지 않아요.',
            'method':'공시 기준 3개 지표 변환·표준화 → K-means 최대 5군집. 지도는 PCA 2차원 투영이며 추천 거리는 원래 3차원 지표로 계산해요.'}
