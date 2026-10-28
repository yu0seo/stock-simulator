from fastapi import APIRouter

from app.api.routes import health
from app.api.routes import platform


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(platform.router)

