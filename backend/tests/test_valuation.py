import asyncio
from datetime import datetime
import httpx
import pytest
from fastapi import HTTPException
from app.core.config import settings
from app.services.market import Market, KST
from app.services.valuation import make_basis, ratios, basic_eps

YEAR='2025'
DATE='2025-12-31'
RECEIPT='20260317000001'

def report(eps='2,000',owners='950,000',total='1,500,000'):
    rows=[dict(account_id='ifrs-full_Equity',sj_div='BS',account_nm='자본총계',thstrm_amount=total,thstrm_dt='2025.12.31 현재',rcept_no=RECEIPT),dict(account_id='ifrs-full_EquityAttributableToOwnersOfParent',sj_div='BS',account_nm='지배기업 소유주지분',thstrm_amount=owners,thstrm_dt='2025.12.31 현재',rcept_no=RECEIPT)]
    if eps is not None: rows.append(dict(account_id='ifrs-full_BasicEarningsLossPerShare',sj_div='IS',account_nm='기본주당이익',account_detail='보통주',thstrm_amount=eps,rcept_no=RECEIPT))
    return rows

def shares(preferred=0,date=DATE):
    common=dict(se='보통주',istc_totqy='1,000',tesstk_co='50',distb_stock_co='950',stlm_dt=date,rcept_no=RECEIPT)
    rows=[common,dict(se='합계',istc_totqy=str(1000+preferred),stlm_dt=date,rcept_no=RECEIPT)]
    if preferred: rows.append(dict(se='우선주',istc_totqy=str(preferred),stlm_dt=date,rcept_no=RECEIPT))
    return rows

def test_annual_per_pbr_parent_equity_treasury_and_price_recalculation():
    basis=make_basis(report(),shares(),YEAR,'CFS')
    assert basis['eps']==2000 and basis['bps']==1000
    assert basis['as_of']==DATE and basis['statement']=='연결'
    assert basis['filing_url'].endswith(RECEIPT)
    a=ratios(20000,basis,'1000')
    b=ratios(30000,basis,'1000')
    assert (a['per'],a['pbr'])==(10,20)
    assert (b['per'],b['pbr'])==(15,30)

def test_ordinary_eps_survives_preferred_but_pbr_is_not_guessed():
    rows=report()
    rows.append(dict(account_id='ifrs-full_BasicEarningsLossPerShare',sj_div='IS',account_nm='우선주기본주당이익',account_detail='우선주',thstrm_amount='9999'))
    basis=make_basis(rows,shares(preferred=100),YEAR,'CFS')
    value=ratios(20000,basis,'1000')
    assert value['per']==10 and value['pbr'] is None
    assert '우선주' in value['pbr_reason']

@pytest.mark.parametrize('eps',['0','-100','(100)','NaN','Infinity',None])
def test_unusable_eps_never_returns_negative_or_fake_per(eps):
    basis=make_basis(report(eps=eps),shares(),YEAR,'CFS')
    v=ratios(20000,basis,'1000')
    assert v['per'] is None and v['per_reason']
    assert v['pbr']==20

def test_ambiguous_eps_and_diluted_eps_are_not_selected():
    rows=report()
    rows.append(dict(account_id='ifrs-full_BasicEarningsLossPerShare',sj_div='IS',account_detail='보통주',thstrm_amount='3000'))
    assert basic_eps(rows) is None
    assert basic_eps([dict(account_id='ifrs-full_DilutedEarningsLossPerShare',sj_div='IS',thstrm_amount='100')]) is None

def test_dividend_eps_fallback_matches_statement_date_and_receipt():
    dividends=[dict(se='(연결)기본주당순이익(원)',stock_knd='보통주',thstrm='2,500',stlm_dt=DATE,rcept_no=RECEIPT),dict(se='(별도)기본주당순이익(원)',stock_knd='보통주',thstrm='9999',stlm_dt=DATE,rcept_no=RECEIPT)]
    b=make_basis(report(eps=None),shares(),YEAR,'CFS',dividends)
    assert b['eps']==2500 and b['eps_source']=='배당 공시 주당순이익'
    dividends[0]['rcept_no']='20260317000002'
    assert make_basis(report(eps=None),shares(),YEAR,'CFS',dividends)['eps'] is None

def test_unspecified_or_diluted_dividend_eps_is_not_treated_as_basic():
    for label in ('(연결)주당순이익(원)','(연결)희석주당순이익(원)'):
        dividends=[dict(se=label,stock_knd='보통주',thstrm='2500',stlm_dt=DATE,rcept_no=RECEIPT)]
        assert make_basis(report(eps=None),shares(),YEAR,'CFS',dividends)['eps'] is None

def test_separate_statement_uses_separate_equity():
    b=make_basis(report(total='1,900,000'),shares(),YEAR,'OFS')
    assert b['bps']==2000 and b['statement']=='별도'

def test_consolidated_equity_never_substitutes_total_including_noncontrolling_interest():
    rows=[r for r in report() if r['account_id']!='ifrs-full_EquityAttributableToOwnersOfParent']
    b=make_basis(rows,shares(),YEAR,'CFS')
    assert b['bps'] is None and b['pbr_reason']

