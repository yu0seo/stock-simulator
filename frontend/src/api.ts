export type User = {id:string;nickname:string};
export type Stock = {symbol:string;name:string;sector:string;color:string;price:number;change:number;per:number|null;pbr:number|null;source:string;updated_at:string};
export type Config = {market_mode:string;auth_mode:string;financial_mode:string;initial_capital:number;game_days:number;market_open:boolean;poll_seconds:number;difficulties:Record<string,{label:string;loan:number;rate:number}>};
export type Position = {symbol:string;name:string;quantity:number;average:number;price:number;value:number;profit:number;color:string};
export type Trade = {id:string;symbol:string;side:string;quantity:number;price:number;amount:number;created_at:number};
export type Account = {difficulty:string;initial:number;cash:number;principal:number;rate:number;interest:number;rewards:number;positions:Position[];trades:Trade[];completed:string[];source:string;net_assets:number;profit:number;return_rate:number;daily_interest:number;days_left:number;status:string;started_at:number;ends_at:number;stock_value:number};
export type Lesson = {id:string;title:string;category:string;minutes:number;reward:number;text:string;question:string;options:string[]};
export type Rank = {id:string;nickname:string;rank:number;difficulty:string;return_rate:number;net_assets:number;completed:number};
export async function api<T>(path:string,body?:unknown):Promise<T>{
  const r=await fetch('/api'+path,{method:body===undefined?'GET':'POST',credentials:'include',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json().catch(()=>({detail:'서버에 연결할 수 없어요. 백엔드 실행 상태를 확인해주세요.'}));
  if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.');
  return data;
}
