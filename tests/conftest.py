import os
import sys
import tempfile
from pathlib import Path
import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="voice-studio-test-"))
os.environ.update({
    'SARVAM_API_KEY':'', 'VOICE_PROVIDER':'legacy',
    'APP_ORIGIN':'http://localhost:3000','PUBLIC_API_ORIGIN':'http://localhost:8000',
    'BILLING_OPERATOR_EMAILS':'','BILLING_OPERATOR_REFUNDS_ENABLED':'false',
    'BILLING_DEVELOPMENT_ALLOWANCES_ENABLED':'true','PAID_ACTIVATION_ENABLED':'false',
    'RAZORPAY_WEBHOOK_SECRET':'','RAZORPAY_WEBHOOK_PREVIOUS_SECRETS_JSON':'',
    'CIPHER_KEY_PROVIDER':'local','CIPHER_KEYS_JSON':'','CIPHER_ACTIVE_KEY_ID':'app-v1','CIPHER_VAULT_URL':'',
    'CIPHER_ROTATION_OPERATOR_EMAILS':'','TURNSTILE_SITE_KEY':'','TURNSTILE_SECRET_KEY':'',
    'WIDGET_BOT_CHALLENGE_ENABLED':'false','WIDGET_MARKETING_CONSENT_ENABLED':'false',
    'CONTENT_SANDBOX_SOCKET':os.environ.get('STUDIO_TEST_SANDBOX_SOCKET',str(TEST_ROOT/'sandbox/content.sock')),
    "APP_ENV": "test", "REDIS_URL": "", "PUBLIC_NETWORK_MODE": "direct", "PUBLIC_HTTP_PROXY": "", "REQUIRE_EMAIL_VERIFICATION": "false", "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "", "DATABASE_URL": "sqlite:///" + str(TEST_ROOT / "test.db"),
    "DATA_DIR": str(TEST_ROOT / "data"), "APP_SECRET": "test-secret-not-for-deployment-" + "x" * 32,
    "OBJECT_STORAGE_PROVIDER": "local", "DEV_SEED_ENABLED": "true",
    "SESSION_SECURE": "false", "SUPABASE_DB_PASSWORD": "", "OPENAI_API_KEY": "",
    "EMBEDDING_API_KEY": "", "VECTOR_ENDPOINT": "", "VECTOR_API_KEY": "",
    "AZURE_STORAGE_CONNECTION_STRING": "", "AZURE_STORAGE_ACCOUNT_URL": "", 'AZURE_STORAGE_PREFIX':'',
    "FISH_API_KEY": "", "FISH_VOICE_ID": "", "FISH_TTS_MODEL":"s2.1-pro", "DEEPGRAM_API_KEY": "",
    "PLIVO_AUTH_ID": "", "PLIVO_AUTH_TOKEN": "", "LIVE_CALLS_ENABLED": "false",
    "PHONE_TRIALS_ENABLED": "false", "BETA_OPERATOR_EMAIL": "",
    "TWILIO_API_KEY": "", "TWILIO_API_SECRET": "", "PHONE_TRIAL_AUTO_ASSIGN_POOL_ID": "",
    "PHONE_NUMBER_PURCHASES_ENABLED": "false",
    "RAZORPAY_KEY_ID": "", "RAZORPAY_KEY_SECRET": "", "LIVE_PAYMENTS_ENABLED": "false",
    'RAZORPAY_MODE':'test','RAZORPAY_TEST_KEY_ID':'','RAZORPAY_TEST_KEY_SECRET':'','RAZORPAY_LIVE_KEY_ID':'','RAZORPAY_LIVE_KEY_SECRET':'',
    'CALCOM_CLIENT_ID':'','CALCOM_CLIENT_SECRET':'','CALCOM_OAUTH_MODE':'confidential','CALENDLY_CLIENT_ID':'','CALENDLY_CLIENT_SECRET':'',
    'SMTP_HOST':'','OPENAI_BASE_URL':'https://api.openai.com/v1','OPENAI_MODEL':'gpt-5.6-luna','OPENAI_CHAT_MODEL':'','OPENAI_API_STYLE':'auto','OPENAI_TOKEN_PARAMETER':'auto','OPENAI_REASONING_EFFORT':'auto','EMBEDDING_BASE_URL':'','TWILIO_ACCOUNT_SID':'','TWILIO_AUTH_TOKEN':'','TWILIO_CALLER_ID':'',
})

