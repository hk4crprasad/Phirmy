from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import AsyncMock
import asyncio
import json
import struct
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
import pytest
from studio.db import session_scope, now, uid
from studio.models import *
from studio.domain import settle_call, reserve, wallet_state, post_ledger
from studio.main import create_app
from studio.security import digest
from studio.config import settings
from studio.knowledge import canonical_url, extract_page, retrieve, validate_public_url
from studio.media import HEADER, decode_frame, encode_frame
from studio.workers import execute_job
from conftest import signup


def test_signup_next_request_is_authenticated(account):
    client, ws, base = account
    response = client.get("/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["workspaces"][0]["id"] == ws
    assert client.get(base + "/wallet").json()["balance_minor"] == 10000


def test_csrf_and_foreign_origin_rejected(account):
    client, ws, base = account
    assert client.post(base + "/agents", json={"name": "Bad CSRF"}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert client.post(base + "/agents", json={"name": "Bad origin"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_signout_revokes_session(account):
    client, ws, base = account
    assert client.post("/v1/auth/signout").status_code == 200
    assert client.get("/v1/auth/me").status_code == 401


def test_password_is_hashed_and_short_password_rejected(client):
    assert client.post("/v1/auth/signup", json={"name": "X", "email": "x@example.test", "password": "short", "workspace_name": "X"}).status_code == 422
    signup(client)
    with session_scope() as db:
        assert db.scalar(select(User)).password_hash.startswith("$argon2")


def test_cross_workspace_ids_do_not_resolve(sample):
    client, ws, base, fixture = sample
    with TestClient(create_app(start_worker=False)) as other:
        other_ws = signup(other, "other@example.test")
        assert other.get(base + "/knowledge/" + fixture["kb_id"]).status_code == 404
        assert other.get("/v1/workspaces/" + other_ws + "/agents/" + fixture["agent_id"]).status_code == 404


def test_read_only_key_cannot_dispatch_or_create(account):
    client, ws, base = account
    key = client.post(base + "/keys", json={"name": "Read only", "scopes": ["kb:read", "billing:read"]}).json()
    secret = key["secret"]
    with session_scope() as db:
        stored = db.get(APIKey, key["key"]["id"])
        assert stored.secret_hash == digest(secret)
        assert secret != stored.secret_hash
    header = {"X-API-Key": secret}
    assert client.get(base + "/knowledge", headers=header).status_code == 200
    assert client.get(base + "/wallet", headers=header).status_code == 200
    assert client.post(base + "/agents", json={"name": "Denied"}, headers=header).status_code == 403
    assert client.delete(base + "/keys/" + key["key"]["id"]).status_code == 200
    assert client.get(base + "/knowledge", headers=header).status_code == 401


def test_key_does_not_expose_hash(account):
    client, ws, base = account
    client.post(base + "/keys", json={"name": "Test", "scopes": ["kb:read"]})
    assert "secret_hash" not in client.get(base + "/keys").text


def test_publish_pins_immutable_version_and_draft_conflicts(sample):
    client, ws, base, fixture = sample
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    first = agent["published_version_id"]
    config = agent["draft_config"]
    config["greeting"] = "Version two greeting."
    draft = client.put(base + "/agents/" + agent["id"] + "/draft", json={"expected_revision": agent["draft_revision"], "config": config})
    assert draft.status_code == 200
    assert client.put(base + "/agents/" + agent["id"] + "/draft", json={"expected_revision": agent["draft_revision"], "config": config}).status_code == 409
    result = client.post(base + "/agents/" + agent["id"] + "/publish", json={"expected_draft_revision": draft.json()["draft_revision"]})
    assert result.status_code == 201
    with session_scope() as db:
        assert db.get(AgentVersion, first).config["greeting"] != config["greeting"]
        assert db.get(AgentVersion, result.json()["id"]).config["greeting"] == config["greeting"]


def test_undefined_variables_block_publish(sample):
    client, ws, base, fixture = sample
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    config = agent["draft_config"]; config["greeting"] = "Hello {{unknown_customer}}"
    saved = client.put(base + "/agents/" + agent["id"] + "/draft", json={"expected_revision": 1, "config": config}).json()
    response = client.post(base + "/agents/" + agent["id"] + "/publish", json={"expected_draft_revision": saved["draft_revision"]})
    assert response.status_code == 422
    assert "undefined_variable" in response.text


def test_model_substitution_blocked(sample):
    client, ws, base, fixture = sample
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    config = agent["draft_config"]; config["llm"]["model"] = "different-model"
    client.put(base + "/agents/" + agent["id"] + "/draft", json={"expected_revision": 1, "config": config})
    assert client.post(base + "/agents/" + agent["id"] + "/publish", json={"expected_draft_revision": 2}).status_code == 422


def test_url_canonicalization_and_carousel_exclusion():
    assert canonical_url("https://EXAMPLE.com/?utm_source=qa#section") == "https://example.com/"
    assert canonical_url("https://example.com") == canonical_url("https://example.com/")
    extracted = extract_page(b"<html><title>Product</title><nav>Menu</nav><main><p>Engraving limit is 20 characters.</p><div class='product-recommendations'>Unrelated refund 90 days</div></main></html>", "https://example.com")
    assert "20 characters" in extracted["text"]
    assert "90 days" not in extracted["text"]
    assert "Menu" not in extracted["text"]


@pytest.mark.asyncio
async def test_private_and_metadata_urls_rejected():
    for url in ["http://127.0.0.1", "http://169.254.169.254/latest/meta-data", "http://[::1]/", "file:///etc/passwd", "https://example.com:8443"]:
        with pytest.raises(ValueError):
            await validate_public_url(url)


def test_retrieval_has_workspace_and_snapshot_provenance(sample):
    client, ws, base, fixture = sample
    response = client.post(base + "/knowledge/" + fixture["kb_id"] + "/query", json={"query": "engraving character limit"})
    assert response.status_code == 200
    assert response.json()["retrieval_mode"] == "lexical-development"
    assert response.json()["passages"]
    assert "20 characters" in response.json()["passages"][0]["text"]


@pytest.mark.sandbox
def test_document_job_upload_and_promotion(sample):
    client, ws, base, fixture = sample
    before = client.get(base + "/knowledge/" + fixture["kb_id"]).json()["active_snapshot_id"]
    result = client.post(base + "/knowledge/" + fixture["kb_id"] + "/documents", files={"file": ("hours.txt", b"Business hours: Monday to Friday from 9 AM to 5 PM. Contact support for appointments.", "text/plain")})
    assert result.status_code == 202, result.text
    asyncio.run(execute_job(result.json()["id"]))
    job = client.get(base + "/jobs/" + result.json()["id"]).json()
    assert job["state"] == "completed", job
    after = client.get(base + "/knowledge/" + fixture["kb_id"]).json()["active_snapshot_id"]
    assert before != after
    with session_scope() as db:
        version = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == fixture["agent_id"]))
        assert version.config["knowledge_snapshot_ids"] == [before]


def test_invalid_document_type_and_magic_rejected(sample):
    client, ws, base, fixture = sample
    path = base + "/knowledge/" + fixture["kb_id"] + "/documents"
    assert client.post(path, files={"file": ("payload.exe", b"binary", "application/octet-stream")}).status_code == 422
    assert client.post(path, files={"file": ("bad.pdf", b"not a PDF", "application/pdf")}).status_code == 422


def test_widget_product_answer_ticket_and_auth_isolation(sample):
    client, ws, base, fixture = sample
    installation = client.get(base + "/installations").json()["items"][0]
    headers = {"Origin": settings.app_origin}
    session = client.post("/v1/public/sessions", json={"visitor_email":"visitor@example.test","installation_public_id": installation["public_id"]}, headers=headers).json()
    widget_headers = {**headers, "Authorization": "Bearer " + session["session_token"]}
    message = {"session_id": session["id"], "message": "What is the cufflinks price?", "client_message_id": uid()}
    response = client.post("/v1/public/chat", json=message, headers=widget_headers)
    assert "INR 999" in response.text
    assert "chat.products" in response.text
    repeat = client.post("/v1/public/chat", json=message, headers=widget_headers)
    assert repeat.status_code == 200
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == session["id"], Message.role == "assistant")) == 1
    ticket_request = {**message, "message": "Please create a support ticket for follow-up.", "client_message_id": uid()}
    ticket_reply = client.post("/v1/public/chat", json=ticket_request, headers=widget_headers)
    assert 'chat.confirmation.required' in ticket_reply.text
    assert len(client.get(base + "/tickets").json()["items"]) == 0
    confirmed = client.post('/v1/public/chat',json={**message,'message':'Confirm request','client_message_id':uid()},headers=widget_headers)
    assert "chat.ticket.created" in confirmed.text
    assert len(client.get(base + "/tickets").json()["items"]) == 1
    bad = client.post("/v1/public/chat", json=message, headers={**headers, "Authorization": "Bearer invalid"})
    assert bad.status_code == 401
    assert client.get("/v1/auth/me").status_code == 200


