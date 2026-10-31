from contextlib import asynccontextmanager, suppress
import asyncio
import logging
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text, select
from .config import settings
from .db import Base, engine, session_scope
from . import models
from . import widget_frame_cache  # Install transaction/bulk invalidation guards.
from .auth_routes import router as auth_router
from .core_routes import router as core_router
from .operations_routes import router as operations_router
from .chat_routes import router as chat_router
from .widget_live import router as widget_live_router
from .agent_deletion import router as agent_deletion_router
from .media import router as media_router
from .carrier import router as carrier_router
from .preview_routes import router as preview_router
from .account_routes import router as account_router
from .resource_routes import router as resource_router
from .connectors import router as connector_router
from .payment_routes import router as payment_router
from .http_tools import router as http_tool_router
from .model_routes import router as model_router
from .twilio_routes import router as twilio_router
from .identity_routes import router as identity_router
from .notification_routes import router as notification_router
from .contact_routes import router as contact_router
from .public_contact import router as public_contact_router
from .number_provisioning import router as number_provisioning_router
from .scheduling import router as scheduling_router
from .website_routes import router as website_router
from .scheduling_oauth import router as scheduling_oauth_router
from .workers import worker_loop, browser_session_maintenance
from .widget_protection import router as widget_protection_router
from .widget_email import router as widget_email_router
from .key_rotation import router as key_rotation_router,install_rotation_guard
from .billing_routes import router as billing_router
from .refund_routes import router as refund_router
from .billing_subscriptions import router as subscription_router
from .transfer_routes import router as transfer_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
SCHEMA_REVISION = '2026-10-27-call-transfers'


