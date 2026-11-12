from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    app_name: str = '대가 API'
    frontend_url: str = 'http://localhost:5173'
    auth_mode: str = 'auto'
    supabase_url: str = ''
    supabase_anon_key: str = ''
    supabase_service_role_key: str = ''
    opendart_api_key: str = ''
    initial_capital: int = 10_000_000
    game_year: int = 2024
    stage_minutes: float = 30
    enable_debug_tools: bool = False
    stage_payments: list[int] = [500_000 + i * 100_000 for i in range(12)]
    historical_data_path: str = str(ROOT / 'backend/data/historical')
    database_path: str = str(ROOT / 'backend/data/daega.sqlite3')
    model_config = SettingsConfigDict(env_file=ROOT / '.env', env_file_encoding='utf-8', extra='ignore')

    @property
    def cloud_auth(self):
        return self.auth_mode != 'local' and bool(self.supabase_url and self.supabase_anon_key and self.supabase_service_role_key)

@lru_cache
def get_settings():
    return Settings()

settings = get_settings()

