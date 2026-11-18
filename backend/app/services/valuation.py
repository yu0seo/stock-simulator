"""Annual, reported-basis valuation. Never estimate EPS from period-end shares."""
import re
from decimal import Decimal, InvalidOperation


def number(value):
    if value is None or isinstance(value, bool): return None
    text=str(value).strip().replace(',','').replace('−','-')
    if text.startswith('(') and text.endswith(')'): text='-'+text[1:-1]
    try:
        result=Decimal(text)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def unique(values):
    values={v for v in values if v is not None}
    return next(iter(values)) if len(values)==1 else None


def account(rows,ids):
    return unique(number(r.get('thstrm_amount')) for r in rows if r.get('account_id') in ids)


def report_date(rows):
    dates=set()
    for r in rows:
        if r.get('sj_div')!='BS': continue
        matches=re.findall(r'\d{4}[.\-/]\d{2}[.\-/]\d{2}',r.get('thstrm_dt',''))
        if matches: dates.add(re.sub(r'[./]','-',matches[-1]))
    return next(iter(dates)) if len(dates)==1 else None


def basic_eps(rows):
    ordinary=[r for r in rows if r.get('sj_div') in ('IS','CIS') and '우선' not in (r.get('account_nm','')+' '+r.get('account_detail',''))]
    total=[r for r in ordinary if r.get('account_id')=='ifrs-full_BasicEarningsLossPerShare']
    explicit=[r for r in total if '보통' in (r.get('account_nm','')+' '+r.get('account_detail',''))]
    total=explicit or total
    if total: return unique(number(r.get('thstrm_amount')) for r in total)
    parts=[account(ordinary,{name}) for name in ('ifrs-full_BasicEarningsLossPerShareFromContinuingOperations','ifrs-full_BasicEarningsLossPerShareFromDiscontinuedOperations')]
    if all(p is not None for p in parts): return sum(parts)
    combined=[r for r in ordinary if re.fullmatch(r'보통주(?:기본/희석|기본및희석)주당(?:순)?이익(?:\(손실\))?',r.get('account_nm','').replace(' ',''))]
    return unique(number(r.get('thstrm_amount')) for r in combined)


def dividend_eps(rows,fs_div,as_of):
    candidates=[]
    for r in rows:
        label=r.get('se','').replace(' ','')
        if '기본주당순이익' not in label or '(원)' not in label: continue
        if fs_div=='CFS' and '연결' not in label: continue
        if fs_div=='OFS' and '연결' in label: continue
        if r.get('stock_knd','').strip() not in ('보통주','보통주식','-',''): continue
        if r.get('stlm_dt','').replace('.','-')!=as_of: continue
        candidates.append(number(r.get('thstrm')))
    return unique(candidates)


def share_counts(row):
    values=[number(row.get(k)) for k in ('istc_totqy','tesstk_co','distb_stock_co')]
    if all(str(row.get(k,'')).strip()=='-' for k in ('istc_totqy','tesstk_co','distb_stock_co')):
        return (Decimal(0),Decimal(0),Decimal(0))
    issued,treasury,outstanding=values
    if str(row.get('tesstk_co','')).strip()=='-' and issued is not None and outstanding==issued:
        treasury=Decimal(0)
    if any(x is None or x<0 or x!=x.to_integral_value() for x in (issued,treasury,outstanding)):
        return None
    return (issued,treasury,outstanding) if issued-treasury==outstanding else None


def share_basis(rows,as_of):
    """Validate all share classes against the filing's total, excluding treasury shares."""
    result={'issued':None,'outstanding':None}
    dated=[r for r in rows if r.get('stlm_dt','').replace('.','-')==as_of and r.get('se','').strip()!='비고']
    totals=[r for r in dated if r.get('se','').strip() in ('합계','총계')]
    classes=[r for r in dated if r not in totals]
    if len(totals)!=1 or not classes: return result
    total=share_counts(totals[0])
    counts=[share_counts(r) for r in classes]
    if total is None or any(c is None for c in counts): return result
    if tuple(sum(c[i] for c in counts) for i in range(3))!=total or total[2]<=0: return result
    common=[r for r in classes if r.get('se','').strip() in ('보통주','보통주식')]
    result['issued']=share_counts(common[0])[0] if len(common)==1 else None
    result['outstanding']=total[2]
    return result


