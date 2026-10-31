"""Read-only database readiness check; never prints the connection string."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/control"))
from sqlalchemy import create_engine, text
from studio.config import settings

if not settings.database_url.startswith("postgresql"):
    raise SystemExit("PostgreSQL credentials are not configured.")
try:
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 10, "prepare_threshold": None}, pool_pre_ping=True)
    with engine.connect() as db:
        ssl = db.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()
        exists = db.execute(text("SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'voice_studio')")).scalar()
        print("PostgreSQL connection: passed")
        print("TLS:", "enabled" if ssl else "not reported")
        print("voice_studio schema:", "exists" if exists else "not created")
        print("Read-only readiness check finished; no schema/data was changed.")
except Exception as exc:
    # Driver exceptions can contain credential-bearing DSNs; keep output to a reason category.
    message = str(exc).lower()
    category = (
        "network/address route unavailable" if any(x in message for x in ["network is unreachable", "no route", "could not translate", "name or service", "name resolution"])
        else "authentication rejected" if any(x in message for x in ["password authentication", "authentication failed"])
        else "connection timeout" if "timeout" in message
        else "connection failed; inspect network, TLS and account settings"
    )
    print("PostgreSQL connection:", category)
    raise SystemExit(1)
