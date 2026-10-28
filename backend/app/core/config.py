from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    app_name: str = '대가 API'
    frontend_url: str = 'http://localhost:5173'
    data_mode: str = 'auto'
    auth_mode: str = 'auto'
    supabase_url: str = ''
    supabase_anon_key: str = ''
    supabase_service_role_key: str = ''
    toss_client_id: str = ''
    toss_client_secret: str = ''
    toss_base_url: str = 'https://openapi.tossinvest.com'
    opendart_api_key: str = ''
    dart_business_year: str = ''
    initial_capital: int = 10_000_000
    game_days: int = 90
    database_path: str = str(ROOT / 'backend/data/daega.sqlite3')
    model_config = SettingsConfigDict(env_file=ROOT / '.env', env_file_encoding='utf-8', extra='ignore')

    @property
    def live_market(self):
        return self.data_mode != 'demo' and bool(self.toss_client_id and self.toss_client_secret)

    @property
    def cloud_auth(self):
        return self.auth_mode != 'local' and bool(self.supabase_url and self.supabase_anon_key and self.supabase_service_role_key)

@lru_cache
def get_settings():
    return Settings()

settings = get_settings()

