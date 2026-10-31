"""Regression gates for admission, callback replay and generation truthfulness."""
import asyncio
import json
from datetime import timedelta
from plivo.utils.signature_v3 import get_signature_v3, construct_post_url
from sqlalchemy import select
from studio.config import settings
from studio.db import session_scope, now
from studio.models import Call, ProviderEvent, Agent, Campaign, Ledger, Attempt
from studio.workers import execute_job
import pytest


@pytest.mark.asyncio
async def test_interrupt_clears_audio_after_generation_already_finished():
    from studio.media import VoiceSession
    class Socket:
        def __init__(self): self.events = []
        async def send_json(self, event): self.events.append(event)
    socket = Socket()
    session = VoiceSession(socket, "workspace", "call", {}, "simulation")
    session.task = asyncio.create_task(asyncio.sleep(0))
    await session.task
    await session.interrupt()
    assert session.epoch == 1
    assert socket.events[-1]["type"] == "server.clear"
    assert socket.events[-1]["epoch"] == 1
    assert session.task is None


@pytest.mark.asyncio
async def test_closed_socket_cannot_abort_session_cleanup():
    from fastapi import WebSocketDisconnect
    from studio.media import VoiceSession
    class Socket:
        async def send_json(self, event): raise WebSocketDisconnect(1006)
    session = VoiceSession(Socket(), "workspace", "call", {}, "simulation")
    session.task = asyncio.create_task(asyncio.sleep(0))
    await session.task
    await session.interrupt()
    assert session.task is None


def test_bootstrap_preserves_scope_checks_and_key_redaction(sample):
    from fastapi.testclient import TestClient
    from studio.main import create_app
    client, ws, base, fixture = sample
    secret = client.post(base + "/keys", json={"name": "KB only", "scopes": ["kb:read"]}).json()["secret"]
    response = client.get(base + "/bootstrap")
    assert response.status_code == 200 and response.json()["summary"]["published_agents"] == 1
    assert "secret_hash" not in response.text and secret not in response.text
    with TestClient(create_app(start_worker=False)) as scoped:
        scoped.headers["X-API-Key"] = secret
        result = scoped.get(base + "/bootstrap").json()
        assert set(result["data"]) == {"knowledge", "jobs"}
        assert result["summary"] == {} and "calls" in result["denied"]


def test_generation_stream_identifies_template(account):
    client, ws, base = account
    response = client.post(base + "/agents/generate", json={"goal": "Help gift customers", "language": "en", "business_url": "https://palsona.in"})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[0]["mode"] == "development-template"
    assert events[-1]["mode"] == "development-template"
    assert "Help gift customers" in events[-1]["instructions"]


def test_campaign_accepts_bounded_execution_settings(sample):
    client, ws, base, fixture = sample
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    for extra in [{"concurrency": 2}, {"max_attempts": 2}]:
        response = client.post(base + "/campaigns", json={"name": "QA", "agent_version_id": agent["published_version_id"], **extra})
        assert response.status_code == 201
    assert client.post(base+'/campaigns',json={'name':'Bad window','agent_version_id':agent['published_version_id'],'calling_hour_start':21,'calling_hour_end':9}).status_code==422


def test_campaign_budget_applies_across_contacts(sample):
    client, ws, base, fixture = sample
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    campaign = client.post(base + "/campaigns", json={"name": "Cap QA", "agent_version_id": agent["published_version_id"], "budget_minor": 350}).json()
    client.post(base + "/campaigns/" + campaign["id"] + "/contacts", json={"contacts": [{"phone": "+12025550123"}, {"phone": "+12025550124"}, {"phone": "+12025550125"}], "dry_run": False})
    client.post(base + "/campaigns/" + campaign["id"] + "/start")
    job = next(j for j in client.get(base + "/jobs").json()["items"] if j["kind"] == "campaign")
    asyncio.run(execute_job(job["id"]))
    assert client.get(base + "/campaigns/" + campaign["id"]).json()["state"] == "paused"
    with session_scope() as db:
        attempts = list(db.scalars(select(Attempt).where(Attempt.campaign_id == campaign["id"])))
        assert len(attempts) == 2
        assert sum(-x.amount_minor for x in db.scalars(select(Ledger).where(Ledger.call_id.in_([a.call_id for a in attempts])))) == 350


def test_number_has_one_workspace_owner(account, client):
    from fastapi.testclient import TestClient
    from studio.main import create_app
    from conftest import signup
    _, _, base = account
    assert client.post(base + "/numbers", json={"e164": "+12025550123"}).status_code == 202
    with TestClient(create_app(start_worker=False)) as second:
        other = signup(second, "number-owner@example.test")
        assert second.post(f"/v1/workspaces/{other}/numbers", json={"e164": "+12025550123"}).status_code == 409


def test_carrier_rejects_bad_signature_and_deduplicates_hangup(sample, monkeypatch):
    client, ws, base, fixture = sample
    monkeypatch.setattr(settings, "live_calls_enabled", True)
    monkeypatch.setattr(settings, "plivo_auth_token", "fake-token-for-offline-test")
    monkeypatch.setattr(settings, "media_public_origin", "https://voice.example.test")
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    with session_scope(write=True) as db:
        call = Call(workspace_id=ws, agent_version_id=agent["published_version_id"], mode="live", transport="pstn", provider_call_id="provider-qa-123", state="connected", connected_at=now() - timedelta(seconds=12))
        db.add(call); db.flush(); call_id = call.id
    path = "/v1/provider-webhooks/plivo/hangup?call_id=" + call_id
    form = {"CallUUID": "provider-qa-123", "BillDuration": "12", "HangupCauseName": "NORMAL_CLEARING"}
    assert client.post(path, data=form).status_code == 401
    nonce = "1690000000000"
    signature = get_signature_v3(settings.plivo_auth_token.encode(), construct_post_url(settings.media_public_origin + path, form).decode(), nonce.encode()).decode()
    headers = {"X-Plivo-Signature-V3": signature, "X-Plivo-Signature-V3-Nonce": nonce}
    for _ in range(2):
        assert client.post(path, data=form, headers=headers).status_code == 200
    with session_scope() as db:
        call = db.get(Call, call_id)
        assert call.state == "completed" and call.connected_ms >= 12000
        assert len(list(db.scalars(select(ProviderEvent)))) == 1
    tampered = {**form, "BillDuration": "999"}
    assert client.post(path, data=tampered, headers=headers).status_code == 401
