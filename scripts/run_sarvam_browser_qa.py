"""Isolated disposable SQLite browser QA server; never loads real provider keys."""
import runpy
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'services/control'))
# Reuse the project's isolated SQLite + cleared-provider QA environment.
runpy.run_path(str(root/'tests/conftest.py'))
from studio.config import settings
settings.app_env='development'
settings.app_origin='http://127.0.0.1:3100'
settings.public_api_origin='http://127.0.0.1:8100'
settings.voice_provider='sarvam'
settings.worker_enabled=False
assert settings.database_url.startswith('sqlite:') and not settings.sarvam_api_key
# Only the isolated test host can satisfy the synthetic ownership boundary.
from studio import origin_ownership
class LoopbackProof:
    async def verify(self, origin, method, token):
        return origin == 'http://127.0.0.1:3201' and method == 'dns'
origin_ownership.provider = LoopbackProof()
import uvicorn
uvicorn.run('studio.main:app',host='127.0.0.1',port=8100,log_level='warning')
