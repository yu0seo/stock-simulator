export type User = {id:string;nickname:string};
export type Rules = {year:number;initial:number;stage_seconds:number;payments:number[];dataset_id:string};
export type Stock = {symbol:string;name:string;sector:string;color:string;price:number;change:number;price_date:string;tradable:boolean;liquidatable:boolean};
export type Config = {auth_mode:string;year:number;initial_capital:number;stage_seconds:number;payments:number[];debug_tools:boolean;stock_count:number;dataset:{ready:boolean;message:string|null;financial_reports:number}};
export type Position = {symbol:string;name:string;color:string;quantity:number;average:number;price:number;value:number;profit:number};
export type Trade = {id:string;symbol:string;side:string;quantity:number;price:number;amount:number;date:string;stage:number;settlement:boolean};
export type Account = {id:string;rules:Rules;rules_id:string;stage:number;phase:'strategy'|'ready'|'running'|'paused'|'settlement'|'bankrupt'|'completed';date:string;cash:number;initial:number;positions:Position[];trades:Trade[];payments:{stage:number;amount:number;date:string}[];strategies:Record<string,{notes:string;watchlist:string[]}>;completed:string[];stock_value:number;net_assets:number;profit:number;return_rate:number;paid:number;current_payment:number;remaining_seconds:number;elapsed:number;cleared:number;failure_reason:string|null;debug_used?:boolean};
export type Snapshot = {account:Account|null;stocks:Stock[];date:string;legacy_saved:boolean;history_count:number};
export type Lesson = {id:string;title:string;category:string;minutes:number;text:string;question:string;options:string[]};
export type Rank = {id:string;nickname:string;rank:number;cleared:number;net_assets:number;return_rate:number;phase:string};
export type Report = {title:string;receipt:string;published_at:string;period_end:string;year:number;report_code:string;statement:string;url:string;rows:{account_nm:string;account_id:string;sj_div:string;thstrm_amount:string;thstrm_add_amount?:string;currency?:string}[]};
export type Financial = {source:string;as_of:string;report:Report|null;message:string|null;available_reports:{receipt:string;title:string;published_at:string;period_end:string}[]};
export type ClusterNode = {symbol:string;name:string;sector:string;cluster:number;x:number;y:number;raw:number[];period_end:string;published_at:string;statement:string;receipt:string};
export type ClusterResult = {as_of:string;nodes:ClusterNode[];excluded:{symbol:string;name:string;reason:string}[];clusters:{id:number;count:number}[];recommendations:(ClusterNode&{distance:number;same_cluster:boolean})[];selected:string;features:string[];explained:number[];total:number;message:string|null;method?:string};
export async function api<T>(path:string,body?:unknown):Promise<T>{
  const r=await fetch('/api'+path,{method:body===undefined?'GET':'POST',credentials:'include',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json().catch(()=>({detail:'서버에 연결할 수 없어요. 실행 상태를 확인해주세요.'}));
  if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'입력값과 연결 상태를 확인해주세요.');
  return data;
}
