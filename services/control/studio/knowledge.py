from contextvars import ContextVar
from collections import Counter, deque
from datetime import timedelta
from urllib.parse import urlparse, urlunparse, urljoin, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import httpcore
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, func
from .config import settings
from .db import session_scope, now, uid, as_dict
from .models import KnowledgeBase, Source, Chunk, Snapshot, Job, Store, Product
from .domain import owned
from .storage import get_store
from .retrieval import vector_configured, Qdrant, embed
from .network import PublicTransport

USER_AGENT = "VoiceStudioKnowledgeBot/0.1"
MAX_PAGE_BYTES = 3_000_000
# Per-crawl pooled transport; all requests retain DNS pinning and origin checks.
fetch_context = ContextVar("crawl_fetch_context", default=None)


def canonical_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().encode("idna").decode()
    port = parsed.port
    netloc = host + (f":{port}" if port and port not in {80, 443} else "")
    path = re.sub("/+", "/", parsed.path).rstrip("/") or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query) if not k.startswith("utm_") and k not in {"fbclid", "gclid"}))
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


async def validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise ValueError("Only public HTTP/HTTPS URLs on standard ports are allowed")
    if settings.public_network_mode == 'proxy':
        from .network import resolve_public_ips
        try:
            await resolve_public_ips(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
        except (OSError, httpcore.ConnectError, httpx.HTTPError) as exc:
            raise ValueError('Website public address could not be verified through the configured proxy') from exc
        return
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError('Website hostname could not be resolved; check the URL and try again') from exc
    if not addresses:
        raise ValueError("URL hostname has no address")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global or ip.is_multicast:
            raise ValueError("Private, local and metadata destinations are not allowed")


async def safe_fetch(url, max_bytes=MAX_PAGE_BYTES, client=None, same_origin=None, permit=None, redirect_delay=0):
    # Deployment egress rules additionally block private/metadata networks at connection time.
    current = url
    context = fetch_context.get()
    client = client or (context["client"] if context else None)
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,transport=PublicTransport())
    try:
        for _ in range(5):
            if same_origin and (urlparse(current).scheme, urlparse(current).netloc) != same_origin:
                raise ValueError('Cross-origin redirect excluded')
            if permit and not permit(current):
                raise ValueError('robots.txt excludes this URL')
            await validate_public_url(current)
            if context and context.get("before_request"):
                await context["before_request"]()
            async with client.stream("GET", current, headers={"User-Agent": USER_AGENT}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    current = urljoin(current, response.headers["location"])
                    if not (context and context.get("before_request")):
                        await asyncio.sleep(redirect_delay)
                    continue
                response.raise_for_status()
                chunks, total = [], 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Source exceeds extraction size limit")
                    chunks.append(chunk)
                return current, b"".join(chunks), response.headers.get("content-type", "")
        raise ValueError("Too many redirects")
    finally:
        if own:
            await client.aclose()


def extract_page(body, url):
    soup = BeautifulSoup(body, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else urlparse(url).path
    linked_data = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            linked_data.append(json.loads(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            pass
    links = []
    for a in soup.select('a[href]'):
        try:
            candidate = urljoin(url, a['href'])
            if urlparse(candidate).scheme not in {'http','https'}: continue
            candidate = canonical_url(candidate)
            if candidate not in links: links.append(candidate)
        except (ValueError, UnicodeError): continue

    for element in soup.select("script, style, nav, footer, header, aside, noscript, .related-products, .product-recommendations, [data-section-type='product-recommendations'], .newsletter, .cookie-banner"):
        element.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = re.sub(r"[ \t]+", " ", main.get_text("\n", strip=True))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    sections = [{'id': x['id'], 'title': x.get_text(' ', strip=True)[:200]} for x in main.select('[id]') if re.fullmatch(r'[A-Za-z][\w:.-]{0,99}', x['id'])][:100]
    return {"title": title, "text": text[:250000], "links": links, "jsonld": linked_data, 'sections': sections}


def chunk_text(text, words=350, overlap=50):
    tokens = text.split()
    return [" ".join(tokens[i:i + words]) for i in range(0, len(tokens), words - overlap) if len(tokens[i:i + words]) >= 4]


def add_source(db, workspace_id, kb_id, url, title, text, raw_key=None):
    hashed = hashlib.sha256(text.encode()).hexdigest()
    source = db.scalar(select(Source).where(Source.workspace_id == workspace_id, Source.kb_id == kb_id, Source.canonical_url == url, Source.content_hash == hashed))
    if source:
        return source
    source = Source(workspace_id=workspace_id, kb_id=kb_id, canonical_url=url, title=title, text_content=text, content_hash=hashed, raw_object_key=raw_key)
    db.add(source)
    db.flush()
    for i, chunk in enumerate(chunk_text(text)):
        db.add(Chunk(workspace_id=workspace_id, source_id=source.id, ordinal=i, text_content=chunk))
    db.flush()
    return source


def lexical_rank(chunks, query):
    stop = {"the", "a", "an", "is", "are", "what", "how", "does", "do", "can", "you", "your", "for", "of", "and", "to", "it", "me", "tell", "about"}
    terms = {t for t in re.findall(r"\w+", query.lower()) if t not in stop and len(t) > 1}
    scores = []
    n = max(len(chunks), 1)
    counts = [Counter(re.findall(r"\w+", c.text_content.lower())) for c in chunks]
    average = sum(sum(c.values()) for c in counts) / n or 1
    import math
    for chunk, words in zip(chunks, counts):
        score = 0.0
        length = sum(words.values())
        for term in terms:
            tf = words[term]
            if not tf:
                continue
            df = sum(1 for c in counts if c[term])
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / average))
        if score:
            scores.append((chunk.id, score))
    return sorted(scores, key=lambda x: x[1], reverse=True)


def _retrieval_rows(workspace_id, snapshot_ids):
    with session_scope() as db:
        snapshots = list(db.scalars(select(Snapshot).where(Snapshot.workspace_id == workspace_id, Snapshot.id.in_(snapshot_ids), Snapshot.state == "published")))
        if len(snapshots) != len(set(snapshot_ids)):
            raise ValueError("One or more knowledge snapshots are unavailable")
        source_ids = list({sid for snapshot in snapshots for sid in snapshot.source_ids})
        chunks = list(db.scalars(select(Chunk).where(Chunk.workspace_id == workspace_id, Chunk.source_id.in_(source_ids)))) if source_ids else []
        sources = {x.id: x for x in db.scalars(select(Source).where(Source.workspace_id == workspace_id, Source.id.in_(source_ids)))}
    return chunks,sources


def valid_prefetch(workspace_id,snapshot_ids,result):
    """Recheck publication/ownership and exact passage contents before cache reuse."""
    try:chunks,sources=_retrieval_rows(workspace_id,snapshot_ids)
    except ValueError:return False
    by_id={chunk.id:chunk for chunk in chunks}
    for passage in result.get('passages',[]):
        chunk=by_id.get(passage.get('chunk_id'))
        source=sources.get(chunk.source_id) if chunk else None
        if (chunk is None or source is None or chunk.source_id!=passage.get('source_revision_id') or
            chunk.text_content!=passage.get('text') or source.canonical_url!=passage.get('url') or
            source.title!=passage.get('title')):return False
    return True


async def retrieve(workspace_id, snapshot_ids, query, limit=6):
    chunks,sources = await asyncio.to_thread(_retrieval_rows,workspace_id,snapshot_ids)
    lexical = await asyncio.to_thread(lexical_rank,chunks,query)
    rankings = [lexical[:20]]
    retrieval_mode = "lexical-development"
    if vector_configured():
        from .metering import scope
        with scope(workspace_id=workspace_id):vector = (await embed([query]))[0]
        points = await Qdrant().search(workspace_id, snapshot_ids, vector)
        rankings.append([(x["payload"]["chunk_id"], x["score"]) for x in points])
        retrieval_mode = "qdrant-hybrid"
    elif settings.app_env == "production":
        raise RuntimeError("Production retrieval requires configured Qdrant and embedding infrastructure")
    fused = Counter()
    for ranking in rankings:
        for rank, (chunk_id, _) in enumerate(ranking):
            fused[chunk_id] += 1 / (60 + rank + 1)
    byid = {x.id: x for x in chunks}
    passages, seen = [], set()
    for chunk_id, score in fused.most_common():
        chunk = byid.get(chunk_id)
        if not chunk:
            continue
        normalized = hashlib.sha256(chunk.text_content.encode()).hexdigest()
        if normalized in seen:
            continue
        seen.add(normalized)
        source = sources[chunk.source_id]
        passages.append({"chunk_id": chunk.id, "source_revision_id": source.id, "url": source.canonical_url, "title": source.title, "text": chunk.text_content, "score": score, "fetched_at": source.fetched_at.replace(tzinfo=now().tzinfo).isoformat()})
        if len(passages) >= limit:
            break
    # Similarity alone is not answerability; avoid interpreting generic catalog passages as policy.
    policy_terms = {"refund", "return", "shipping", "delivery", "cancellation"}
    requested_policy = policy_terms.intersection(re.findall(r"\w+", query.lower()))
    answerable = bool(passages)
    if requested_policy and not any(any(term in p["text"].lower() for term in requested_policy) for p in passages):
        answerable = False
    return {"answerable": answerable, "reason": "Source passages found" if answerable else "No supporting source for this question", "passages": passages, "retrieval_mode": retrieval_mode}


async def index_snapshot(workspace_id, snapshot_id):
    if not vector_configured():
        if settings.app_env == "production":
            raise RuntimeError("Qdrant and embedding credentials must be configured")
        return
    def load():
        with session_scope() as db:
            snapshot=owned(db,Snapshot,workspace_id,snapshot_id)
            return [as_dict(x) for x in db.scalars(select(Chunk).where(Chunk.workspace_id==workspace_id,Chunk.source_id.in_(snapshot.source_ids)))]
    chunks=await asyncio.to_thread(load)
    from .job_control import resource_slot
    async with httpx.AsyncClient(timeout=30) as client:
        qdrant=Qdrant(client=client)
        await qdrant.ensure_collection()
        next_batch=0
        async def consume():
            nonlocal next_batch
            while next_batch<len(chunks):
                start=next_batch;next_batch+=32
                batch=chunks[start:start+32]
                async with resource_slot('index',settings.index_concurrency):
                    from .metering import scope
                    with scope(workspace_id=workspace_id):vectors=await embed([x['text_content'] for x in batch])
                    await qdrant.upsert(workspace_id,snapshot_id,batch,vectors)
        tasks=[asyncio.create_task(consume()) for _ in range(min(settings.index_concurrency,(len(chunks)+31)//32))]
        try:await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)


async def crawl_job(job_id):
    from .website_crawler import crawl
    await crawl(job_id)
