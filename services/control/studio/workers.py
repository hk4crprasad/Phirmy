"""Durable leased job pool and independent webhook dispatcher."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import asyncio
import hashlib
import hmac
import io
import json
import logging
import re
import time
from urllib.parse import urlparse, urljoin
import httpx
from sqlalchemy import select, or_, case
from sqlalchemy.orm import aliased
from .job_control import get_job, claim, LeaseLost
from .config import settings
from .db import session_scope, now, as_dict
from .models import *
from .domain import owned, settle_call, reserve, enqueue, emit
from .knowledge import crawl_job, safe_fetch, canonical_url, extract_page, add_source, index_snapshot
from .storage import get_store,put_checked
from .security import capability
from .secrets import decrypt

log = logging.getLogger(__name__)
JOB_HEARTBEAT_SECONDS = 20


async def document_job(job_id):
    with session_scope() as db:
        job = get_job(db,job_id)
        ws, payload = job.workspace_id, job.payload
    body = await asyncio.to_thread(lambda:get_store().get(ws,payload["object_key"]))
    from .isolation import parse_document
    text=await parse_document(body,payload['suffix'])
    with session_scope(write=True) as db:
        job = get_job(db,job_id)
        if job.cancel_requested:
            job.state = "canceled"
            return
        kb = owned(db, KnowledgeBase, ws, payload["kb_id"])
        source = add_source(db, ws, kb.id, "document://" + hashlib.sha256(body).hexdigest() + "/" + payload["filename"], payload["filename"], text, payload["object_key"])
        old = db.get(Snapshot, kb.active_snapshot_id) if kb.active_snapshot_id else None
        source_ids = list(dict.fromkeys((old.source_ids if old else []) + [source.id]))
        from sqlalchemy import func
        revision = (db.scalar(select(func.max(Snapshot.revision)).where(Snapshot.workspace_id == ws, Snapshot.kb_id == kb.id)) or 0) + 1
        snapshot = Snapshot(workspace_id=ws, kb_id=kb.id, revision=revision, source_ids=source_ids)
        db.add(snapshot); db.flush()
        snapshot_id = snapshot.id
        job.phase = "indexing"
    await index_snapshot(ws, snapshot_id)
    with session_scope(write=True) as db:
        job = get_job(db,job_id)
        snapshot = owned(db, Snapshot, ws, snapshot_id)
        kb = owned(db, KnowledgeBase, ws, payload["kb_id"])
        snapshot.state = "published"
        kb.active_snapshot_id, kb.status = snapshot.id, "ready"
        kb.pages_indexed = len(snapshot.source_ids)
        from sqlalchemy import func
        kb.chunks_indexed = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.workspace_id == ws, Chunk.source_id.in_(snapshot.source_ids)))
        job = get_job(db,job_id)
        job.completed_items, job.total_items, job.result = 1, 1, {"source_id": source.id, "snapshot_id": snapshot.id}


def product_from_jsonld(data):
    if isinstance(data, list):
        return [p for item in data for p in product_from_jsonld(item)]
    if not isinstance(data, dict):
        return []
    if "@graph" in data:
        return product_from_jsonld(data["@graph"])
    kind = data.get("@type", "")
    if kind == "Product" or isinstance(kind, list) and "Product" in kind:
        return [data]
    return []


async def catalog_job(job_id):
    with session_scope() as db:
        job = get_job(db,job_id)
        ws, payload = job.workspace_id, job.payload
        store = owned(db, Store, ws, payload["store_id"])
        root, store_id = store.website_url, store.id
    origin = urlparse(root).netloc
    _, body, content_type = await safe_fetch(root)
    page = await asyncio.to_thread(extract_page, body, root)
    urls = [root] + [x for x in page["links"] if urlparse(x).netloc == origin and any(word in urlparse(x).path for word in ["/products/", "/product/"])]
    urls = list(dict.fromkeys(urls))[:50]
    seen = set(payload.get("processed_urls", []))
    imported, errors = payload.get("imported", 0), payload.get("item_errors", [])
    for url in urls:
        if url in seen:
            continue
        with session_scope(write=True) as db:
            job = get_job(db,job_id)
            if job.cancel_requested:
                job.state, job.phase = "canceled", "canceled"
                return
            job.phase, job.total_items, job.lease_until = "extracting_products", len(urls), now() + timedelta(minutes=3)
        try:
            from .admission import resource_hold
            await asyncio.to_thread(resource_hold,ws,'usage:catalog-page:'+job_id+':'+url,'crawl_pages',1,store_id)
            final, raw, content_type = await safe_fetch(url)
            if urlparse(final).netloc != origin:
                raise ValueError("Cross-origin product excluded")
            parsed = await asyncio.to_thread(extract_page, raw, final)
            raw_key = await asyncio.to_thread(put_checked, ws, "snapshots", raw, content_type)
            with session_scope(write=True) as db:
                get_job(db,job_id)
                from .metering import stored,record_usage
                stored(db,ws,raw_key,len(raw))
                record_usage(db,ws,'catalog-page:'+job_id+':'+url,'crawl_pages',1,scope_id=store_id)
            candidates = [p for data in parsed["jsonld"] for p in product_from_jsonld(data)]
            for data in candidates:
                offer = data.get("offers", {})
                if isinstance(offer, list):
                    offer = offer[0] if offer else {}
                price_value = offer.get("price")
                if price_value is None or not data.get("name"):
                    continue
                price = Decimal(str(price_value))
                if not price.is_finite() or price < 0 or price > 1_000_000_000:
                    raise ValueError("Invalid product price")
                currency = str(offer.get("priceCurrency", "")).upper()
                if not re.fullmatch("[A-Z]{3}", currency):
                    raise ValueError("Product price currency missing")
                product_url = canonical_url(urljoin(final, data.get("url") or final))
                availability = str(offer.get("availability", "")).lower()
                stock = "out_of_stock" if "outofstock" in availability else "in_stock" if "instock" in availability else "unknown"
                image = data.get("image")
                image = image[0] if isinstance(image, list) and image else image
                image = image.get("url") if isinstance(image, dict) else image
                with session_scope(write=True) as db:
                    get_job(db,job_id)
                    product = db.scalar(select(Product).where(Product.workspace_id == ws, Product.store_id == store_id, Product.canonical_url == product_url))
                    if product and product.provenance.get("manual_override"):
                        continue
                    if not product:
                        product = Product(workspace_id=ws, store_id=store_id, canonical_url=product_url)
                        db.add(product)
                    product.title = str(data["name"])[:300]
                    product.description = BeautifulText(str(data.get("description", "")))[:20000]
                    product.price_minor = int((price * 100).quantize(Decimal("1")))
                    product.currency, product.availability = currency, stock
                    product.image_url = image if isinstance(image, str) and image.startswith("https://") else None
                    product.provenance = {"source": "jsonld", "url": final, "raw_object_key": raw_key, "fetched_at": now().isoformat()}
                    imported += 1
        except (httpx.HTTPError, ValueError, InvalidOperation) as exc:
            errors.append({"url": url, "reason": str(exc)[:250]})
        seen.add(url)
        with session_scope(write=True) as db:
            job = get_job(db,job_id)
            job.completed_items = len(seen)
            job.payload = {**payload, "processed_urls": list(seen), "imported": imported, "item_errors": errors}
        await asyncio.sleep(.1)
    with session_scope(write=True) as db:
        get_job(db,job_id).result = {"imported_or_updated": imported, "item_errors": errors, "pages_examined": len(seen)}


def BeautifulText(value):
    from bs4 import BeautifulSoup
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


async def verify_number_job(job_id):
    import plivo
    with session_scope() as db:
        job = get_job(db,job_id)
        ws, number_id = job.workspace_id, job.payload["number_id"]
        number = owned(db, Number, ws, number_id)
        e164 = number.e164
        from .phone_trials import for_number, pool_credentials
        trial = for_number(db, number_id)
        trial_pool_id = trial.pool_id if trial else None
    from .carrier_config import credentials
    carrier = pool_credentials(trial_pool_id) if trial_pool_id else credentials(number.provider, ws)
    if number.provider=='twilio':
        from .carrier_config import twilio_client
        client=twilio_client(carrier)
        matches=await asyncio.to_thread(client.incoming_phone_numbers.list,phone_number=e164,limit=1)
        if not matches:raise ValueError('Number is not owned by the configured Twilio account')
        with session_scope(write=True) as db:
            get_job(db,job_id)
            number=owned(db,Number,ws,number_id);number.provider_number_id=matches[0].sid;number.status='active';number.can_outbound=bool(matches[0].capabilities.get('voice'));number.can_inbound=number.can_outbound and not trial_pool_id
            get_job(db,job_id).result={'number_id':number.id,'verified':True,'provider':'twilio'}
        return
    client = plivo.RestClient(carrier['auth_id'], carrier['auth_token'])
    response = await asyncio.to_thread(client.numbers.get, e164)
    data = dict(response.__dict__) if not isinstance(response, dict) else response
    with session_scope(write=True) as db:
        get_job(db,job_id)
        number = owned(db, Number, ws, number_id)
        number.status, number.provider_number_id = "active", e164
        # Do not accept browser-supplied inbound capability as proof; use provider number metadata.
        number.can_inbound = bool(data.get("voice_enabled", False))
        number.can_outbound = bool(data.get("voice_enabled", False))
        get_job(db,job_id).result = {"number_id": number.id, "verified": True, "voice_enabled": number.can_inbound}


async def outbound_job(job_id):
    with session_scope(write=True) as db:
        job = get_job(db,job_id)
        call = owned(db, Call, job.workspace_id, job.payload["call_id"])
        if call.state in TERMINAL_STATES:
            return
        if call.state != "created":
            if call.provider_call_id:
                return
            call.failure_code = "unknown_dispatch_outcome"
            settle_call(db, call, 0, "failed")
            raise ValueError("Prior dispatch outcome is unknown; operator reconciliation required before retry")
        call.state = "connecting"
        ws, call_id, mode, destination = call.workspace_id, call.id, call.mode, call.destination
        provider=call.metadata_data.get('provider','plivo')
        caller = settings.plivo_caller_id
        if call.metadata_data.get("number_id"):
            number = owned(db, Number, ws, call.metadata_data["number_id"])
            caller = number.e164
            provider=number.provider
        call.metadata_data={**call.metadata_data,'provider':provider}
        trial_seconds = None
        if mode == 'live':
            from .phone_trials import for_number, call_seconds
            if for_number(db, call.metadata_data.get('number_id')):
                trial_seconds = call_seconds(db, call)
    if mode == "simulation":
        await asyncio.sleep(.4)
        with session_scope(write=True) as db:
            get_job(db,job_id)
            call = owned(db, Call, ws, call_id)
            call.connected_at, call.state = now(), "connected"
            db.add(Turn(workspace_id=ws, call_id=call.id, ordinal=0, speaker="assistant", text_content="Simulation only: this call did not reach the telephone network.", epoch=0))
        await asyncio.sleep(.4)
        with session_scope(write=True) as db:
            get_job(db,job_id)
            call = owned(db, Call, ws, call_id)
            settle_call(db, call, 30000, "completed")
        return
    with session_scope() as db:
        admitted = owned(db, Call, ws, call_id)
        contact_id = admitted.metadata_data.get('contact', {}).get('contact_id')
        if contact_id:
            contact = owned(db, Contact, ws, contact_id)
            if contact.archived or contact.consent != 'granted':
                raise ValueError('Contact permission was revoked before dispatch')
    from .carrier_config import call_credentials, telephony_ready
    if not telephony_ready(ws):
        raise ValueError("Live telephone dispatch is disabled")
    carrier = call_credentials(admitted)
    if provider=='twilio':
        from .carrier_config import twilio_client
        client=twilio_client(carrier);base=settings.media_public_origin.rstrip('/')
        limits = {'time_limit':min(admitted.metadata_data.get('admitted_max_seconds',300),trial_seconds or 900)}
        result=await asyncio.to_thread(client.calls.create,from_=caller,to=destination,url=base+'/v1/provider-webhooks/twilio/answer?call_id='+call_id,status_callback=base+'/v1/provider-webhooks/twilio/status?call_id='+call_id,status_callback_event=['completed'], **limits)
        with session_scope(write=True) as db:
            get_job(db,job_id)
            call=owned(db,Call,ws,call_id)
            if call.provider_call_id and call.provider_call_id!=result.sid:raise ValueError('Twilio returned a conflicting call identity')
            call.provider_call_id=result.sid
            if call.state=='connecting':call.state='ringing'
        return
    import plivo
    client = plivo.RestClient(carrier['auth_id'], carrier['auth_token'])
    base = settings.media_public_origin.rstrip("/")
    result = await asyncio.to_thread(client.calls.create, from_=caller, to_=destination, answer_url=base + "/v1/provider-webhooks/plivo/answer?call_id=" + call_id, answer_method="POST", hangup_url=base + "/v1/provider-webhooks/plivo/hangup?call_id=" + call_id, hangup_method="POST",time_limit=admitted.metadata_data.get('admitted_max_seconds',300))
    provider_id = result.get("request_uuid") if isinstance(result, dict) else getattr(result, "request_uuid", None)
    if isinstance(provider_id, list):
        provider_id = provider_id[0]
    with session_scope(write=True) as db:
        get_job(db,job_id)
        call = owned(db, Call, ws, call_id)
        # An answer callback may have bound the canonical leg before create() returns.
        if not call.provider_call_id:call.provider_call_id = str(provider_id) if provider_id else None
        elif provider_id:call.metadata_data={**call.metadata_data,'provider_request_id':str(provider_id)}
        if call.state=='connecting':call.state = "ringing"


TERMINAL_STATES = {"completed", "failed", "canceled", "no_answer", "busy"}


def campaign_ready_at(campaign, timestamp):
    from zoneinfo import ZoneInfo
    local=timestamp.astimezone(ZoneInfo(campaign.timezone))
    start=campaign.policy.get('calling_hour_start',9)
    end=campaign.policy.get('calling_hour_end',21)
    if local.hour<start:return local.replace(hour=start,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    if local.hour>=end:return (local+timedelta(days=1)).replace(hour=start,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    return timestamp


async def campaign_job(job_id):
    with session_scope() as db:
        job=get_job(db,job_id);ws=job.workspace_id;campaign_id=job.payload['campaign_id']
    while True:
        children=[]
        with session_scope(write=True) as db:
            get_job(db,job_id)
            campaign=db.scalar(select(Campaign).where(Campaign.workspace_id==ws,Campaign.id==campaign_id).with_for_update().execution_options(populate_existing=True))
            job=get_job(db,job_id)
            if job.cancel_requested:
                campaign.state='canceled';return
            if campaign.state in {'paused','canceled','completed'}:return
            ready=max(now(),campaign.scheduled_at or now())
            # Simulation is deterministic and does not call a person; hours constrain live calls.
            if campaign.mode=='live':ready=campaign_ready_at(campaign,ready)
            if ready>now()+timedelta(seconds=1):
                campaign.state='scheduled';job.state='queued';job.available_at=ready;job.lease_until=None;return
            campaign.state='running'
            attempts=list(db.scalars(select(Attempt).where(Attempt.workspace_id==ws,Attempt.campaign_id==campaign_id)))
            bycontact={};active=[];calls={}
            for attempt in attempts:
                call=owned(db,Call,ws,attempt.call_id);calls[call.id]=call
                if attempt.state=='running' and call.state in TERMINAL_STATES:
                    attempt.state='completed' if call.state=='completed' else 'failed';attempt.outcome=call.state
                if attempt.state=='running':active.append(attempt)
                previous=bycontact.get(attempt.contact_identity)
                if not previous or attempt.attempt_index>previous.attempt_index:bycontact[attempt.contact_identity]=attempt
            pending=[];finished=0;next_retry=None
            for contact in campaign.contacts:
                identity=hashlib.sha256(contact['phone'].encode()).hexdigest();previous=bycontact.get(identity)
                if previous is None:pending.append((identity,contact,1));continue
                if previous.state=='running':continue
                call=calls[previous.call_id]
                if previous.outcome in {'no_answer','busy'} and previous.attempt_index<campaign.max_attempts:
                    retry_at=(call.ended_at or now())+timedelta(seconds=campaign.policy.get('retry_delay_seconds',300))
                    if retry_at<=now():pending.append((identity,contact,previous.attempt_index+1))
                    else:next_retry=min(next_retry,retry_at) if next_retry else retry_at
                else:finished+=1
            job.completed_items,job.total_items=finished,len(campaign.contacts)
            if finished==len(campaign.contacts):campaign.state='completed';return
            call_ids=list(calls)
            spent=sum(-x.amount_minor for x in db.scalars(select(Ledger).where(Ledger.workspace_id==ws,Ledger.call_id.in_(call_ids),Ledger.amount_minor<0))) if call_ids else 0
            held=sum(x.amount_minor for x in db.scalars(select(Reservation).where(Reservation.workspace_id==ws,Reservation.call_id.in_(call_ids),Reservation.state=='active'))) if call_ids else 0
            remaining=campaign.budget_minor-spent-held
            capacity=max(0,campaign.concurrency-len(active))
            for identity,contact,index in pending[:capacity]:
                if remaining<=0:break
                version=owned(db,AgentVersion,ws,campaign.agent_version_id)
                budget=min(remaining,500)
                call=Call(workspace_id=ws,agent_version_id=version.id,agent_name=version.config['name'],direction='outbound',transport='pstn',mode=campaign.mode,destination=contact['phone'],metadata_data={'number_id':campaign.number_id,'budget_minor':budget,'campaign_id':campaign.id,'contact':contact,'variables':contact.get('variables',{})})
                db.add(call);db.flush()
                from .admission import admit_voice as admit_plan_voice
                admit_plan_voice(db,call,version.config)
                remaining-=budget
                db.add(Attempt(workspace_id=ws,campaign_id=campaign_id,contact_identity=identity,attempt_index=index,call_id=call.id,state='running'))
                children.append(enqueue(db,ws,'outbound',{'call_id':call.id}).id)
            if not children:
                if remaining<=0 and not active:
                    campaign.state='paused';job.result={'reason':'campaign_budget_exhausted','spent_minor':spent};return
                job.state='queued';job.lease_until=None;job.available_at=now()+timedelta(seconds=3) if active else next_retry or now()+timedelta(seconds=3)
                return
            job.lease_until=now()+timedelta(minutes=3)
        await asyncio.gather(*(execute_job(child) for child in children))


async def hangup_job(job_id):
    import plivo
    with session_scope() as db:
        job = get_job(db,job_id)
        call = owned(db, Call, job.workspace_id, job.payload["call_id"])
        call_id = call.provider_call_id
        provider=call.metadata_data.get('provider','plivo')
        ws = call.workspace_id
    if not call_id:
        raise ValueError("Provider leg ID unavailable")
    from .carrier_config import call_credentials
    carrier = call_credentials(call)
    if provider=='twilio':
        from .carrier_config import twilio_client
        client=twilio_client(carrier)
        await asyncio.to_thread(client.calls(call_id).update,status='completed');return
    client = plivo.RestClient(carrier['auth_id'], carrier['auth_token'])
    await asyncio.to_thread(client.calls.delete, call_id)


async def http_tool_job(job_id):
    from .http_tools import perform
    with session_scope() as db:execution_id=get_job(db,job_id).payload['execution_id']
    await perform(execution_id)


from .number_provisioning import allocation_job
from .agent_deletion import purge_job
from .invoices import invoice_job
from .refund_routes import refund_job
from .billing_subscriptions import create_job as subscription_job,cancel_job as subscription_cancel_job

from .transfers import transfer_job

HANDLERS = {"call_transfer":transfer_job,"billing_subscription_create":subscription_job,"billing_subscription_cancel":subscription_cancel_job,"billing_refund":refund_job,"invoice_pdf":invoice_job,"agent_delete":purge_job,"http_tool":http_tool_job,"crawl": crawl_job, "document": document_job, "catalog": catalog_job, "outbound": outbound_job,
            "campaign": campaign_job, "verify_number": verify_number_job, "hangup": hangup_job,
            "phone_number_allocate": allocation_job}


async def execute_job(job_id, lease_token=None):
    from .db import uid
    def begin():
        nonlocal lease_token
        with session_scope(write=True) as db:
            job = db.scalar(select(Job).where(Job.id==job_id).with_for_update())
            if not job or job.state in {'completed','canceled'}: return
            if lease_token is not None:
                if job.state!='running' or job.lease_token!=lease_token: return
            else:
                if job.state=='running' and job.lease_token and job.lease_until and job.lease_until>now(): return
                lease_token=uid();job.lease_token=lease_token
            job.state,job.phase,job.attempts,job.lease_until='running','starting',job.attempts+1,now()+timedelta(minutes=3)
            return job.kind
    kind=await asyncio.to_thread(begin)
    if kind is None:return
    context=claim.set((job_id,lease_token))
    async def heartbeat():
        while True:
            await asyncio.sleep(JOB_HEARTBEAT_SECONDS)
            def renew():
                with session_scope(write=True) as db:
                    job=get_job(db,job_id)
                    if job.state=='running':job.lease_until=now()+timedelta(minutes=3)
            await asyncio.to_thread(renew)
    async def perform():await HANDLERS[kind](job_id)
    work=asyncio.create_task(perform())
    monitor=asyncio.create_task(heartbeat())
    try:
        done,_=await asyncio.wait({work,monitor},return_when=asyncio.FIRST_COMPLETED)
        if monitor in done:await monitor
        await work
        def complete():
            with session_scope(write=True) as db:
                job=get_job(db,job_id)
                if job.state=='running':
                    job.state,job.phase,job.error='completed','completed',None
                    emit(db,job.workspace_id,'job.completed',{'job_id':job.id})
                job.lease_until=None;job.updated_at=now()
        await asyncio.to_thread(complete)
    except LeaseLost:
        log.warning('Job lease moved to another worker: %s',job_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception('Job failed: %s',job_id)
        def fail():
            with session_scope(write=True) as db:
                job=db.scalar(select(Job).where(Job.id==job_id).with_for_update())
                if not job or job.lease_token!=lease_token:return
                job.state,job.phase,job.error,job.updated_at,job.lease_until='failed','failed',str(exc)[:1000],now(),None
                if kind=='crawl':
                    kb=owned(db,KnowledgeBase,job.workspace_id,job.payload['kb_id'])
                    kb.status='ready' if kb.active_snapshot_id else 'failed'
                if kind=='outbound':
                    call=owned(db,Call,job.workspace_id,job.payload['call_id'])
                    if call.state not in TERMINAL_STATES:
                        call.failure_code='provider_dispatch_failed';settle_call(db,call,0,'failed')
                emit(db,job.workspace_id,'job.failed',{'job_id':job.id,'kind':kind})
        await asyncio.to_thread(fail)
    finally:
        for task in (work,monitor):
            if not task.done():task.cancel()
        await asyncio.gather(work,monitor,return_exceptions=True)
        claim.reset(context)


async def deliver_webhook(delivery_id):
    from .knowledge import validate_public_url
    from .network import PublicTransport
    with session_scope() as db:
        delivery = db.get(Delivery, delivery_id)
        endpoint = owned(db, WebhookEndpoint, delivery.workspace_id, delivery.endpoint_id)
        if not endpoint.enabled:
            delivery.state = 'canceled'
            return
        url, secret, payload = endpoint.url, decrypt(endpoint.secret), delivery.payload
    status, error = None, None
    try:
        await validate_public_url(url)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False, transport=PublicTransport()) as client:
            response = await client.post(url, content=body, headers={"Content-Type": "application/json", "X-Studio-Timestamp": timestamp, "X-Studio-Signature": "v1=" + signature, "X-Studio-Event": payload["id"]})
            status = response.status_code
    except Exception as exc:
        error = str(exc)[:300]
    with session_scope(write=True) as db:
        delivery = db.get(Delivery, delivery_id)
        delivery.attempt += 1
        delivery.http_status, delivery.error = status, error
        delivery.state = "success" if status and 200 <= status < 300 else "dead_letter" if delivery.attempt >= 6 else "pending"
        delivery.next_attempt_at = now() + timedelta(seconds=min(3600, 2 ** delivery.attempt * 10))


def browser_session_maintenance():
    # Only the API process knows which browser calls it currently owns.
    from .media import owners
    with session_scope(write=True) as db:
        for call in db.scalars(select(Call).where(Call.transport=='browser',Call.state.in_(['created','connected','ending']),Call.created_at<now()-timedelta(minutes=20))):
            if call.id not in owners:
                call.failure_code='orphaned_browser_session';settle_call(db,call,call.connected_ms,'failed')


def maintenance_sync(local_browser_sessions=True):
    from .models import Recording,Preview,ToolExecution,AuthSession,OAuthAttempt,AccountToken,Notification,UsageRecord
    from sqlalchemy import delete
    with session_scope() as db:
        expired=[(r.id,r.workspace_id,r.object_key) for r in db.scalars(select(Recording).where(Recording.deleted_at.is_(None),Recording.expires_at<=now()).limit(20))]
    for recording_id,ws,key in expired:
        get_store().delete(ws,key)
        with session_scope(write=True) as db:
            db.get(Recording,recording_id).deleted_at=now()
            from .metering import removed
            removed(db,ws,key)
    with session_scope(write=True) as db:
        db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
        db.execute(delete(OAuthAttempt).where(OAuthAttempt.expires_at < now() - timedelta(days=1)))
        db.execute(delete(AccountToken).where(AccountToken.expires_at < now() - timedelta(days=1)))
        db.execute(delete(Notification).where(Notification.created_at < now() - timedelta(days=90)))
        db.execute(delete(UsageRecord).where(UsageRecord.created_at < now() - timedelta(days=32)))
        db.execute(delete(Preview).where(Preview.expires_at<now()))
        for execution in db.scalars(select(ToolExecution).where(ToolExecution.state=='running',ToolExecution.created_at<now()-timedelta(minutes=5))):
            execution.state='unknown';execution.result={'error':'The worker lost the result. Reconcile before repeating a side effect.'}
    if local_browser_sessions:browser_session_maintenance()
    from .billing_subscriptions import maintenance as billing_maintenance
    billing_maintenance()


async def maintenance(local_browser_sessions=True):
    await asyncio.to_thread(maintenance_sync,local_browser_sessions)
    from .website_routes import schedule_updates
    def update_websites():
        with session_scope(write=True) as db: schedule_updates(db)
    await asyncio.to_thread(update_websites)
    from .phone_trials import maintenance as trial_maintenance
    await asyncio.to_thread(trial_maintenance)


def claim_dispatch(claim_jobs=True, claim_deliveries=True):
    from .db import uid
    with session_scope(write=True) as db:
        claimed=None
        if claim_jobs:
            active_job=aliased(Job)
            resources={'kb_id':KnowledgeBase,'store_id':Store,'campaign_id':Campaign}
            busy_resource=or_(*(select(active_job.id).where(active_job.workspace_id==Job.workspace_id,active_job.id!=Job.id,active_job.state=='running',active_job.lease_until>now(),active_job.payload[key].as_string()==Job.payload[key].as_string()).exists() for key in resources))
            skipped=[]
            for _ in range(20):
                job=db.scalar(select(Job).where(or_(Job.state=='queued',(Job.state=='running') & (Job.lease_until<now())),or_(Job.available_at.is_(None),Job.available_at<=now()),~busy_resource,Job.id.not_in(skipped)).order_by(case((Job.state=='running',0),else_=1),Job.created_at,Job.id).limit(1).with_for_update(skip_locked=True))
                if not job:break
                skipped.append(job.id)
                not_before=job.result.get('not_before')
                if not_before and datetime.fromisoformat(not_before).replace(tzinfo=timezone.utc)>now():
                    job.available_at=datetime.fromisoformat(not_before).replace(tzinfo=timezone.utc);continue
                blocked=False
                for key,model in resources.items():
                    resource_id=job.payload.get(key)
                    if not resource_id:continue
                    resource=db.scalar(select(model).where(model.workspace_id==job.workspace_id,model.id==resource_id).with_for_update(skip_locked=True))
                    if resource is None:
                        blocked=True;break
                    active=list(db.scalars(select(Job).where(Job.workspace_id==job.workspace_id,Job.id!=job.id,Job.state=='running',Job.lease_until>now())))
                    if any(other.payload.get(key)==resource_id for other in active):
                        blocked=True;break
                    if key=='kb_id' and resource.status=='deleting':
                        job.state='canceled';job.cancel_requested=True;blocked=True;break
                if blocked:continue
                token=uid();job.state,job.lease_token,job.lease_until='running',token,now()+timedelta(minutes=3)
                claimed=(job.id,token);break
        delivery=None
        if claim_deliveries:
            delivery=db.scalar(select(Delivery).where(or_(Delivery.state=='pending',Delivery.state=='delivering'),Delivery.next_attempt_at<=now()).order_by(Delivery.created_at).limit(1).with_for_update(skip_locked=True))
            if delivery:
                delivery.state='delivering';delivery.next_attempt_at=now()+timedelta(minutes=3)
        return claimed,delivery.id if delivery else None


async def worker_loop(stop, local_browser_sessions=True):
    jobs,deliveries=set(),set()
    maintenance_task=None;next_maintenance=0
    mail_task = None
    rotation_task = None
    billing_task = None
    from .readiness import heartbeat
    worker_identity = __import__('uuid').uuid4().hex
    next_heartbeat = 0
    def drain(tasks):
        for task in list(tasks):
            if task.done():
                tasks.remove(task)
                try:task.result()
                except asyncio.CancelledError:pass
                except Exception:log.exception('Worker task failed')
    try:
        while not stop.is_set():
            if time.monotonic() >= next_heartbeat:
                try:
                    await asyncio.to_thread(heartbeat, worker_identity)
                except Exception:
                    log.warning('Worker heartbeat unavailable')
                next_heartbeat = time.monotonic() + 5
            drain(jobs);drain(deliveries)
            if billing_task is not None and billing_task.done():
                drain({billing_task});billing_task=None
            if billing_task is None:
                from .billing_inbox import process_inbox
                billing_task=asyncio.create_task(process_inbox())
            if rotation_task is not None and rotation_task.done():
                drain({rotation_task});rotation_task=None
            if rotation_task is None:
                from .key_rotation import process_rotation_batch
                rotation_task=asyncio.create_task(asyncio.to_thread(process_rotation_batch))
            if mail_task is not None and mail_task.done():
                drain({mail_task})
                mail_task = None
            if mail_task is None:
                from .mail_outbox import process_outbox
                mail_task = asyncio.create_task(asyncio.to_thread(process_outbox))
            if maintenance_task and maintenance_task.done():
                drain({maintenance_task});maintenance_task=None
            if time.monotonic()>=next_maintenance and maintenance_task is None:
                maintenance_task=asyncio.create_task(maintenance() if local_browser_sessions else maintenance(False));next_maintenance=time.monotonic()+60
            try:
                while not stop.is_set() and (len(jobs)<settings.worker_concurrency or not deliveries):
                    job,delivery=await asyncio.to_thread(claim_dispatch,claim_jobs=len(jobs)<settings.worker_concurrency,claim_deliveries=not deliveries)
                    if job:jobs.add(asyncio.create_task(execute_job(*job)))
                    if delivery:deliveries.add(asyncio.create_task(deliver_webhook(delivery)))
                    if not job and not delivery:break
            except asyncio.CancelledError:raise
            except Exception:log.exception('Dispatcher iteration failed')
            try:await asyncio.wait_for(stop.wait(),timeout=settings.worker_poll_seconds)
            except asyncio.TimeoutError:pass
    finally:
        if billing_task is not None:await asyncio.shield(billing_task)
        if mail_task is not None:
            # A thread sending SMTP cannot be cancelled safely; drain its bounded delivery.
            await asyncio.shield(mail_task)
        if rotation_task is not None:await asyncio.shield(rotation_task)
        pending=jobs|deliveries|({maintenance_task} if maintenance_task else set())
        for task in pending:task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
        try:
            await asyncio.to_thread(heartbeat, worker_identity, 'stopped')
        except Exception:
            log.warning('Worker shutdown heartbeat unavailable')
