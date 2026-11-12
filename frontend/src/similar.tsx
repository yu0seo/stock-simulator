import {useEffect,useState} from 'react';
import {ArrowRight,ChartNoAxesCombined,Target} from 'lucide-react';
import {api,ClusterResult,Stock} from './api';

const colors=['#557edf','#64a68e','#b08ad1','#d49c66','#d37c91'];
const groups=(i:number)=>'군집 '+String(i+1);

export function SimilarCompanies({stocks,date,onStock}:{stocks:Stock[];date:string;onStock:(s:string)=>void}){
  const [compact,setCompact]=useState(()=>window.innerWidth<=760);
  useEffect(()=>{const query=window.matchMedia('(max-width:760px)');const change=()=>setCompact(query.matches);query.addEventListener('change',change);return()=>query.removeEventListener('change',change);},[]);
  const [selected,setSelected]=useState(stocks[0]?.symbol??'005930');
  const [data,setData]=useState<ClusterResult>();
  const [loading,setLoading]=useState(true),[error,setError]=useState('');
  const [hover,setHover]=useState<string|null>(null),[filter,setFilter]=useState<number|null>(null);
  useEffect(()=>{let alive=true;setLoading(true);setError('');api<ClusterResult>('/market/clusters?symbol='+encodeURIComponent(selected)).then(d=>{if(alive)setData(d);}).catch(e=>{if(alive)setError(e.message);}).finally(()=>{if(alive)setLoading(false);});return()=>{alive=false;};},[selected,date]);
  const node=data?.nodes.find(n=>n.symbol===selected),active=data?.nodes.find(n=>n.symbol===(hover??selected));
  const W=compact?600:900,H=compact?520:490,L=compact?45:65,R=compact?25:65,T=compact?32:45,B=50;
  const xs=data?.nodes.map(n=>n.x)??[0],ys=data?.nodes.map(n=>n.y)??[0];
  const minX=Math.min(...xs)-.45,maxX=Math.max(...xs)+.45,minY=Math.min(...ys)-.45,maxY=Math.max(...ys)+.45;
  const x=(v:number)=>L+(v-minX)/(maxX-minX)*(W-L-R),y=(v:number)=>H-B-(v-minY)/(maxY-minY)*(H-T-B);
  return <div className="similar-content">
    <div className="cluster-intro"><span className="cluster-symbol"><ChartNoAxesCombined size={23}/></span><div><h2>재무 특성이 닮은 기업을 찾아보세요</h2><p>{date}까지 공개된 재무제표로 규모·부채부담·수익성을 비교해요.</p></div><span className="tag">{data?.nodes.length??'—'} / {data?.total??stocks.length}개 기업 분석</span></div>
    <section className="panel cluster-panel"><div className="cluster-controls"><label>비교 기준 기업<select aria-label="비교 기준 기업" value={selected} onChange={e=>{setSelected(e.target.value);setFilter(null);}}>{stocks.map(s=><option key={s.symbol} value={s.symbol}>{s.name} · {s.symbol}</option>)}</select></label><div className="cluster-legend"><button className={filter===null?'active':''} onClick={()=>setFilter(null)}>전체</button>{data?.clusters.map(c=><button key={c.id} className={filter===c.id?'active':''} onClick={()=>setFilter(filter===c.id?null:c.id)}><i style={{background:colors[c.id]}}/>{groups(c.id)}<small>{c.count}</small></button>)}</div></div>
      {error?<p className="form-error" role="alert">{error}</p>:!data?<p className="quiet-empty">기업의 재무 특성을 비교하고 있어요.</p>:<>
        <div className={'cluster-map '+(loading?'is-loading':'')} aria-busy={loading}>
          <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label="유사 기업 군집 지도">
            <rect x={L} y={T} width={W-L-R} height={H-T-B} rx="12" fill="#fafcff"/>
            {[0,.25,.5,.75,1].map(v=><g key={v}><line x1={L+(W-L-R)*v} x2={L+(W-L-R)*v} y1={T} y2={H-B} stroke="#e7edf8" strokeDasharray="3 5"/><line x1={L} x2={W-R} y1={T+(H-T-B)*v} y2={T+(H-T-B)*v} stroke="#e7edf8" strokeDasharray="3 5"/></g>)}
            {data.clusters.filter(c=>filter===null||filter===c.id).map(c=>{const members=data.nodes.filter(n=>n.cluster===c.id);const cx=members.reduce((a,n)=>a+x(n.x),0)/members.length,cy=members.reduce((a,n)=>a+y(n.y),0)/members.length;const rx=Math.max(33,Math.sqrt(members.reduce((a,n)=>a+(x(n.x)-cx)**2,0)/members.length)*1.6),ry=Math.max(28,Math.sqrt(members.reduce((a,n)=>a+(y(n.y)-cy)**2,0)/members.length)*1.6);return <ellipse key={c.id} cx={cx} cy={cy} rx={Math.min(rx,180)} ry={Math.min(ry,140)} fill={colors[c.id]+'0b'} stroke={colors[c.id]+'25'} strokeDasharray="5 5"/>;})}
            {data.nodes.map(n=><g key={n.symbol} role="button" tabIndex={0} aria-label={`${n.name}, ${groups(n.cluster)}, 비교 기준으로 선택`} className="cluster-node" opacity={filter===null||filter===n.cluster?1:.12} onMouseEnter={()=>setHover(n.symbol)} onMouseLeave={()=>setHover(null)} onFocus={()=>setHover(n.symbol)} onBlur={()=>setHover(null)} onClick={()=>setSelected(n.symbol)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(n.symbol);}}}><title>{n.name} · {groups(n.cluster)} · 공시 {n.published_at}</title>{n.symbol===selected&&<circle cx={x(n.x)} cy={y(n.y)} r="17" fill={colors[n.cluster]+'16'} stroke={colors[n.cluster]} strokeWidth="1.3"/>}<circle cx={x(n.x)} cy={y(n.y)} r={n.symbol===selected?8:6} fill={colors[n.cluster]} stroke="white" strokeWidth="2"/></g>)}
            {active&&<g pointerEvents="none"><rect x={Math.min(W-177,Math.max(10,x(active.x)-78))} y={Math.max(5,y(active.y)-44)} width="156" height="29" rx="6" fill="white" stroke={colors[active.cluster]+'66'}/><text x={Math.min(W-99,Math.max(88,x(active.x)))} y={Math.max(24,y(active.y)-25)} textAnchor="middle" fontSize="12" fontWeight="600" fill="#527095">{active.name}</text></g>}
            <text x={W/2} y={H-10} textAnchor="middle" fontSize="11" fill="#8295b2">재무 특성 축 1 · {(data.explained[0]*100).toFixed(1)}%</text><text transform={`translate(18 ${H/2}) rotate(-90)`} textAnchor="middle" fontSize="11" fill="#8295b2">재무 특성 축 2 · {(data.explained[1]*100).toFixed(1)}%</text>
          </svg>
        </div>
        <p className="map-hint">점을 선택하면 기준 기업이 바뀌어요. 같은 색은 같은 군집이에요. 지도는 3개 재무 특성을 2개 축으로 요약한 모습이에요.</p>
        {data.message&&<div className="info-box">{data.message}</div>}
        {node&&<div className="selected-company"><div><span className="eyebrow">SELECTED COMPANY</span><h3><i style={{background:colors[node.cluster]}}/>{node.name}<span className="tag">{groups(node.cluster)}</span></h3><p>실적 {node.period_end} · 공시 {node.published_at} · {node.statement==='CFS'?'연결':'별도'}</p></div><dl><div><dt>총자산</dt><dd>{(node.raw[0]/1e12).toFixed(1)}조 원</dd></div><div><dt>부채 / 자산</dt><dd>{node.raw[1].toFixed(1)}%</dd></div><div><dt>연환산 이익 / 기말자산</dt><dd>{node.raw[2].toFixed(1)}%</dd></div></dl><button className="text-btn" onClick={()=>onStock(selected)}>종목 상세<ArrowRight size={14}/></button></div>}
        <details className="cluster-method"><summary>군집 기준과 사용 자료 확인</summary><p>{data.method}</p><p>총자산은 로그 변환, 자산 대비 이익은 극단값의 영향을 줄이는 변환 후 표준화해요. 순이익의 연환산은 비교를 위한 계산이며 미래 이익 예측이나 평균자산 기준 ROA가 아니에요. 기업별 실적 기간과 연결·별도 기준이 다를 수 있어요.</p><div className="cluster-source-list">{data.nodes.map(n=><a key={n.symbol} href={'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+n.receipt} target="_blank" rel="noreferrer">{n.name} · 실적 {n.period_end} / 공개 {n.published_at} ↗</a>)}</div></details>
      </>}
    </section>
    {data&&<section className="panel"><div className="section-heading"><h2><Target size={18}/> {stocks.find(s=>s.symbol===selected)?.name}와 비교할 기업</h2><span className="muted">3개 지표의 거리순</span></div>{data.recommendations.length?<div className="similar-grid">{data.recommendations.map(n=><article className="similar-card" key={n.symbol}><div><span className="cluster-dot" style={{background:colors[n.cluster]}}/><strong>{n.name}</strong><span className="tag">{n.same_cluster?'같은 군집':groups(n.cluster)}</span></div><small>{n.sector} · 재무 거리 {n.distance.toFixed(2)}</small><p>실적 {n.period_end}<br/>공개 {n.published_at}</p><div className="similar-card-actions"><button className="text-btn" onClick={()=>setSelected(n.symbol)}>지도에서 비교</button><button className="text-btn" onClick={()=>onStock(n.symbol)}>종목 상세<ArrowRight size={13}/></button></div></article>)}</div>:<p className="quiet-empty">현재 공개 자료로 비교 가능한 기업이 부족해요.</p>}<p className="fineprint">재무 거리 0에 가까울수록 사용한 지표가 비슷해요. 유사한 기업이 같은 수익률을 보장하지는 않아요.</p></section>}
    {data&&data.excluded.length>0&&<section className="panel excluded-companies"><h3>현재 비교 자료가 부족한 기업 · {data.excluded.length}개</h3><p>50개 종목 모두를 확인하되, 공개된 지표가 부족하면 임의로 군집에 넣지 않아요. 게임 날짜가 진행되며 자료가 공개되면 분석 대상에 포함돼요.</p><div>{data.excluded.map(n=><button key={n.symbol} title={n.reason} onClick={()=>onStock(n.symbol)}>{n.name}<ArrowRight size={12}/></button>)}</div></section>}
  </div>;
}
