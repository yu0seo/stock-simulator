import type {Stock,Valuation} from './api';

export function withValuation(stock:Stock,basis:Valuation):Stock{
  const per=!basis.per_reason&&basis.eps!==null&&basis.eps>0?stock.price/basis.eps:null;
  const pbr=!basis.pbr_reason&&basis.bps!==null&&basis.bps>0?stock.price/basis.bps:null;
  return {...stock,per,pbr,valuation:{...basis,price:stock.price,per,pbr}};
}

export function ratioLabel(stock:Stock,metric:'per'|'pbr'){
  const v=stock[metric];
  if(metric==='per'&&stock.valuation?.eps!==null&&stock.valuation?.eps!==undefined&&stock.valuation.eps<=0)return stock.valuation.eps<0?'적자':'이익 없음';
  return v!==null&&Number.isFinite(v)&&v>0?v.toFixed(2)+'배':stock.valuation?'산출 불가':'—';
}

export function valuationYear(stock:Stock){
  if(stock.source==='sample')return '학습용 예시';
  return stock.valuation?.year?stock.valuation.year+' 공시 기준':stock.valuation?'공시 기준 미확인':'공시 지표 조회 중';
}

export function ValuationDetails({stock}:{stock:Stock}){
  const v=stock.valuation;
  if(stock.source==='sample')return <div className="tip"><p>PER·PBR은 학습용 예시예요. 실제 시세와 OpenDART 공시가 연결되면 연간 공시 기준으로 계산해요.</p></div>;
  if(!v)return <div className="tip" role="status"><p>연간 공시 기준 EPS·BPS를 확인하고 있어요. 시세와 모의 주문은 먼저 사용할 수 있어요.</p></div>;
  const format=(n:number|null)=>n===null?'확인 불가':n.toLocaleString('ko-KR',{maximumFractionDigits:2})+'원';
  return <div className="valuation-details"><div className="valuation-heading"><strong>{v.year?v.year+'년 연간 공시 기준':'연간 공시 기준 확인 필요'}</strong>{v.statement&&<span>{v.statement} · {v.as_of}</span>}</div><div className="valuation-inputs"><span>기본 EPS <b>{format(v.eps)}</b></span><span>BPS <b>{format(v.bps)}</b></span></div><p>PER = 현재가 ÷ 연간 기본 EPS · PBR = 현재가 ÷ 기말 BPS</p>{v.eps_source&&<p>EPS 출처: {v.eps_source}</p>}{v.bps_source&&<p>BPS 기준: {v.bps_source}</p>}{v.per_reason&&<p className="valuation-reason">PER 산출 불가: {v.per_reason}</p>}{v.pbr_reason&&<p className="valuation-reason">PBR 산출 불가: {v.pbr_reason}</p>}<p>현재가를 표시한 결산일의 공시 EPS·BPS로 나눈 참고 지표예요. 최근 12개월(TTM) 수치가 아니며, 공시 이후 분할·증자·소각 등 기업행동에 따른 주당지표 보정은 반영하지 않았어요.</p>{v.filing_url&&<a href={v.filing_url} target="_blank" rel="noreferrer">계산에 사용한 DART 공시 보기 ↗</a>}</div>;
}