from fastapi.testclient import TestClient
from studio.main import create_app, initialize_database
from studio.db import Base, engine
from studio.security import limiter
from studio.media import owners
from studio.config import settings
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qa_accounts import bootstrap_account


def pytest_addoption(parser):
    parser.addoption('--run-sandbox', action='store_true', default=False,
                     help='Run real isolated parser/browser/audio/PDF integrations; requires Docker and browser dependencies')
    parser.addoption('--beta-smoke', action='store_true', default=False,
                     help='Run only the explicitly allowlisted offline beta release checks')


def pytest_configure(config):
    if os.environ.get('CI', '').casefold() in {'1', 'true'} and not (config.getoption('--run-sandbox') or config.getoption('--beta-smoke')):
        raise pytest.UsageError('CI must run the real sandbox checks: pass --run-sandbox (Docker is mandatory)')


def pytest_collection_modifyitems(config, items):
    if config.getoption('--beta-smoke'):
        allowed = {'test_identity.py', 'test_media_lifecycle.py', 'test_sarvam_voice.py', 'test_widget_preview.py', 'test_gateway_metering.py', 'test_beta_allowances.py'}
        if not items or any(item.path.name not in allowed or item.get_closest_marker('sandbox') for item in items):
            raise pytest.UsageError('--beta-smoke only accepts the approved offline release modules')
        return
    if config.getoption('--run-sandbox'):
        return
    skip = pytest.mark.skip(reason='Real sandbox integration: opt in with --run-sandbox')
    for item in items:
        if item.get_closest_marker('sandbox'):
            item.add_marker(skip)


@pytest.fixture(scope='session',autouse=True)
def isolated_content_service(request):
    if not request.config.getoption('--run-sandbox'):
        yield
        return
    if os.environ.get('STUDIO_TEST_SANDBOX_SOCKET'):
        assert Path(settings.content_sandbox_socket).is_socket(),'Start the isolated content service before testing'
        yield
        return
    from content_sandbox import start,stop
    name='studio-content-tests-'+str(os.getpid())
    try:
        start(TEST_ROOT/'sandbox',name)
        yield
    finally:stop(name)


def verify_test_origin(client, base, origin, monkeypatch):
    from studio import origin_ownership
    challenge = client.post(base+'/origins', json={'origin':origin})
    assert challenge.status_code == 201, challenge.text
    details = challenge.json()
    class FakeProof:
        async def verify(self, candidate, method, token):
            return candidate == origin and method == 'dns' and origin_ownership.PREFIX+token == details['dns']['value']
    monkeypatch.setattr(origin_ownership, 'provider', FakeProof())
    response = client.post(base+'/origins/'+details['id']+'/verify', json={'method':'dns'})
    assert response.status_code == 200, response.text
    return details['id']


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    # Timing is tested with a deterministic clock; avoid real padding on every fixture.
    monkeypatch.setattr(settings, 'auth_response_floor_ms', 0)
    # Mail tokens are scoped to the database reset below; do not retain an
    # earlier test's email and accidentally exercise its now-invalid token.
    outbox = TEST_ROOT / 'data' / 'mail-outbox'
    if outbox.exists():
        for message in outbox.glob('*.eml'):
            message.unlink()
    Base.metadata.drop_all(engine)
    initialize_database()
    limiter.entries.clear()
    owners.clear()
    yield


@pytest.fixture
def client():
    with TestClient(create_app(start_worker=False)) as client:
        yield client


def signup(client, email="qa@example.test"):
    from studio.legal import current
    response = client.post("/v1/auth/signup", json={
        "legal_accepted": True, "legal_version": current()["version"],
        "name": "QA Builder", "email": email, "password": "Long-Local-Test-Password", "workspace_name": "Test Workspace",
    })
    assert response.status_code == 202, response.text
    response = client.post('/v1/auth/signin', json={'email': email, 'password': 'Long-Local-Test-Password'})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = client.cookies["studio_csrf"]
    workspace_id = client.get('/v1/auth/me').json()['workspaces'][0]['id']
    return workspace_id


@pytest.fixture
def account(client):
    workspace_id = signup(client)
    return client, workspace_id, "/v1/workspaces/" + workspace_id


@pytest.fixture
def sample(account):
    client, workspace_id, base = account
    response = client.post(base + "/fixtures", json={})
    assert response.status_code == 201, response.text
    return client, workspace_id, base, response.json()
