"""Non-destructive integration check. Retains two clearly named QA workspaces.

Uses the configured PostgreSQL database, never drops tables or truncates data.
No provider requests are made. Run from the project root with uv run python.
"""
from pathlib import Path
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from qa_accounts import bootstrap_account
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/control"))


def verify():
    from fastapi.testclient import TestClient
    from sqlalchemy import select, text, inspect
    from sqlalchemy.exc import DBAPIError
    from studio.config import settings
    from studio.main import create_app
    from studio.db import engine, session_scope, now
    from studio.models import Call, Ledger, AgentVersion
    from studio.domain import reserve, settle_call

    if engine.dialect.name != "postgresql" or settings.app_env == "production":
        raise RuntimeError("Run only against the configured development PostgreSQL deployment")
    suffix = uuid.uuid4().hex[:10]
    app = create_app(start_worker=False)

    def signup(client, name):
        response = bootstrap_account(client, "/v1/auth/signup", json={"name": "PostgreSQL QA", "email": f"pg-qa-{suffix}-{name}@example.test", "password": uuid.uuid4().hex, "workspace_name": f"Integration QA {suffix} {name}"})
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = client.cookies["studio_csrf"]
        ws = response.json()['workspaces'][0]["id"]
        return ws, "/v1/workspaces/" + ws

    with TestClient(app) as client:
        ws, base = signup(client, "primary")
        assert client.get("/v1/auth/me").status_code == 200
        fixture = client.post(base + "/fixtures").json()
        agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
        version_id = agent["published_version_id"]
        assert client.post(base + "/knowledge/" + fixture["kb_id"] + "/query", json={"query": "engraving character limit"}).status_code == 200
        with TestClient(app) as other:
            _, _ = signup(other, "isolation")
            assert other.get(base + "/agents/" + fixture["agent_id"]).status_code == 404
        with session_scope(write=True) as db:
            call = Call(workspace_id=ws, agent_version_id=version_id, state="connected", metadata_data={"rate_minor_per_minute": 600})
            db.add(call); db.flush(); call_id = call.id
            reserve(db, call, 1000)

        def settle(_):
            with session_scope(write=True) as db:
                settle_call(db, db.get(Call, call_id), 66000)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(settle, range(2)))
        with session_scope() as db:
            entries = list(db.scalars(select(Ledger).where(Ledger.call_id == call_id)))
            assert len(entries) == 1 and entries[0].amount_minor == -660
            assert db.get(Call, call_id).analysis["disposition"] == "no_engagement"
        for table, row in [("ledger_entries", entries[0].id), ("agent_versions", version_id)]:
            blocked = False
            try:
                with engine.begin() as db:
                    db.execute(text(f"UPDATE voice_studio.{table} SET id = id WHERE id = :id"), {"id": row})
            except DBAPIError:
                blocked = True
            assert blocked, "Append-only protection missing"

        start = now() + timedelta(days=2)
        booking = {"title": "Database QA", "start": start.isoformat(), "end": (start + timedelta(minutes=15)).isoformat(), "timezone": "Asia/Kolkata"}
        first = client.post(base + "/appointments", json=booking, headers={"Idempotency-Key": suffix + "-booking"})
        second = client.post(base + "/appointments", json=booking, headers={"Idempotency-Key": suffix + "-booking"})
        assert first.status_code == second.status_code == 201 and first.json()["id"] == second.json()["id"]
        assert client.post(base + "/appointments", json=booking, headers={"Idempotency-Key": suffix + "-conflict"}).status_code == 409

    with engine.connect() as db:
        assert db.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()
        assert not db.execute(text("SELECT has_schema_privilege('anon', 'voice_studio', 'USAGE')")).scalar()
        count = len(inspect(db).get_table_names(schema="voice_studio"))
    print(f"PostgreSQL integration: passed ({count} application tables, TLS)")
    print("Passed: auth, tenant isolation, knowledge query, pinned agent, concurrent settlement, append-only records, booking idempotency/conflict, no anonymous schema access.")
    print("Retained QA workspace:", ws)
    print("No unrelated schema was modified. QA uses synthetic development credit; no external provider was called.")


if __name__ == "__main__":
    try:
        verify()
    except Exception as exc:
        # Do not render credential-bearing driver errors or settings.
        print("PostgreSQL verification failed:", type(exc).__name__)
        raise SystemExit(1)