def make_basis(rows,shares,year,fs_div,dividends=()):
    as_of=report_date(rows)
    refs={r.get('rcept_no') for r in rows if re.fullmatch(r'\d{14}',str(r.get('rcept_no','')))}
    receipt=next(iter(refs)) if len(refs)==1 else None
    if as_of is None and receipt:
        # The full-statement API omits dates; the same filing's share disclosure supplies one.
        dates={r.get('stlm_dt','').replace('.','-') for r in shares if r.get('rcept_no')==receipt}
        if len(dates)==1 and re.fullmatch(r'\d{4}-\d{2}-\d{2}',next(iter(dates))):
            as_of=next(iter(dates))
    basis={'source':'opendart','year':year,'as_of':as_of,'statement':'연결' if fs_div=='CFS' else '별도',
           'eps':None,'bps':None,'issued':None,'eps_source':None,'bps_source':None,'per_reason':None,'pbr_reason':None,
           'filing_url':f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}' if receipt else None}
    if not as_of or as_of[:4]!=str(year):
        basis.update(per_reason='연간 공시의 결산기준일을 확인할 수 없어요.',pbr_reason='연간 공시의 결산기준일을 확인할 수 없어요.')
        return basis
    # Both endpoints must describe the same annual statement basis; mismatched restatements fail closed.
    share_refs={r.get('rcept_no') for r in shares if r.get('rcept_no')}
    if receipt and share_refs and share_refs!={receipt}:
        basis.update(per_reason='재무제표와 주식 수 공시의 접수번호가 달라요.',pbr_reason='재무제표와 주식 수 공시의 접수번호가 달라요.')
        return basis
    cap=share_basis(shares,as_of)
    basis['issued']=float(cap['issued']) if cap['issued'] is not None else None
    eps=basic_eps(rows)
    eps_source='재무제표 기본 EPS'
    if eps is not None and not any(r.get('account_id')=='ifrs-full_BasicEarningsLossPerShare' for r in rows):
        eps_source='재무제표 기본 EPS (계속영업 + 중단영업)' if any(r.get('account_id')=='ifrs-full_BasicEarningsLossPerShareFromContinuingOperations' for r in rows) else '재무제표 보통주 기본·희석 동일 EPS'
    if eps is None:
        valid_dividends=[r for r in dividends if not receipt or r.get('rcept_no')==receipt]
        eps=dividend_eps(valid_dividends,fs_div,as_of)
        eps_source='배당 공시 주당순이익'
    if eps is not None: basis.update(eps=float(eps),eps_source=eps_source)
    if eps is None: basis['per_reason']='보통주 기본 EPS가 누락됐거나 값이 모호해요.'
    elif eps<=0: basis['per_reason']='EPS가 0 이하라 PER을 산출하지 않아요.'
    if cap['outstanding'] is None:
        basis['pbr_reason']='같은 결산일의 발행·자기·유통주식 수 합계를 확인할 수 없어요.'
    else:
        equity=account(rows,{'ifrs-full_EquityAttributableToOwnersOfParent'}) if fs_div=='CFS' else account(rows,{'ifrs-full_Equity'})
        if equity is None: basis['pbr_reason']='주주 귀속 자본을 확인할 수 없어요.'
        elif equity<=0: basis['pbr_reason']='주주 귀속 자본이 0 이하라 PBR을 산출하지 않아요.'
        else: basis.update(bps=float(equity/cap['outstanding']),bps_source='지배지분 자본 ÷ 보통주·우선주 합산 유통주식 수(자기주식 제외)' if fs_div=='CFS' else '별도 자기자본 ÷ 전체 유통주식 수(자기주식 제외)')
    return basis


def ratios(price,basis):
    result={**basis,'price':price,'per':None,'pbr':None}
    for metric,denominator in (('per','eps'),('pbr','bps')):
        d=number(basis.get(denominator))
        if not basis.get(metric+'_reason') and d is not None and d>0:
            result[metric]=round(float(Decimal(str(price))/d),4)
    return result