def test_widget_foreign_origin_denied(sample):
    client, ws, base, fixture = sample
    installation = client.get(base + "/installations").json()["items"][0]
    assert client.post("/v1/public/sessions", json={"visitor_email":"visitor@example.test","installation_public_id": installation["public_id"]}, headers={"Origin": "https://other.example"}).status_code == 403


def test_product_canonical_merge(sample):
    client, ws, base, fixture = sample
    original = client.get(base + "/products").json()["items"][0]
    body = {key: original[key] for key in ["store_id", "title", "canonical_url", "description", "price_minor", "currency", "availability", "customization_max_chars"]}
    body["canonical_url"] += "/"
    result = client.post(base + "/products", json=body)
    assert result.status_code == 201
    assert result.json()["id"] == original["id"]
    assert len(client.get(base + "/products").json()["items"]) == 1


def test_outbound_idempotency_body_conflict_and_no_live_dispatch(sample):
    client, ws, base, fixture = sample
    body = {"agent_id": fixture["agent_id"], "destination": "+12025550123", "mode": "simulation", "budget_minor": 500}
    headers = {"Idempotency-Key": "test-dial-command"}
    first = client.post(base + "/calls/outbound", json=body, headers=headers)
    second = client.post(base + "/calls/outbound", json=body, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert client.post(base + "/calls/outbound", json={**body, "destination": "+12025550124"}, headers=headers).status_code == 409
    assert client.post(base + "/calls/outbound", json={**body, "mode": "live"}, headers={"Idempotency-Key": "live-is-disabled"}).status_code == 409


def test_66_second_settlement_race_posts_one_debit(sample):
    client, ws, base, fixture = sample
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    with session_scope(write=True) as db:
        call = Call(workspace_id=ws, agent_version_id=agent["published_version_id"], agent_name="Billing QA", state="connected", mode="simulation", metadata_data={"rate_minor_per_minute": 600})
        db.add(call); db.flush()
        call_id = call.id
        reserve(db, call, 1000)
    def settle(_):
        with session_scope(write=True) as db:
            return settle_call(db, db.get(Call, call_id), 66000).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(settle, range(2))) == [call_id, call_id]
    with session_scope() as db:
        entries = list(db.scalars(select(Ledger).where(Ledger.call_id == call_id)))
        assert len(entries) == 1
        assert entries[0].amount_minor == -660
        assert wallet_state(db, ws)["available_minor"] == 9340
        assert db.get(Call, call_id).analysis["is_lead"] is False
        assert db.get(Call, call_id).analysis["disposition"] == "no_engagement"