def initialize_database():
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS voice_studio"))
    Base.metadata.create_all(engine)
    schema = "voice_studio" if engine.dialect.name == "postgresql" else None
    prefix = "voice_studio." if schema else ""
    with engine.begin() as connection:
        workspace_columns = {column['name'] for column in inspect(connection).get_columns('workspaces', schema=schema)}
        if 'free_allowance_user_id' not in workspace_columns:
            connection.execute(text(f'ALTER TABLE {prefix}workspaces ADD COLUMN free_allowance_user_id VARCHAR(36) REFERENCES {prefix}users(id)'))
        allowance_index = next(index.name for index in models.Workspace.__table__.indexes if 'free_allowance_user_id' in index.columns)
        connection.execute(text(f'CREATE INDEX IF NOT EXISTS {allowance_index} ON {prefix}workspaces (free_allowance_user_id)'))
        # Preserve an original owner independently of later membership changes.
        connection.execute(text(f'''UPDATE {prefix}workspaces SET free_allowance_user_id =
            (SELECT m.user_id FROM {prefix}memberships m WHERE m.workspace_id = {prefix}workspaces.id AND m.role = 'owner'
             ORDER BY m.created_at, m.id LIMIT 1) WHERE free_allowance_user_id IS NULL'''))
        if schema:
            connection.execute(text('''CREATE OR REPLACE FUNCTION voice_studio.retain_free_allowance_owner()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                IF OLD.free_allowance_user_id IS NOT NULL AND NEW.free_allowance_user_id IS DISTINCT FROM OLD.free_allowance_user_id
                THEN RAISE EXCEPTION 'free allowance owner is immutable'; END IF; RETURN NEW; END; $$'''))
            connection.execute(text('DROP TRIGGER IF EXISTS retain_free_allowance_owner ON voice_studio.workspaces'))
            connection.execute(text('''CREATE TRIGGER retain_free_allowance_owner BEFORE UPDATE ON voice_studio.workspaces
                FOR EACH ROW EXECUTE FUNCTION voice_studio.retain_free_allowance_owner()'''))
        else:
            connection.execute(text('''CREATE TRIGGER IF NOT EXISTS retain_free_allowance_owner BEFORE UPDATE ON workspaces
                WHEN OLD.free_allowance_user_id IS NOT NULL AND NEW.free_allowance_user_id IS NOT OLD.free_allowance_user_id
                BEGIN SELECT RAISE(ABORT, 'free allowance owner is immutable'); END'''))
        order_columns={column['name'] for column in inspect(connection).get_columns('payment_orders',schema=schema)}
        for name,datatype in [('net_minor','INTEGER'),('quote_hash','VARCHAR(64)'),('encrypted_snapshot','TEXT'),
                              ('reversed_net_minor','INTEGER NOT NULL DEFAULT 0'),('refunded_net_minor','INTEGER NOT NULL DEFAULT 0'),
                              ('refunded_gross_minor','INTEGER NOT NULL DEFAULT 0'),
                              ('captured_at','TIMESTAMP WITH TIME ZONE' if schema else 'DATETIME')]:
            if name not in order_columns:connection.execute(text(f'ALTER TABLE {prefix}payment_orders ADD COLUMN {name} {datatype}'))
        subscription_columns={column['name'] for column in inspect(connection).get_columns('workspace_subscriptions',schema=schema)}
        if 'billing_blocked' not in subscription_columns:
            connection.execute(text(f'ALTER TABLE {prefix}workspace_subscriptions ADD COLUMN billing_blocked BOOLEAN NOT NULL DEFAULT FALSE'))
        if 'maintenance_at' not in subscription_columns:
            datatype='TIMESTAMP WITH TIME ZONE' if schema else 'DATETIME'
            connection.execute(text(f'ALTER TABLE {prefix}workspace_subscriptions ADD COLUMN maintenance_at {datatype}'))
        cost_columns={column['name'] for column in inspect(connection).get_columns('call_cost_records',schema=schema)}
        if 'model' not in cost_columns:connection.execute(text(f'ALTER TABLE {prefix}call_cost_records ADD COLUMN model VARCHAR(160)'))
        key_columns = {column['name'] for column in inspect(connection).get_columns('api_keys', schema=schema)}
        for column in ['expires_at', 'last_used_at']:
            if column not in key_columns:
                datatype = 'TIMESTAMP WITH TIME ZONE' if schema else 'DATETIME'
                connection.execute(text(f'ALTER TABLE {prefix}api_keys ADD COLUMN {column} {datatype}'))
        if 'requests_per_minute' not in key_columns:
            connection.execute(text(f'ALTER TABLE {prefix}api_keys ADD COLUMN requests_per_minute INTEGER NOT NULL DEFAULT 60'))
        campaign_columns={x['name'] for x in inspect(connection).get_columns('campaigns',schema=schema)}
        if 'policy' not in campaign_columns:
            connection.execute(text(f"ALTER TABLE {prefix}campaigns ADD COLUMN policy JSON NOT NULL DEFAULT '{{}}'"))
        job_columns = {x["name"] for x in inspect(connection).get_columns("jobs", schema=schema)}
        if 'lease_token' not in job_columns:
            connection.execute(text(f'ALTER TABLE {prefix}jobs ADD COLUMN lease_token VARCHAR(36)'))
        if "available_at" not in job_columns:
            connection.execute(text(f"ALTER TABLE {prefix}jobs ADD COLUMN available_at " + ("TIMESTAMP WITH TIME ZONE" if schema else "DATETIME")))
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_jobs_available_at ON {prefix}jobs (available_at)"))
        connection.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_number_provider_e164 ON {prefix}phone_numbers (provider, e164)"))
        connection.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_calls_provider_call_id ON {prefix}calls (provider_call_id)"))
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            # Supabase clients never access this backend-owned schema directly.
            for role in ["PUBLIC", "anon", "authenticated"]:
                if role == "PUBLIC" or connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).scalar():
                    connection.execute(text(f"REVOKE ALL ON SCHEMA voice_studio FROM {role}"))
                    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA voice_studio FROM {role}"))
            connection.execute(text("""CREATE OR REPLACE FUNCTION voice_studio.reject_record_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append-only record'; END; $$"""))
            for table in ["ledger_entries", "agent_versions", "audit_events",'http_tool_versions','cipher_rotation_audit',
                          'plan_catalog_snapshots','tariff_snapshots','meter_events','call_cost_records','billing_financial_events','billing_invoices','legal_policy_snapshots','legal_acceptances']:
                connection.execute(text(f"DROP TRIGGER IF EXISTS immutable_record ON voice_studio.{table}"))
                connection.execute(text(f"CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON voice_studio.{table} FOR EACH ROW EXECUTE FUNCTION voice_studio.reject_record_mutation()"))
    # Additive migration for the first local implementation. Production migrations are separate.
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            columns = {x["name"] for x in inspect(connection).get_columns("knowledge_sources")}
            if "raw_object_key" not in columns:
                connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN raw_object_key TEXT"))
            for table in ["ledger_entries", "agent_versions", "audit_events",'http_tool_versions','cipher_rotation_audit',
                          'plan_catalog_snapshots','tariff_snapshots','meter_events','call_cost_records','billing_financial_events','billing_invoices','legal_policy_snapshots','legal_acceptances']:
                for action in ["UPDATE", "DELETE"]:
                    connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only record'); END"))
    # Published versions remain append-only except during an owner-authorized purge job.
    with engine.begin() as connection:
        if engine.dialect.name == 'postgresql':
            connection.execute(text("""CREATE OR REPLACE FUNCTION voice_studio.authorized_agent_version_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF EXISTS (SELECT 1 FROM voice_studio.jobs j JOIN voice_studio.agents a ON a.id=OLD.agent_id AND a.workspace_id=OLD.workspace_id
                WHERE j.workspace_id=OLD.workspace_id AND j.kind='agent_delete' AND j.state='running'
                AND j.payload->>'agent_id'=OLD.agent_id AND a.archived=true) THEN RETURN OLD; END IF;
              RAISE EXCEPTION 'append-only record';
            END; $$"""))
            connection.execute(text('DROP TRIGGER IF EXISTS immutable_record ON voice_studio.agent_versions'))
            connection.execute(text('CREATE TRIGGER immutable_record BEFORE UPDATE ON voice_studio.agent_versions FOR EACH ROW EXECUTE FUNCTION voice_studio.reject_record_mutation()'))
            connection.execute(text('DROP TRIGGER IF EXISTS immutable_agent_versions_delete ON voice_studio.agent_versions'))
            connection.execute(text('CREATE TRIGGER immutable_agent_versions_delete BEFORE DELETE ON voice_studio.agent_versions FOR EACH ROW EXECUTE FUNCTION voice_studio.authorized_agent_version_delete()'))
        else:
            connection.execute(text('DROP TRIGGER IF EXISTS immutable_agent_versions_delete'))
            connection.execute(text("""CREATE TRIGGER immutable_agent_versions_delete BEFORE DELETE ON agent_versions
              WHEN NOT EXISTS(SELECT 1 FROM jobs j JOIN agents a ON a.id=OLD.agent_id AND a.workspace_id=OLD.workspace_id
                WHERE j.workspace_id=OLD.workspace_id AND j.kind='agent_delete' AND j.state='running'
                AND json_extract(j.payload,'$.agent_id')=OLD.agent_id AND a.archived=1)
              BEGIN SELECT RAISE(ABORT,'append-only record'); END"""))
    with engine.begin() as connection:install_rotation_guard(connection)
    with session_scope(write=True) as db:
        if not db.scalar(select(models.SchemaMigration.id).where(models.SchemaMigration.revision == SCHEMA_REVISION)):
            db.add(models.SchemaMigration(revision=SCHEMA_REVISION))


