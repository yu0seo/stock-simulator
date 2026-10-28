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
    candidates=[r for r in rows if r.get('account_id')=='ifrs-full_BasicEarningsLossPerShare' and r.get('sj_div') in ('IS','CIS')]
    candidates=[r for r in candidates if '우선' not in (r.get('account_nm','')+' '+r.get('account_detail',''))]
    explicit=[r for r in candidates if '보통' in (r.get('account_nm','')+' '+r.get('account_detail',''))]
    return unique(number(r.get('thstrm_amount')) for r in (explicit or candidates))


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


def share_basis(rows,as_of):
    """Require explicit common, treasury and total counts from the same balance date."""
    result={'issued':None,'outstanding':None,'common_only':False}
    dated=[r for r in rows if r.get('stlm_dt','').replace('.','-')==as_of and r.get('se','').strip()!='비고']
    common=[r for r in dated if r.get('se','').strip() in ('보통주','보통주식')]
    if len(common)!=1: return result
    r=common[0]
    issued=number(r.get('istc_totqy'))
    treasury=number(r.get('tesstk_co'))
    outstanding=number(r.get('distb_stock_co'))
    if any(x is None or x!=x.to_integral_value() for x in (issued,treasury,outstanding)): return result
    if issued<=0 or treasury<0 or outstanding<=0 or issued-treasury!=outstanding: return result
    result.update(issued=issued,outstanding=outstanding)
    totals=[r for r in dated if r.get('se','').strip() in ('합계','총계')]
    # If any other class exists, its book-value allocation is not guessed.
    result['common_only']=len(totals)==1 and number(totals[0].get('istc_totqy'))==issued and all(
        r in common or r in totals or number(r.get('istc_totqy'))==0 for r in dated)
    return result


def make_basis(rows,shares,year,fs_div,dividends=()):
    as_of=report_date(rows)
    refs={r.get('rcept_no') for r in rows if re.fullmatch(r'\d{14}',str(r.get('rcept_no','')))}
    receipt=next(iter(refs)) if len(refs)==1 else None
    basis={'source':'opendart','year':year,'as_of':as_of,'statement':'연결' if fs_div=='CFS' else '별도',
           'eps':None,'bps':None,'issued':None,'eps_source':None,'per_reason':None,'pbr_reason':None,
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
    if eps is None:
        valid_dividends=[r for r in dividends if not receipt or r.get('rcept_no')==receipt]
        eps=dividend_eps(valid_dividends,fs_div,as_of)
        eps_source='배당 공시 주당순이익'
    if eps is None: basis['per_reason']='보통주 기본 EPS가 누락됐거나 값이 모호해요.'
    elif eps<=0: basis['per_reason']='EPS가 0 이하라 PER을 산출하지 않아요.'
    else: basis.update(eps=float(eps),eps_source=eps_source)
    if cap['issued'] is None:
        basis.update(per_reason='같은 결산일의 보통주·자기주식 수를 확인할 수 없어요.',pbr_reason='같은 결산일의 보통주·자기주식 수를 확인할 수 없어요.')
    elif not cap['common_only']:
        basis['pbr_reason']='우선주 등 다른 종류주식이 있거나 자본 배분 근거가 부족해요.'
    else:
        equity=account(rows,{'ifrs-full_EquityAttributableToOwnersOfParent'}) if fs_div=='CFS' else account(rows,{'ifrs-full_Equity'})
        if equity is None: basis['pbr_reason']='주주 귀속 자본을 확인할 수 없어요.'
        elif equity<=0: basis['pbr_reason']='주주 귀속 자본이 0 이하라 PBR을 산출하지 않아요.'
        else: basis['bps']=float(equity/cap['outstanding'])
    return basis


def ratios(price,basis,current_issued):
    result={**basis,'price':price,'per':None,'pbr':None}
    # Compare issued common shares, not outstanding shares (treasury repurchases are different).
    current=number(current_issued)
    reported=number(basis.get('issued'))
    reason=None
    if reported is not None:
        if current is None or current<=0 or current!=current.to_integral_value(): reason='현재 발행주식 수를 확인할 수 없어요.'
        elif current!=reported: reason='공시 이후 발행주식 수가 변경되어 주당지표 재확인이 필요해요.'
    if reason:
        result.update(per_reason=reason,pbr_reason=reason)
    else:
        for metric,denominator in (('per','eps'),('pbr','bps')):
            d=number(basis.get(denominator))
            if not basis.get(metric+'_reason') and d is not None and d>0:
                result[metric]=round(float(Decimal(str(price))/d),4)
    return result
