import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
import httpx
from fastapi import HTTPException, Request, Response
from app.core.config import settings

class Store:
    @contextmanager
    def connect(self):
        Path(settings.database_path).parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(settings.database_path, timeout=15)
        db.row_factory=sqlite3.Row
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,nickname TEXT UNIQUE,password TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS accounts(user_id TEXT PRIMARY KEY,data TEXT,version INTEGER);
        ''')
        try:
            with db:
                yield db
        finally:
            db.close()

    async def cloud(self, path, method='GET', payload=None, token=None, admin=False):
        key=settings.supabase_service_role_key if admin else settings.supabase_anon_key
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r=await client.request(method,settings.supabase_url.rstrip('/')+path,json=payload,headers={'apikey':key,'Authorization':'Bearer '+(token or key)})
            except httpx.HTTPError:
                raise HTTPException(502,'Supabase 연결을 확인해주세요.')
        if r.is_error:
            msg=r.json().get('msg',r.json().get('message','인증 또는 DB 요청에 실패했습니다.'))
            if r.status_code>=500: msg='Supabase DB 스키마와 연결 설정을 확인해주세요.'
            raise HTTPException(409 if r.status_code==409 else 400, str(msg))
        return r.json() if r.content else None

    def cookie(self,response,access,refresh=''):
        # Local HTTP development uses SameSite=lax; serve behind HTTPS with secure cookies in deployment.
        response.set_cookie('daega_session',access,httponly=True,samesite='lax',max_age=604800)
        if refresh: response.set_cookie('daega_refresh',refresh,httponly=True,samesite='lax',max_age=2592000)

    async def signup(self,email,password,nickname,response):
        if settings.cloud_auth:
            data=await self.cloud('/auth/v1/signup','POST',{'email':email,'password':password,'data':{'nickname':nickname}})
            if data.get('access_token'):
                self.cookie(response,data['access_token'],data.get('refresh_token',''))
                return {'user':{'id':data['user']['id'],'nickname':nickname},'message':'회원가입이 완료됐어요.'}
            return {'user':None,'message':'가입 확인 메일을 보냈어요. 이메일 인증 후 로그인해주세요.'}
        salt=secrets.token_hex(16)
        hashed=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
        uid=secrets.token_hex(16)
        try:
            with self.connect() as db:
                db.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,email,nickname,salt+':'+hashed))
        except sqlite3.IntegrityError:
            raise HTTPException(409,'이미 사용 중인 이메일 또는 닉네임이에요.')
        return await self.login(email,password,response)

    async def login(self,email,password,response):
        if settings.cloud_auth:
            data=await self.cloud('/auth/v1/token?grant_type=password','POST',{'email':email,'password':password})
            self.cookie(response,data['access_token'],data.get('refresh_token',''))
            return {'user':{'id':data['user']['id'],'nickname':data['user'].get('user_metadata',{}).get('nickname','투자자')},'message':'다시 만나 반가워요.'}
        with self.connect() as db:
            user=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
            salt,expected=(user['password'].split(':') if user else ('unknown',''))
            actual=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
            if not user or not hmac.compare_digest(actual,expected): raise HTTPException(401,'이메일 또는 비밀번호를 확인해주세요.')
            token=secrets.token_urlsafe(40)
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],time.time()+604800))
            self.cookie(response,token)
            return {'user':{'id':user['id'],'nickname':user['nickname']},'message':'다시 만나 반가워요.'}

    async def user(self,request:Request,response:Response):
        token=request.cookies.get('daega_session','')
        if not token: raise HTTPException(401,'먼저 로그인해주세요.')
        if settings.cloud_auth:
            try:
                data=await self.cloud('/auth/v1/user',token=token)
            except HTTPException:
                refresh=request.cookies.get('daega_refresh')
                if not refresh: raise HTTPException(401,'로그인이 만료됐어요.')
                try: d=await self.cloud('/auth/v1/token?grant_type=refresh_token','POST',{'refresh_token':refresh})
                except HTTPException: raise HTTPException(401,'다시 로그인해주세요.')
                self.cookie(response,d['access_token'],d.get('refresh_token',''))
                data=d['user']
            # Nickname comes from the immutable public profile created at signup.
            rows=await self.cloud('/rest/v1/profiles?user_id=eq.'+data['id']+'&select=nickname',admin=True)
            return {'id':data['id'],'nickname':rows[0]['nickname'] if rows else '투자자'}
        with self.connect() as db:
            u=db.execute('SELECT u.id,u.nickname FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not u: raise HTTPException(401,'다시 로그인해주세요.')
            return dict(u)

    async def logout(self,request,response):
        token=request.cookies.get('daega_session','')
        if settings.cloud_auth:
            try: await self.cloud('/auth/v1/logout','POST',token=token)
            except HTTPException: pass
        else:
            with self.connect() as db: db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie('daega_session')
        response.delete_cookie('daega_refresh')

    async def account(self,uid):
        if settings.cloud_auth:
            rows=await self.cloud('/rest/v1/accounts?user_id=eq.'+uid+'&select=data,version',admin=True)
            return (rows[0]['data'],rows[0]['version']) if rows else (None,0)
        with self.connect() as db:
            r=db.execute('SELECT data,version FROM accounts WHERE user_id=?',(uid,)).fetchone()
            return (json.loads(r['data']),r['version']) if r else (None,0)

    async def save(self,uid,data,version):
        if settings.cloud_auth:
            ok=await self.cloud('/rest/v1/rpc/save_account','POST',{'p_user_id':uid,'p_data':data,'p_version':version},admin=True)
            if not ok: raise HTTPException(409,'다른 요청이 먼저 처리됐어요. 새로고침 후 다시 시도해주세요.')
            return
        with self.connect() as db:
            if version==0:
                try: db.execute('INSERT INTO accounts VALUES(?,?,1)',(uid,json.dumps(data)))
                except sqlite3.IntegrityError: raise HTTPException(409,'이미 시작한 계정이에요. 새로고침해주세요.')
            else:
                r=db.execute('UPDATE accounts SET data=?,version=version+1 WHERE user_id=? AND version=?',(json.dumps(data),uid,version))
                if not r.rowcount: raise HTTPException(409,'다른 요청이 먼저 처리됐어요. 새로고침 후 다시 시도해주세요.')

    async def accounts(self):
        if settings.cloud_auth:
            rows=await self.cloud('/rest/v1/accounts?select=user_id,data,profiles(nickname)&limit=1000',admin=True)
            return [{'id':r['user_id'],'nickname':r['profiles']['nickname'],'data':r['data']} for r in rows]
        with self.connect() as db:
            return [{'id':r['user_id'],'nickname':r['nickname'],'data':json.loads(r['data'])} for r in db.execute('SELECT a.*,u.nickname FROM accounts a JOIN users u ON u.id=a.user_id')]

store=Store()
