"""Isolated local UI check. Never uses the user's Supabase DB."""
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.config import settings
settings.auth_mode='local'
settings.frontend_url='http://127.0.0.1:8091'
settings.stage_minutes=30
settings.enable_debug_tools=True
import uvicorn
with tempfile.TemporaryDirectory(prefix='daega-ui-') as tmp:
    settings.database_path=str(Path(tmp)/'ui.sqlite3')
    uvicorn.run('app.main:app',host='127.0.0.1',port=8091,log_level='warning')
