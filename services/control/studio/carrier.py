"""Plivo callback/media adapter. Live execution remains a deployment acceptance gate."""
from datetime import timezone
from urllib.parse import urlencode
from xml.etree.ElementTree import Element, SubElement, tostring
import asyncio
import base64
import contextlib
import hashlib
import json
import time
import logging
import numpy as np
import soxr
import websockets
from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy import select, text
from plivo.utils import validate_v3_signature
from .config import settings
from .db import session_scope, now
from .models import Call, Number, Agent, AgentVersion, ProviderEvent
from .domain import owned, settle_call, enqueue,bind_variables
from .security import capability, verify_capability
from .media import VoiceSession, owners
from .async_work import durable_await
from .media_lifecycle import locked_call, finalize as finalize_media
from .carrier_config import callback_credentials

router = APIRouter()
log = logging.getLogger(__name__)


def mulaw_decode(data):
    value = np.bitwise_xor(np.frombuffer(data, dtype=np.uint8), 255).astype(np.int32)
    magnitude = ((value & 15) * 8 + 132) << ((value >> 4) & 7)
    return np.where(value & 128, 132 - magnitude, magnitude - 132).astype(np.int16)


def mulaw_encode(samples):
    values = np.asarray(samples, dtype=np.int32)
    sign = np.where(values < 0, 128, 0)
    mag = np.minimum(np.abs(values), 32635) + 132
    exponent = np.clip(np.floor(np.log2(mag)).astype(np.int32) - 7, 0, 7)
    mantissa = (mag >> (exponent + 3)) & 15
    return np.bitwise_xor(sign | (exponent << 4) | mantissa, 255).astype(np.uint8).tobytes()


async def verified_form(request):
    if not settings.live_calls_enabled:
        raise HTTPException(503, "Plivo live callbacks are not enabled")
    if not settings.media_public_origin.startswith("https://"):
        raise HTTPException(503, "Configure an HTTPS MEDIA_PUBLIC_ORIGIN")
    form = {key: str(value) for key, value in (await request.form()).items()}
    carrier = callback_credentials('plivo', form, request.query_params.get('call_id'))
    if not carrier.get('auth_token'):
        raise HTTPException(503, 'Connect Plivo first')
    signature = request.headers.get("x-plivo-signature-v3", "")
    nonce = request.headers.get("x-plivo-signature-v3-nonce", "")
    uri = settings.media_public_origin.rstrip("/") + request.url.path + ("?" + request.url.query if request.url.query else "")
    if not signature or not nonce or not validate_v3_signature(request.method, uri, nonce, carrier['auth_token'], signature, form):
        raise HTTPException(401, "Invalid Plivo signature")
    return form


def e164(value):
    return "+" + str(value).lstrip("+")