@pytest.mark.parametrize('equity',['0','-100','NaN'])
def test_nonpositive_equity_not_a_valid_bps(equity):
    b=make_basis(report(owners=equity),shares(),YEAR,'CFS')
    assert b['bps'] is None and b['pbr_reason']

def test_share_date_receipt_and_treasury_mismatches_fail_closed():
    for invalid in [shares(date='2024-12-31'),shares(),shares()]:
        if invalid[0]['stlm_dt']==DATE:
            if invalid[0]['distb_stock_co']=='950': invalid[0]['distb_stock_co']='999'
        b=make_basis(report(),invalid,YEAR,'CFS')
        assert b['pbr_reason'] and ratios(20000,b,'1000')['per'] is None
    mismatch=shares()
    mismatch[0]['rcept_no']='20260317000002'
    assert make_basis(report(),mismatch,YEAR,'CFS')['per_reason']

def test_incomplete_share_classes_and_unknown_treasury_do_not_estimate():
    for s in ([shares()[0]],shares()):
        if len(s)>1: s[0]['tesstk_co']='-'
        b=make_basis(report(),s,YEAR,'CFS')
        assert b['bps'] is None

@pytest.mark.parametrize('current',['2000',None,'NaN','0'])
def test_post_report_capital_changes_or_missing_current_shares_prevent_ratios(current):
    v=ratios(20000,make_basis(report(),shares(),YEAR,'CFS'),current)
    assert v['per'] is None and v['pbr'] is None
    assert v['per_reason'] and v['pbr_reason']

def test_unknown_report_date_never_uses_invented_december_31():
    rows=report()
    for r in rows: r.pop('thstrm_dt',None)
    assert make_basis(rows,shares(),YEAR,'CFS')['as_of'] is None

def configure(monkeypatch):
    monkeypatch.setattr(settings,'data_mode','auto')
    monkeypatch.setattr(settings,'toss_client_id','test')
    monkeypatch.setattr(settings,'toss_client_secret','test')
    monkeypatch.setattr(settings,'opendart_api_key','test')
    monkeypatch.setattr(settings,'dart_business_year',YEAR)

def test_dart_contracts_and_cached_denominators_repriced(monkeypatch):
    configure(monkeypatch)
    calls=[]
    def handler(r):
        calls.append(r.url.path)
        assert r.url.params['bsns_year']==YEAR and r.url.params['reprt_code']=='11011'
        if 'fnlttSinglAcntAll' in r.url.path:
            assert r.url.params['fs_div']=='CFS'
            return httpx.Response(200,json={'status':'000','list':report()})
        assert 'stockTotqySttus' in r.url.path
        return httpx.Response(200,json={'status':'000','list':shares()})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    m=Market()
    price=[20000]
    async def quotes(): return [{'symbol':'005930','price':price[0]}]
    async def toss(path,params):
        assert path=='/api/v1/stocks'
        return [{'symbol':'005930','sharesOutstanding':'1000'}]
    monkeypatch.setattr(m,'quotes',quotes)
    monkeypatch.setattr(m,'toss',toss)
    async def run():
        assert (await m.valuations())[0]['per']==10
        price[0]=30000
        assert (await m.valuations())[0]['per']==15
    asyncio.run(run())
    assert len(calls)==2

def test_unpublished_annual_fallback_and_explicit_year(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(settings,'dart_business_year','')
    m=Market()
    latest=datetime.now(KST).year-1
    calls=[]
    async def dart(endpoint,symbol,year,fs_div):
        calls.append((year,fs_div))
        return report() if year==latest-1 and fs_div=='CFS' else None
    monkeypatch.setattr(m,'dart',dart)
    result=asyncio.run(m.annual_report('005930'))
    assert result['year']==str(latest-1)
    assert calls==[(latest,'CFS'),(latest,'OFS'),(latest-1,'CFS')]
    monkeypatch.setattr(settings,'dart_business_year',str(latest))
    with pytest.raises(HTTPException): asyncio.run(MarketWithDart(dart).annual_report('005930'))

class MarketWithDart(Market):
    def __init__(self,dart):
        super().__init__()
        self.dart=dart

def test_dart_errors_do_not_fabricate_or_poison_quotes(monkeypatch):
    configure(monkeypatch)
    m=Market()
    async def quotes():return [{'symbol':'005930','price':20000}]
    async def toss(*args):return []
    async def dart(*args):raise HTTPException(502,'공시 연결 실패')
    monkeypatch.setattr(m,'quotes',quotes)
    monkeypatch.setattr(m,'toss',toss)
    monkeypatch.setattr(m,'dart',dart)
    result=asyncio.run(m.valuations())[0]
    assert result['per'] is None and result['pbr'] is None
    assert result['source']=='unavailable' and result['per_reason']=='공시 연결 실패'
    assert asyncio.run(m.quotes())[0]['price']==20000