def verify_database_schema():
    schema = 'voice_studio' if engine.dialect.name == 'postgresql' else None
    with engine.connect() as connection:
        actual = set(inspect(connection).get_table_names(schema=schema))
        required = {table.name for table in Base.metadata.tables.values()}
        if not required.issubset(actual):
            raise RuntimeError('Database migration is required before starting this release')
        if 'free_allowance_user_id' not in {column['name'] for column in inspect(connection).get_columns('workspaces',schema=schema)}:
            raise RuntimeError('Database migration is required before starting this release')
        if 'lease_token' not in {column['name'] for column in inspect(connection).get_columns('jobs',schema=schema)}:
            raise RuntimeError('Database migration is required before starting this release')
        if 'model' not in {column['name'] for column in inspect(connection).get_columns('call_cost_records',schema=schema)}:
            raise RuntimeError('Database migration is required before starting this release')
        if not {'expires_at', 'last_used_at', 'requests_per_minute'}.issubset(
                {column['name'] for column in inspect(connection).get_columns('api_keys', schema=schema)}):
            raise RuntimeError('Database migration is required before starting this release')
        if not connection.execute(select(models.SchemaMigration.id).where(models.SchemaMigration.revision == SCHEMA_REVISION)).scalar():
            raise RuntimeError('Database schema revision does not match this release')