@router.post("/v1/provider-webhooks/plivo/answer")
async def answer(request: Request, call_id: str | None = None):
    form = await verified_form(request)
    provider_id = form.get("CallUUID", "")
    if not provider_id or len(provider_id) > 100:
        raise HTTPException(422, "Plivo CallUUID missing")
    with session_scope(write=True) as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "plivo:" + provider_id})
        if call_id:
            call = db.scalar(select(Call).where(Call.id==call_id).with_for_update())
            if not call or call.mode != "live" or call.transport != "pstn" or call.metadata_data.get('provider','plivo')!='plivo':
                raise HTTPException(404, "Call not found")
            if call.destination and e164(form.get("To", "")) != e164(call.destination):
                raise HTTPException(403, "Carrier destination differs from the admitted call")
            if call.provider_call_id and call.provider_call_id != provider_id:
                if call.metadata_data.get('provider_leg_bound'):raise HTTPException(403,'Carrier call identity mismatch')
                call.metadata_data = {**call.metadata_data, "provider_request_id": call.provider_call_id}
            call.provider_call_id = provider_id
            call.metadata_data={**call.metadata_data,'provider':'plivo','provider_leg_bound':True}
        else:
            call = db.scalar(select(Call).where(Call.provider_call_id == provider_id, Call.transport == "pstn", Call.mode == "live"))
            if not call:
                number = db.scalar(select(Number).where(Number.e164 == e164(form.get("To", "")), Number.provider == "plivo", Number.status == "active", Number.can_inbound.is_(True)))
                if not number or not number.agent_id:
                    root = Element("Response");SubElement(root, "Hangup")
                    return Response(tostring(root, encoding="unicode"), media_type="application/xml")
                agent = owned(db, Agent, number.workspace_id, number.agent_id)
                from .llm import live_voice_ready
                if not agent.published_version_id or not live_voice_ready(owned(db,AgentVersion,number.workspace_id,agent.published_version_id).config,number.workspace_id):
                    raise HTTPException(409, "Inbound agent/voice pipeline is not ready")
                call = Call(workspace_id=number.workspace_id, agent_version_id=agent.published_version_id, agent_name=agent.name, direction="inbound", transport="pstn", mode="live", provider_call_id=provider_id,
                            metadata_data={'provider':'plivo','provider_leg_bound':True,'variables':{'caller_number':form.get('From','')},"number_id": number.id})
                db.add(call); db.flush()
                from .admission import admit_voice
                admit_voice(db,call,owned(db,AgentVersion,call.workspace_id,call.agent_version_id).config)
        if call.state in {"ending","completed", "failed", "canceled", "no_answer", "busy"}:
            root = Element("Response");SubElement(root, "Hangup")
            return Response(tostring(root, encoding="unicode"), media_type="application/xml")
        if 'admitted_max_seconds' not in call.metadata_data:
            from .admission import admit_voice
            admit_voice(db,call,owned(db,AgentVersion,call.workspace_id,call.agent_version_id).config)
        if call.state in {'created','ringing'}:call.state = "connecting"
        from .carrier_config import remaining_seconds
        remaining=remaining_seconds(call)
        token = capability({"aud": "carrier", "workspace_id": call.workspace_id, "call_id": call.id, "provider_call_id": provider_id}, ttl=180)
    media_origin = settings.media_public_origin.replace("https://", "wss://").rstrip("/")
    root = Element("Response")
    if remaining==0:
        SubElement(root,'Hangup');return Response(tostring(root,encoding='unicode'),media_type='application/xml')
    SubElement(root,'Hangup',{'schedule':str(remaining)})
    stream = SubElement(root, "Stream", {"bidirectional": "true", "keepCallAlive": "true", "contentType": "audio/x-mulaw;rate=8000"})
    stream.text = media_origin + "/v1/carrier-media/" + token
    SubElement(root, "Hangup")
    return Response(tostring(root, encoding="unicode"), media_type="application/xml")


@router.post("/v1/provider-webhooks/plivo/hangup")
async def hangup(request: Request, call_id: str | None = None):
    form = await verified_form(request)
    provider_id = form.get("CallUUID", "")
    event_hash = hashlib.sha256(json.dumps(form, sort_keys=True).encode()).hexdigest()
    with session_scope(write=True) as db:
        event = db.scalar(select(ProviderEvent).where(ProviderEvent.provider == "plivo", ProviderEvent.event_key == event_hash))
        if event:
            return {"status": "acknowledged"}
        call = db.get(Call, call_id) if call_id else db.scalar(select(Call).where(Call.provider_call_id == provider_id, Call.mode == "live"))
        if not call or call.mode != "live" or call.metadata_data.get('provider','plivo')!='plivo' or call.provider_call_id and call.provider_call_id != provider_id:
            raise HTTPException(404, "Provider call leg not found")
        db.add(ProviderEvent(provider="plivo", event_key=event_hash, payload_hash=event_hash))
        call.metadata_data = {**call.metadata_data, "provider_duration_seconds": form.get("BillDuration"), "provider_hangup_cause": form.get("HangupCauseName")}
        connected_ms = int((now() - call.connected_at.replace(tzinfo=timezone.utc)).total_seconds() * 1000) if call.connected_at else 0
        outcome = "completed" if call.connected_at else "busy" if "busy" in str(form.get("HangupCauseName", "")).lower() else "no_answer"
        settle_call(db, call, connected_ms, outcome)
    return {"status": "acknowledged"}


