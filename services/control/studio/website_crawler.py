"""Bounded concurrent crawling, cooperative stop and atomic knowledge publication."""
import asyncio
import hashlib
import json
import re
from contextlib import suppress
from xml.etree.ElementTree import ParseError
from collections import deque
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import httpx
from sqlalchemy import select, func
from . import knowledge as k
from .job_control import get_job, check_lease, resource_slot
from .config import settings
from .db import session_scope, now
from .models import KnowledgeBase, Snapshot, Source, Chunk, Job, Store
from .domain import owned
from .storage import get_store,put_checked
from .website_extraction import origin, sitemap_locations, commerce_facts, save_products, rendered_html


class CrawlStopped(Exception):
    pass


def check_stop(job_id):
    with session_scope() as db:
        job = get_job(db,job_id)
        if job.cancel_requested or job.state == 'canceled':
            raise CrawlStopped()


def mark_stopped(job_id):
    with session_scope(write=True) as db:
        job = get_job(db,job_id)
        job.state, job.phase, job.lease_until, job.updated_at = 'canceled', 'canceled', None, now()
        kb = db.get(KnowledgeBase, job.payload['kb_id'])
        kb.status = 'ready' if kb.active_snapshot_id else 'canceled'


async def crawl(job_id):
    # Stop remains responsive while waiting on network, browser rendering or an
    # embedding batch. Cancellation never promotes a partially built snapshot.
    stopped = asyncio.Event()
    heartbeat = 0.0
    async def watch():
        nonlocal heartbeat
        while not stopped.is_set():
            await asyncio.to_thread(check_stop, job_id)
            if asyncio.get_running_loop().time() >= heartbeat:
                def renew():
                    with session_scope(write=True) as db:
                        job = get_job(db,job_id)
                        if job.state == 'running': job.lease_until = now() + timedelta(minutes=3)
                await asyncio.to_thread(renew)
                heartbeat = asyncio.get_running_loop().time() + 30
            try:
                await asyncio.wait_for(stopped.wait(), timeout=.2)
            except asyncio.TimeoutError:
                pass
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,
                                 transport=k.PublicTransport(), limits=httpx.Limits(max_connections=settings.crawl_concurrency)) as client:
        token = k.fetch_context.set({'client': client, 'before_request': None})
        work, monitor = asyncio.create_task(_crawl(job_id)), asyncio.create_task(watch())
        try:
            done, _ = await asyncio.wait({work, monitor}, return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                await monitor
            await work
        except CrawlStopped:
            work.cancel()
            with suppress(asyncio.CancelledError, CrawlStopped):
                await work
            await asyncio.to_thread(mark_stopped, job_id)
        finally:
            stopped.set()
            for task in (work, monitor):
                if not task.done(): task.cancel()
            await asyncio.gather(work, monitor, return_exceptions=True)
            k.fetch_context.reset(token)


async def _crawl(job_id):
    check_stop(job_id)
    with session_scope() as db:
        job = get_job(db,job_id)
        ws, payload = job.workspace_id, dict(job.payload)
        kb = owned(db, KnowledgeBase, ws, payload['kb_id'])
        root, kb_id = k.canonical_url(kb.website_url), kb.id
        maximum = min(1000, max(1, payload.get('max_pages', 100)))
    await k.validate_public_url(root)
    root_origin = origin(root)
    robot = RobotFileParser()
    try:
        _, raw, _ = await k.safe_fetch(urljoin(root, '/robots.txt'), 200000, same_origin=root_origin)
        robot.parse(raw.decode(errors='replace').splitlines())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {404, 410}:
            raise ValueError('Crawl permission could not be established from robots.txt') from exc
        robot.parse([])
    delay = max(.25, float(robot.crawl_delay(k.USER_AGENT) or robot.crawl_delay('*') or 0))
    rate = robot.request_rate(k.USER_AGENT) or robot.request_rate('*')
    if rate: delay = max(delay, rate.seconds / max(1, rate.requests))
    if delay > 60:
        raise ValueError('Site requests a crawl interval above the supported 60 seconds')
    last_fetch, blocked_until, pacing = 0.0, 0.0, asyncio.Lock()
    async def pace():
        nonlocal last_fetch
        async with pacing:
            await asyncio.sleep(max(0, delay - (asyncio.get_running_loop().time() - last_fetch), blocked_until - asyncio.get_running_loop().time()))
            last_fetch = asyncio.get_running_loop().time()
    k.fetch_context.get()['before_request'] = pace

    async def fetch(url, size=k.MAX_PAGE_BYTES):
        nonlocal blocked_until
        for attempt in range(3):
            await asyncio.to_thread(check_stop,job_id)
            try:
                return await k.safe_fetch(url, size, same_origin=root_origin, permit=lambda u: robot.can_fetch(k.USER_AGENT, u), redirect_delay=delay)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {429, 503} or attempt == 2: raise
                retry_after = exc.response.headers.get('retry-after', '')
                try: wait = float(retry_after)
                except ValueError:
                    try: wait = (parsedate_to_datetime(retry_after).astimezone(timezone.utc) - now()).total_seconds()
                    except (ValueError, TypeError, OverflowError): wait = 2 ** (attempt + 1)
                if wait > 60: raise  # Never retry before a site's longer requested interval.
                blocked_until = max(blocked_until, asyncio.get_running_loop().time() + max(1, wait))
                await asyncio.sleep(max(1, wait))

    queue = deque(payload.get('queue', [root]))
    visited = set(payload.get('visited', []))
    source_ids, failures = list(payload.get('source_ids', [])), list(payload.get('failures', []))
    excluded = set(payload.get('excluded_urls', []))
    if not payload.get('discovered_sitemaps'):
        maps = deque((robot.site_maps() or []) + [urljoin(root, '/sitemap.xml')])
        seen_maps = set()
        while maps and len(seen_maps) < 30:
            url = maps.popleft()
            if url in seen_maps or origin(url) != root_origin or not robot.can_fetch(k.USER_AGENT, url): continue
            seen_maps.add(url)
            try:
                _, body, _ = await fetch(url)
                links, indexes = sitemap_locations(body)
                maps.extend(x for x in indexes if origin(x) == root_origin)
                for x in links[:maximum * 10]:
                    candidate = k.canonical_url(x)
                    if origin(candidate) == root_origin and candidate not in queue and len(queue) < maximum * 10:
                        queue.append(candidate)
            except (httpx.HTTPError, ValueError, ParseError):
                pass
    with session_scope(write=True) as db:
        store = db.scalar(select(Store).where(Store.workspace_id == ws, Store.website_url == root))
        if not store:
            store = Store(workspace_id=ws, website_url=root, name=kb.name)
            db.add(store); db.flush()
        store_id = store.id
    with session_scope() as db:
        hashes = set(db.scalars(select(Source.content_hash).where(Source.workspace_id == ws, Source.id.in_(source_ids))))
    duplicates, rendered, reused = payload.get('duplicates', 0), payload.get('rendered', 0), 0
    async def process_page(url):
        from .admission import resource_hold
        meter_operation='crawl-page:'+job_id+':'+url
        await asyncio.to_thread(resource_hold,ws,'usage:'+meter_operation,'crawl_pages',1,kb_id)
        final, body, mime = await fetch(url)
        await asyncio.to_thread(check_stop,job_id)
        if origin(final)!=root_origin:raise ValueError('Cross-origin redirect excluded')
        if 'html' not in mime.lower():return None
        page=await asyncio.to_thread(k.extract_page,body,final)
        warnings=[];did_render=False
        if payload.get('render_js') and (len(page['text'].split())<35 or payload.get('render_all')):
            try:
                async with resource_slot('render',settings.render_concurrency):
                    body=await rendered_html(final,robot,delay)
                if len(body)>k.MAX_PAGE_BYTES:raise ValueError('Rendered page exceeds size limit')
                page=await asyncio.to_thread(k.extract_page,body,final);did_render=True
            except Exception:
                warnings.append({'url':url,'reason':'Dynamic rendering failed; static content was retained'})
        await asyncio.to_thread(check_stop,job_id)
        def extract():
            facts=commerce_facts(page,final)
            text=page['text']+('\nStructured website product evidence (untrusted data):\n'+json.dumps(facts,ensure_ascii=False) if facts else '')
            if page.get('sections'):text+='\nIndexed website sections:\n'+json.dumps(page['sections'])
            if not text.strip():raise ValueError('No readable page content')
            hashed=hashlib.sha256(text.encode()).hexdigest();canonical=k.canonical_url(final)
            with session_scope() as db:
                row=db.scalar(select(Source).where(Source.workspace_id==ws,Source.kb_id==kb_id,Source.canonical_url==canonical,Source.content_hash==hashed))
                return facts,text,hashed,canonical,bool(row),row.raw_object_key if row else None
        facts,text,hashed,canonical,existing,raw_key=await asyncio.to_thread(extract)
        if not existing:
            raw_key=await asyncio.to_thread(lambda:put_checked(ws,'snapshots',body,mime))
        return {'page':page,'facts':facts,'text':text,'hash':hashed,'canonical':canonical,'raw_key':raw_key,'raw_size':len(body),'reused':existing,'rendered':did_render,'warnings':warnings,'meter_operation':meter_operation}

    def persist(prepared):
        with session_scope(write=True) as db:
            job=get_job(db,job_id)
            if job.cancel_requested:raise CrawlStopped()
            source=k.add_source(db,ws,kb_id,prepared['canonical'],prepared['page']['title'],prepared['text'],prepared['raw_key'])
            from .metering import stored,record_usage
            if not prepared['reused']:stored(db,ws,prepared['raw_key'],prepared['raw_size'])
            record_usage(db,ws,prepared['meter_operation'],'crawl_pages',1,scope_id=kb_id)
            source.fetched_at=now()
            save_products(db,ws,store_id,source.id,prepared['facts'])
            return source.id

    pending={}
    try:
        while (queue or pending) and len(source_ids)<maximum:
            await asyncio.to_thread(check_stop,job_id)
            while queue and len(pending)<min(settings.crawl_concurrency,maximum-len(source_ids)) and len(visited)<maximum*4:
                url=queue.popleft()
                if url in visited or url in excluded:continue
                visited.add(url)
                if not robot.can_fetch(k.USER_AGENT,url):
                    failures.append({'url':url,'reason':'robots.txt excludes this URL'});continue
                pending[asyncio.create_task(process_page(url))]=url
            if not pending:break
            def progress():
                with session_scope(write=True) as db:
                    job=get_job(db,job_id)
                    job.phase,job.total_items,job.updated_at,job.lease_until='fetching',maximum,now(),now()+timedelta(minutes=3)
            await asyncio.to_thread(progress)
            done,_=await asyncio.wait(pending,return_when=asyncio.FIRST_COMPLETED)
            for task in sorted(done,key=lambda task:pending[task]):
                await asyncio.to_thread(check_stop,job_id)
                url=pending.pop(task)
                try:
                    prepared=task.result()
                    if prepared is not None:
                        failures.extend(prepared['warnings']);rendered+=int(prepared['rendered']);reused+=int(prepared['reused'])
                        source_id=await asyncio.to_thread(persist,prepared)
                        if prepared['hash'] not in hashes:
                            source_ids.append(source_id);hashes.add(prepared['hash'])
                        else:duplicates+=1
                        candidates=[x for x in prepared['page']['links'] if origin(x)==root_origin and not re.search(r'\.(jpg|png|gif|zip|mp4|svg|webp|pdf|css|js)$',urlparse(x).path,re.I)]
                        candidates.sort(key=lambda x:0 if any(word in x.lower() for word in ['policy','refund','shipping','contact','faq','product','service','pricing']) else 1)
                        for candidate in candidates:
                            if candidate not in visited and candidate not in queue and len(queue)<maximum*10:queue.append(candidate)
                except (httpx.HTTPError,ValueError) as exc:
                    failures.append({'url':url,'reason':str(exc)[:300]})
                inflight=set(pending.values())
                def checkpoint():
                    with session_scope(write=True) as db:
                        job=get_job(db,job_id)
                        job.payload={**payload,'queue':sorted(inflight)+list(queue),'visited':sorted(visited-inflight),'source_ids':list(source_ids),'failures':failures[-200:],'discovered_sitemaps':True,'duplicates':duplicates,'rendered':rendered}
                        job.completed_items=len(source_ids)
                await asyncio.to_thread(checkpoint)
    finally:
        for task in pending:task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
    check_stop(job_id)
    if not source_ids: raise ValueError('No pages could be indexed; inspect crawl permissions and errors')
    with session_scope(write=True) as db:
        old = db.get(Snapshot, db.get(KnowledgeBase, kb_id).active_snapshot_id) if kb.active_snapshot_id else None
        unchanged = bool(old and set(old.source_ids) == set(source_ids))
        if unchanged: snapshot_id = old.id
        else:
            revision = (db.scalar(select(func.max(Snapshot.revision)).where(Snapshot.workspace_id == ws, Snapshot.kb_id == kb_id)) or 0) + 1
            snapshot = Snapshot(workspace_id=ws, kb_id=kb_id, revision=revision, source_ids=source_ids)
            db.add(snapshot); db.flush(); snapshot_id = snapshot.id
        get_job(db,job_id).phase = 'indexing'
    if not unchanged: await k.index_snapshot(ws, snapshot_id)
    with session_scope(write=True) as db:
        # Serialize cancellation and publication: a successful stop wins before
        # publication, while a completed publication is already terminal.
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        check_lease(job)
        if job.cancel_requested: raise CrawlStopped()
        kb = owned(db, KnowledgeBase, ws, kb_id)
        snapshot = owned(db, Snapshot, ws, snapshot_id)
        snapshot.state = 'published'
        kb.active_snapshot_id, kb.status, kb.pages_indexed = snapshot.id, 'ready', len(source_ids)
        kb.chunks_indexed = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.workspace_id == ws, Chunk.source_id.in_(source_ids)))
        corpus = '\n'.join(db.scalars(select(Source.text_content).where(Source.workspace_id == ws, Source.id.in_(source_ids)))).lower()
        kb.assessment = {topic: 'covered' if any(word in corpus for word in words) else 'missing' for topic, words in {
            'products':['product','service'], 'pricing':['price','₹','inr','usd'], 'hours':['opening hours','business hours'], 'contact':['contact','@','telephone'], 'shipping':['shipping','delivery'], 'refunds':['refund','returns'], 'appointments':['appointment','book a slot']}.items()}
        job.result = {'kb_id': kb_id, 'snapshot_id': snapshot_id, 'failures': failures[-200:], 'pages': kb.pages_indexed, 'chunks': kb.chunks_indexed,
                      'duplicates': duplicates, 'reused_pages': reused, 'unchanged': unchanged, 'rendered_pages': rendered, 'remaining_urls': len(queue) + len(pending), 'coverage': 'limited' if queue or pending else 'discovered-pages-complete'}
        from .website_routes import connect_snapshot
        if not unchanged: connect_snapshot(db, ws, kb_id, snapshot_id)
        job.state, job.phase, job.lease_until = 'completed', 'completed', None
