import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from fastapi import HTTPException
from app.core.config import settings
from app.services.store import store
from app.services.market import market
from app.services.game import accrue, summary
from app.services.catalog import DIFFICULTIES

REFRESH_SECONDS=600


class Leaderboard:
    def __init__(self):
        self.rows=[]
        self.updated_at=None
        self.until=0
        self.excluded=0
        self.error=False
        self.lock=asyncio.Lock()

    async def refresh(self):
        async with self.lock:
            if self.updated_at and time.time()<self.until: return
            source='toss' if settings.live_market else 'sample'
            accounts=await store.ranking_accounts()
            quotes=await market.quotes()
            entries=[]
            excluded=0
            required={'cash','principal','rate','interest','accrued_at','initial','rewards','positions','completed','ends_at','source','difficulty'}
            stamp=datetime.now(timezone.utc).isoformat()
            for row in accounts:
                a=row['data']
                if not isinstance(a,dict) or not required.issubset(a) or not isinstance(a['difficulty'],str) or a['difficulty'] not in DIFFICULTIES:
                    excluded+=1
                    continue
                if a['source']!=source: continue
                try:
                    a={**a}
                    accrue(a)
                    value=summary(a,quotes)
                    if not all(math.isfinite(value[k]) for k in ('return_rate','net_assets')): raise ValueError('Nonfinite ranking')
                    entries.append({'user_id':row['id'],'nickname':row['nickname'],'difficulty':a['difficulty'],'source':source,'return_rate':value['return_rate'],'net_assets':value['net_assets'],'completed':len(a['completed']),'updated_at':stamp})
                except (KeyError,TypeError,ValueError,ZeroDivisionError,AttributeError,OverflowError):
                    excluded+=1
            if settings.shared_rankings:
                if entries: await store.cloud('/rest/v1/rpc/sync_leaderboard','POST',{'p_entries':entries},admin=True)
                # shortcut: read at most 1,000 entries per league; add DB paging before larger leagues.
                rows=await store.cloud('/rest/v1/leaderboard?select=user_id,nickname,difficulty,source,return_rate,net_assets,completed,updated_at&source=eq.'+source+'&order=return_rate.desc,nickname.asc&limit=1000',admin=True)
            else: rows=entries
            self.rows=rows
            self.excluded=excluded
            self.updated_at=stamp
            self.until=time.time()+REFRESH_SECONDS
            self.error=False

    async def get(self,difficulty='all'):
        if not self.updated_at or time.time()>=self.until:
            try: await self.refresh()
            except Exception:
                self.error=True
                if not self.updated_at: raise HTTPException(502,'공용 DB 랭킹을 불러오지 못했어요. 잠시 후 다시 확인해주세요.') from None
        source='toss' if settings.live_market else 'sample'
        rows=sorted((dict(r) for r in self.rows if r['source']==source and (difficulty=='all' or r['difficulty']==difficulty)),key=lambda r:(-r['return_rate'],r['nickname'],r['user_id']))
        items=[{'id':r['user_id'],'nickname':r['nickname'],'difficulty':r['difficulty'],'return_rate':r['return_rate'],'net_assets':r['net_assets'],'completed':r['completed'],'rank':i+1} for i,r in enumerate(rows[:100])]
        return {'items':items,'source':source,'count':len(rows),'updated_at':self.updated_at,'refresh_seconds':REFRESH_SECONDS,'storage':'supabase' if settings.shared_rankings else 'sqlite','excluded':self.excluded,'stale':self.error,'formula':'(순자산 − 초기 자기자본 − 학습 보상) ÷ (초기 자기자본 + 학습 보상) × 100'}

    async def run(self):
        while True:
            delay=REFRESH_SECONDS
            try:
                await self.refresh()
                delay=max(1,self.until-time.time())
            except Exception:
                self.error=True
                logging.getLogger(__name__).warning('Leaderboard refresh failed; retaining the last successful snapshot.')
            await asyncio.sleep(delay)


leaderboard=Leaderboard()