class PlivoTransport:
    """Translate application audio/control to the negotiated carrier protocol."""
    def __init__(self, websocket, stream_id):
        self.ws, self.stream_id = websocket, stream_id
        self.resampler = soxr.ResampleStream(24000, 8000, 1, dtype="int16", quality="LQ")

    async def send_json(self, event):
        if event.get("type") == "server.clear":
            self.resampler.clear()
            await self.ws.send_json({"event": "clearAudio", "streamId": self.stream_id})

    async def send_bytes(self, frame):
        pcm = np.frombuffer(frame[32:], dtype="<i2")
        converted = self.resampler.resample_chunk(pcm)
        if len(converted):
            await self.ws.send_json({"event": "playAudio", "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": base64.b64encode(mulaw_encode(converted)).decode()}})

    async def close(self):
        await self.ws.close()


@router.websocket("/v1/carrier-media/{token}")
async def carrier_media(websocket: WebSocket, token: str):
    try:
        claims = verify_capability(token, "carrier")
    except HTTPException:
        await websocket.close(1008)
        return
    if not settings.live_calls_enabled:
        await websocket.close(1008)
        return
    call_id, ws = claims["call_id"], claims["workspace_id"]
    if call_id in owners:
        await websocket.close(1008)
        return
    owners.add(call_id)
    session, recognize, idle = None, None, None
    failed = False
    admitted = False
    try:
        await websocket.accept()
        start = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if start.get("event") == "connected":
            start = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        data = start.get("start", {})
        if start.get("event") != "start" or data.get("callId") != claims["provider_call_id"] or data.get("mediaFormat", {}).get("encoding") != "audio/x-mulaw" or data.get("mediaFormat", {}).get("sampleRate") != 8000:
            raise ValueError("Carrier stream identity or negotiated audio format mismatch")
        stream_id = data["streamId"]
        def admit():
            with session_scope(write=True) as db:
                call = locked_call(db, ws, call_id)
                if call.provider_call_id != claims["provider_call_id"] or call.state not in {"connecting", "ringing"}:
                    raise ValueError("Carrier leg is unavailable")
                config = bind_variables(owned(db, AgentVersion, ws, call.agent_version_id).config,call.metadata_data.get('variables',call.metadata_data.get('contact',{})))
                from .llm import live_voice_ready
                if not live_voice_ready(config,ws):raise ValueError('Voice pipeline not configured')
                call.connected_at = call.connected_at or now()
                call.state = "connected"
            return config
        async def initialize():
            nonlocal config, admitted, session
            config = await asyncio.to_thread(admit)
            admitted = True
            transport = PlivoTransport(websocket, stream_id)
            session = await asyncio.to_thread(VoiceSession, transport, ws, call_id, config, 'live')
        config = None
        await durable_await(initialize())
        await session.open_recognition()
        recognize = asyncio.create_task(session.recognize())
        session.task = asyncio.create_task(session.respond())
        idle=asyncio.create_task(session.watch_idle())
        input_resampler = soxr.ResampleStream(8000, 16000, 1, dtype="int16", quality="LQ")
        deadline = time.monotonic() + min(config["behavior"]["max_connected_seconds"], 900,session.admitted_max_seconds)
        while time.monotonic() < deadline:
            message = await session.receive(websocket.receive_json(), timeout=30)
            if message.get("event") == "stop":
                break
            if message.get("event") == "media":
                if message.get("streamId") != stream_id:
                    raise ValueError("Unexpected carrier stream ID")
                media = message.get("media", {})
                if media.get("track") != "inbound":
                    continue
                payload = base64.b64decode(media["payload"], validate=True)
                if not 1 <= len(payload) <= 1600:
                    raise ValueError("Carrier audio payload is too large")
                pcm = input_resampler.resample_chunk(mulaw_decode(payload))
                if len(pcm):
                    session.recording.add(pcm.astype('<i2', copy=False).tobytes(), 16000, 0)
                    await session.recognition_audio(pcm.astype("<i2", copy=False).tobytes())
    except asyncio.CancelledError:
        failed = True
        raise
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        failed = True
        log.exception("Carrier media failed for internal call %s", call_id)
    finally:
        try:
            await durable_await(finalize_media(session, ws, call_id, admitted=admitted,
                failed=failed, failure_code='carrier_media_failed', tasks=(idle, recognize)))
        finally:
            owners.discard(call_id)
            with contextlib.suppress(Exception):
                await websocket.close()
