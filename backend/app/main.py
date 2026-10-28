from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pathlib import Path
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422,content={'detail':'입력값을 확인해주세요. 닉네임은 한글·영문·숫자·밑줄 2–12자, 비밀번호는 8자 이상이어야 해요.'})

# Same-origin browser requests only for cookie-authenticated mutations.
@app.middleware('http')
async def protect_origin(request,call_next):
    origin=request.headers.get('origin')
    allowed={settings.frontend_url,'http://localhost:5173','http://127.0.0.1:5173','http://localhost:8000','http://127.0.0.1:8000'}
    if request.method in ('POST','PUT','PATCH','DELETE') and origin and origin not in allowed:
        return JSONResponse(status_code=403,content={'detail':'허용되지 않은 요청 출처입니다.'})
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    return response

dist=Path(__file__).resolve().parents[2]/'dist'
if dist.exists():
    app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')