def test_ledger_update_is_rejected(account):
    client, ws, base = account
    with pytest.raises(IntegrityError):
        with session_scope(write=True) as db:
            db.execute(text("UPDATE ledger_entries SET amount_minor = 999 WHERE workspace_id = :ws"), {"ws": ws})


def test_campaign_start_does_not_duplicate_dispatch(sample):
    client, ws, base, fixture = sample
    agent = client.get(base + "/agents/" + fixture["agent_id"]).json()
    campaign = client.post(base + "/campaigns", json={"name": "QA", "agent_version_id": agent["published_version_id"], "mode": "simulation", "max_attempts": 1}).json()
    result = client.post(base + "/campaigns/" + campaign["id"] + "/contacts", json={"contacts": [{"phone": "+12025550123"}, {"phone": "+12025550123"}], "dry_run": False})
    assert result.json()["accepted"] == 1 and result.json()["duplicates"] == 1
    for _ in range(2):
        assert client.post(base + "/campaigns/" + campaign["id"] + "/start").status_code == 200
    jobs = [j for j in client.get(base + "/jobs").json()["items"] if j["kind"] == "campaign"]
    assert len(jobs) == 1
    asyncio.run(execute_job(jobs[0]["id"]))
    assert client.get(base + "/campaigns/" + campaign["id"]).json()["state"] == "completed"
    assert client.post(base + "/campaigns/" + campaign["id"] + "/start").json()["state"] == "completed"
    assert len(client.get(base + "/campaigns/" + campaign["id"] + "/attempts").json()["items"]) == 1


def test_booking_idempotency_and_slot_conflict(account):
    client, ws, base = account
    start = now() + timedelta(days=1)
    body = {"title": "QA booking", "start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat(), "timezone": "Asia/Kolkata"}
    first = client.post(base + "/appointments", json=body, headers={"Idempotency-Key": "booking-one"})
    second = client.post(base + "/appointments", json=body, headers={"Idempotency-Key": "booking-one"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert client.post(base + "/appointments", json=body, headers={"Idempotency-Key": "booking-two"}).status_code == 409
    assert first.json()["state"] == "local"


def test_audio_packet_boundaries():
    pcm = bytes(640)
    good = HEADER.pack(b"NTV1", 1, 1, 1, 0, 16000, 0, 0, 640, 0) + pcm
    assert decode_frame(good)[0] == pcm
    for bad in [b"x", good[:-1], HEADER.pack(b"NTV1", 1, 1, 1, 0, 48000, 0, 0, 640, 0) + pcm]:
        with pytest.raises(ValueError):
            decode_frame(bad)
    assert len(encode_frame(bytes(960), 2, 1, 20)) == 992


def test_browser_simulation_and_no_engagement_analysis(sample):
    client, ws, base, fixture = sample
    session = client.post(base + "/voice/sessions", json={"agent_id": fixture["agent_id"], "mode": "simulation"}).json()
    with client.websocket_connect("/v1/media", headers={"Origin": settings.app_origin}) as socket:
        socket.send_json({"type": "client.start", "session_token": session["session_token"]})
        assert socket.receive_json()["type"] == "server.ready"
        while True:
            message = socket.receive_json()
            if message["type"] == "server.turn_state" and message["state"] == "listening":
                break
        socket.send_json({"type": "client.stop"})
        while socket.receive_json()["type"] != "server.ended":
            pass
    call = client.get(base + "/calls/" + session["call_id"]).json()
    assert call["mode"] == "simulation"
    assert call["state"] == "completed"
    assert call["analysis"]["user_turn_count"] == 0
    assert call["analysis"]["is_lead"] is False
    assert client.get(base + "/wallet").json()["balance_minor"] == 10000
