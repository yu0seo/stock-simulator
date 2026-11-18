import {useEffect,useState} from 'react';
import {api} from './api';
import {RefreshCw,ArrowUpRight} from 'lucide-react';

type Point={symbol:string;name:string;sector:string;cluster:number;vector:number[];profit_margin:number;equity_return:number;debt_ratio:number;year:string;statement?:string};
type Model={items:Point[];excluded:{symbol:string;name:string;reason:string}[];source:string;method:string};
const colors=['#4b78d0','#32958b','#c28b48'];
const pct=(value:number)=>value.toLocaleString('ko-KR',{maximumFractionDigits:1})+'%';

export function ClusterMap({onSelect}:{onSelect:(symbol:string)=>void}){
  const [model,setModel]=useState<Model>();
  const [error,setError]=useState('');
  const [retry,setRetry]=useState(0);
  const [group,setGroup]=useState<number|null>(null);
  const [selected,setSelected]=useState('');
  useEffect(()=>{let alive=true;setError('');api<Model>('/market/clusters').then(data=>{if(alive){setModel(data);setSelected(data.items[0]?.symbol??'');}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[retry]);
  if(error)return <div className="panel" role="alert"><p>{error}</p><button className="text-btn" onClick={()=>setRetry(n=>n+1)}><RefreshCw size={15}/>다시 불러오기</button></div>;
  if(!model)return <div className="panel quiet-empty" role="status">기업의 재무정보를 모아 지도를 그리고 있어요. 첫 조회는 잠시 걸릴 수 있어요.</div>;
  if(!model.items.length)return <div className="panel quiet-empty">지도를 만들 재무정보가 부족해요. 잠시 후 다시 확인해주세요.<button className="text-btn" onClick={()=>setRetry(n=>n+1)}>다시 불러오기</button></div>;
  const groups=[...new Set(model.items.map(p=>p.cluster))].sort();
  const point=model.items.find(p=>p.symbol===selected)??model.items[0];
  const visible=model.items.filter(p=>group===null||p.cluster===group);
  const xs=model.items.map(p=>p.vector[0]),ys=model.items.map(p=>p.vector[2]);
  const xmin=Math.min(...xs)-.3,xmax=Math.max(...xs)+.3,ymin=Math.min(...ys)-.3,ymax=Math.max(...ys)+.3;
  const x=(value:number)=>70+(value-xmin)/(xmax-xmin)*660;
  const y=(value:number)=>360-(value-ymin)/(ymax-ymin)*300;
  return <>
    <div className="panel cluster-panel">
      <div className="section-heading"><div><h2>재무 성격이 비슷한 기업끼리</h2><p className="cluster-caption">점 하나가 기업 하나예요. 같은 색은 세 가지 재무지표가 비슷한 그룹이에요.</p></div><span className="source-badge">{model.source==='sample'?'학습용 샘플':'OpenDART 공시'}</span></div>
      <div className="cluster-legend" aria-label="군집 필터"><button className={group===null?'selected':''} onClick={()=>setGroup(null)}>전체 {model.items.length}개</button>{groups.map(id=><button key={id} className={group===id?'selected':''} onClick={()=>{setGroup(id);setSelected(model.items.find(p=>p.cluster===id)!.symbol);}}><i style={{background:colors[id]}}/>그룹 {id+1} · {model.items.filter(p=>p.cluster===id).length}개</button>)}</div>
      <div className="cluster-layout"><div className="cluster-chart"><svg viewBox="0 0 800 425" aria-label="기업 군집 지도. 가로는 순이익률, 세로는 부채비율이며 색상은 재무지표가 비슷한 그룹입니다.">
        <title>기업 재무지표 기반 군집 지도</title>
        {[0,1,2,3,4].map(i=><g key={i} className="cluster-grid"><line x1={70+i*165} y1="60" x2={70+i*165} y2="360"/><line x1="70" y1={60+i*75} x2="730" y2={60+i*75}/></g>)}
        <text x="70" y="395" className="cluster-axis">순이익률 낮음</text><text x="730" y="395" textAnchor="end" className="cluster-axis">순이익률 높음 →</text><text transform="translate(26 210) rotate(-90)" textAnchor="middle" className="cluster-axis">부채비율 높음 →</text>
        {visible.map(p=><g key={p.symbol} role="button" tabIndex={0} className="cluster-point" aria-label={`${p.name}, 그룹 ${p.cluster+1}, 순이익률 ${pct(p.profit_margin)}, 부채비율 ${pct(p.debt_ratio)}`} onClick={()=>setSelected(p.symbol)} onFocus={()=>setSelected(p.symbol)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(p.symbol);}}}><title>{p.name} · 그룹 {p.cluster+1}</title><circle cx={x(p.vector[0])} cy={y(p.vector[2])} r={selected===p.symbol?9:6} fill={colors[p.cluster]} stroke={selected===p.symbol?'#18345d':'#fff'} strokeWidth="2"/>{selected===p.symbol&&<text x={x(p.vector[0])+12} y={y(p.vector[2])-12} className="cluster-label">{p.name}</text>}</g>)}
      </svg><p className="cluster-caption">점의 위치는 비교하기 쉽도록 로그 변환·표준화했어요. 색상은 순이익률·기말자본 대비 이익률·부채비율을 함께 비교한 결과예요.</p></div>
      <aside className="cluster-selection" aria-live="polite"><span className="tag" style={{color:colors[point.cluster]}}>그룹 {point.cluster+1}</span><h3>{point.name}</h3><p>{point.sector} · {point.year} {point.statement??''}</p><dl><div><dt>순이익률</dt><dd>{pct(point.profit_margin)}</dd></div><div><dt>기말자본 대비 이익률</dt><dd>{pct(point.equity_return)}</dd></div><div><dt>부채비율</dt><dd>{pct(point.debt_ratio)}</dd></div></dl><p>순이익률은 번 돈 중 얼마나 남겼는지, 부채비율은 자기자본에 비해 빚이 얼마나 많은지를 보여줘요.</p><button className="btn secondary full" onClick={()=>onSelect(point.symbol)}>기업 상세 보기 <ArrowUpRight size={15}/></button></aside></div>
      <div className="cluster-company-list" aria-label="지도에 표시한 기업">{visible.map(p=><button key={p.symbol} aria-pressed={p.symbol===selected} onClick={()=>setSelected(p.symbol)}><i style={{background:colors[p.cluster]}}/>{p.name}</button>)}</div>
    </div>
    <p className="fineprint">기업을 비교해 보는 학습용 지도예요. 그룹 번호는 순위나 투자 등급이 아니에요. 기말자본 대비 이익률은 ROE와 다르며, 회사마다 공시 연도가 다를 수 있어요.</p>
    {model.excluded.length>0&&<details className="panel"><summary>재무정보가 부족해 제외한 기업 {model.excluded.length}개</summary>{model.excluded.map(p=><p key={p.symbol}>{p.name} · {p.reason}</p>)}</details>}
  </>;
}