def create_app(start_worker=True):
    @asynccontextmanager
    async def lifespan(app):
        if settings.app_env == 'production':
            verify_database_schema()
        else:
            initialize_database()
        from .key_provider import warm_active_key
        await asyncio.wait_for(asyncio.to_thread(warm_active_key),15)
        stop = asyncio.Event()
        task = asyncio.create_task(worker_loop(stop)) if start_worker and settings.worker_enabled else None
        async def clean_browser_sessions():
            while not stop.is_set():
                try:
                    await asyncio.to_thread(browser_session_maintenance)
                except Exception:
                    logging.exception('Browser session maintenance failed')
                try:await asyncio.wait_for(stop.wait(),timeout=60)
                except asyncio.TimeoutError:pass
        browser_task=asyncio.create_task(clean_browser_sessions()) if start_worker and not settings.worker_enabled else None
        yield
        stop.set()
        for running in (task,browser_task):
            if running:
                running.cancel()
                with suppress(asyncio.CancelledError):await running

    app = FastAPI(title="Voice Studio API", version="0.1.0", lifespan=lifespan, docs_url=None, openapi_url=None, redoc_url=None)
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    app.add_middleware(ProxyHeadersMiddleware,
                       trusted_hosts=[ip.strip() for ip in settings.trusted_proxy_ips.split(',') if ip.strip()])
    app.add_middleware(CORSMiddleware, allow_origins=[settings.app_origin, settings.app_origin.replace("localhost", "127.0.0.1")], allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-CSRF-Token", "X-API-Key", "Idempotency-Key", "Authorization"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/v1/") else "no-cache"
        return response

    @app.middleware("http")
    async def public_widget_cors(request: Request, call_next):
        if not request.url.path.startswith("/v1/public/"):
            return await call_next(request)
        origin = request.headers.get("origin", "")
        if request.method == "OPTIONS":
            response = JSONResponse(content={}, status_code=200)
        else:
            response = await call_next(request)
        # Public handlers independently enforce the installation origin and token binding.
        # These requests never authenticate through dashboard cookies.
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Max-Age"] = "300"
            response.headers["Vary"] = "Origin"
            if "Access-Control-Allow-Credentials" in response.headers:
                del response.headers["Access-Control-Allow-Credentials"]
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get('/readyz', include_in_schema=False)
    async def ready():
        from .readiness import readiness
        payload, status = await readiness()
        return JSONResponse(payload, status_code=status)

    def docs_access(request, db):
        if settings.app_env == 'production':
            from .security import active_user
            from .account_policy import require_verified
            require_verified(db, active_user(request, db, csrf=False))

    from .security import db_dependency

    @app.get('/openapi.json', include_in_schema=False)
    def openapi_document(request: Request, db=Depends(db_dependency, scope='function')):
        docs_access(request, db)
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    def api_docs(request: Request, db=Depends(db_dependency, scope='function')):
        docs_access(request, db)
        import base64, secrets
        from fastapi.responses import HTMLResponse
        from fastapi.openapi.docs import get_swagger_ui_html
        nonce = base64.b64encode(secrets.token_bytes(24)).decode()
        html = get_swagger_ui_html(openapi_url='openapi.json', title='Voice Studio API').body.decode()
        return HTMLResponse(html.replace('<script', '<script nonce="'+nonce+'"'), headers={
            'Content-Security-Policy': "default-src 'none'; script-src 'nonce-"+nonce+"' 'strict-dynamic'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            'Cache-Control':'private, no-store'})

    for router in [scheduling_oauth_router, website_router, auth_router, identity_router, notification_router, contact_router, public_contact_router, number_provisioning_router, scheduling_router, core_router, operations_router, chat_router, widget_live_router, agent_deletion_router, media_router, carrier_router, preview_router, account_router, resource_router, connector_router, payment_router,http_tool_router,model_router,twilio_router]:
        app.include_router(router)
    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes,
                             description='Workspace-scoped agent APIs. Dashboard access uses short-lived JWT cookies, rotating refresh cookies and CSRF protection. Server integrations use scoped X-API-Key credentials. Public widgets use origin-bound session capabilities.',
                             servers=[{'url': '/backend', 'description': 'Web application proxy'}, {'url': '/', 'description': 'Direct API server'}])
        schema.setdefault('components', {}).setdefault('securitySchemes', {}).update({
            'WorkspaceKey': {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'},
            'DashboardSession': {'type': 'apiKey', 'in': 'cookie', 'name': 'studio_session'},
            'WidgetCapability': {'type': 'http', 'scheme': 'bearer', 'description': 'Origin-bound capability returned by a public widget session'},
            'WidgetResumeCapability': {'type': 'http', 'scheme': 'bearer', 'description': 'Origin-bound seven-day resume token returned by a public widget session; never a dashboard credential'},
        })
        for path, operations in schema['paths'].items():
            for operation in operations.values():
                if not isinstance(operation, dict) or 'responses' not in operation:
                    continue
                if path.endswith('/oauth/start') or path == '/v1/auth/scheduling/{provider}/callback':
                    operation['security'] = [{'DashboardSession': []}]
                elif path.startswith('/v1/workspaces/'):
                    operation.setdefault('security', [{'WorkspaceKey': []}, {'DashboardSession': []}])
                elif path.startswith(('/v1/public/voice/','/v1/public/email/')) or path == '/v1/public/chat':
                    operation['security'] = [{'WidgetCapability': []}]
                elif path == '/v1/public/sessions/resume':
                    operation['security'] = [{'WidgetResumeCapability': []}]
        app.openapi_schema = schema
        return schema
    app.openapi = openapi
    from .origin_ownership import router as origin_router
    app.include_router(origin_router)
    app.include_router(widget_protection_router)
    app.include_router(widget_email_router)
    app.include_router(key_rotation_router)
    app.include_router(billing_router)
    app.include_router(refund_router)
    app.include_router(subscription_router)
    app.include_router(transfer_router)
    from .operator_billing import router as operator_billing_router
    app.include_router(operator_billing_router)
    from .legal import router as legal_router
    app.include_router(legal_router)
    from .http_security import RequestSecurity
    app.add_middleware(RequestSecurity)
    return app


app = create_app()
