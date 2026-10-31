"""Local contact preview: isolated SQLite/outbox, actual configured SMTP, port 8102.

This deliberately does not use the normal development Supabase database or start
any agent, billing, ingestion, telephony, or other background workers.
"""
from contextlib import asynccontextmanager, suppress
import asyncio
import logging
import os
from pathlib import Path
import secrets
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(os.environ.get('CONTACT_DATA_DIR', ROOT / 'data' / 'mainpage-contact'))
HOSTED = os.environ.get('CONTACT_HOSTED') == 'true'


def main():
    FOLDER.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_file = FOLDER / '.encryption-secret'
    if not key_file.exists():
        try:
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as file:
                file.write(secrets.token_urlsafe(48))
    # Read SMTP privately from the existing .env; never print config or exceptions.
    if HOSTED:
        import json
        values = json.loads(Path(os.environ['CONTACT_SMTP_FILE']).read_text())
    else:
        values = dotenv_values(ROOT / '.env')
    for name in ('SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM', 'SMTP_SECURITY'):
        if values.get(name):
            os.environ[name] = values[name]
    os.environ.update({
        'APP_ENV': 'contact' if HOSTED else 'development', 'DATABASE_URL': 'sqlite:///' + str(FOLDER / 'enquiries.db'),
        'SUPABASE_DB_PASSWORD': '', 'DATA_DIR': str(FOLDER), 'APP_SECRET': key_file.read_text(),
        'CIPHER_KEY_PROVIDER': 'local', 'CIPHER_KEYS_JSON': '', 'CIPHER_ACTIVE_KEY_ID': 'app-v1',
        'REDIS_URL': os.environ.get('CONTACT_REDIS_URL', ''),
    })
    sys.path.insert(0, str(ROOT / 'services' / 'control'))
    from fastapi import FastAPI
    from studio.db import engine
    from studio.mail_outbox import process_outbox
    from studio.models import EmailOutbox
    from studio.public_contact import router
    from studio.config import settings
    import uvicorn

    if not settings.smtp_host:
        raise SystemExit('SMTP is not configured. Add the existing SMTP settings before running this preview.')
    EmailOutbox.__table__.create(engine, checkfirst=True)

    async def deliver():
        while True:
            try:
                await asyncio.to_thread(process_outbox, 4)
            except Exception:
                logging.getLogger(__name__).warning('Contact outbox pass failed; retrying without logging private data')
            await asyncio.sleep(3)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(deliver())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    if HOSTED:
        from fastapi.responses import JSONResponse

        @app.middleware('http')
        async def trusted_site(request, call_next):
            if request.url.path == '/v1/public/contact' and request.headers.get('origin') not in {
                'https://phirmy.com', 'https://www.phirmy.com'
            }:
                return JSONResponse({'detail': 'Use the Phirmy contact page.'}, status_code=403)
            return await call_next(request)

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    app.include_router(router)
    uvicorn.run(app, host='127.0.0.1', port=8102, proxy_headers=HOSTED, forwarded_allow_ips='127.0.0.1', access_log=False)


if __name__ == '__main__':
    main()
