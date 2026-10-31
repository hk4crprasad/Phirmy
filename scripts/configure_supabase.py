"""Set the main database connection without shell arguments or terminal echo."""
from getpass import getpass
from pathlib import Path
import os
from dotenv import dotenv_values, set_key, unset_key
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if not path.exists():
    path.write_text((root / ".env.example").read_text())
os.chmod(path, 0o600)
connection = getpass("Supabase PostgreSQL connection URL (hidden): ")
if not connection:
    raise SystemExit("Connection was empty; no change made.")
try:
    url = make_url(connection)
    if url.drivername not in {"postgresql", "postgresql+psycopg"} or not url.host or not url.username or not url.password or not url.database:
        raise ValueError("Incomplete PostgreSQL connection")
    url = url.update_query_dict({"sslmode": "require"})
except Exception:
    raise SystemExit("Enter a complete PostgreSQL URL from Supabase Connect; value not displayed.")
set_key(str(path), "DATABASE_URL", url.render_as_string(hide_password=False), quote_mode="always")
# Remove the superseded fields so the legacy override cannot select another DB.
existing = dotenv_values(path)
for key in ("SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_NAME", "SUPABASE_DB_PASSWORD", "RUNTIME_DATABASE_URL"):
    if key in existing:
        unset_key(str(path), key)
print("Saved DATABASE_URL privately with TLS. Value not displayed.")
print("Set MIGRATION_DATABASE_URL for the same database before schema maintenance.")
