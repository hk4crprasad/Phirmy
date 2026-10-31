"""A useful website answer before account creation, with an owned, expiring preview."""
import asyncio
import json
import re
import secrets
import time
from datetime import timedelta
from typing import Literal
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from .config import settings
from .db import session_scope, now, uid, as_dict
from .models import Preview, KnowledgeBase, Snapshot, Agent, Installation, Chunk, WebsiteAssistant
from .schemas import Input
from .security import digest, limiter, check_origin, principal, db_dependency, capability
from .knowledge import safe_fetch, canonical_url, extract_page, add_source
from .domain import default_agent, publish_agent, enqueue, audit
from .storage import get_store,put_checked
from .retrieval import vector_configured, Qdrant, embed
from .preview_answers import source_answer, answer_question, navigation

router = APIRouter()
COOKIE = "studio_preview"


class Website(Input):
    url: str = Field(min_length=4, max_length=2000)


class HistoryEntry(Input):
    role: Literal['user', 'assistant']
    content: str = Field(max_length=2000)


class Question(Input):
    question: str = Field(min_length=2, max_length=1000)
    history: list[HistoryEntry] = Field(default_factory=list, max_length=8)


def preview_owned(db, request):
    token = request.cookies.get(COOKIE, "")
    row = db.scalar(select(Preview).where(Preview.token_hash == digest(token), Preview.expires_at > now()))
    if not row:
        raise HTTPException(410, "This preview has expired. Try your website again.")
    return row


async def fetch_preview(url):
    parsed = urlparse(url)
    robots_url = parsed.scheme + '://' + parsed.netloc + '/robots.txt'
    try:
        _, body, _ = await asyncio.wait_for(safe_fetch(robots_url, max_bytes=100000), timeout=3)
        robots = RobotFileParser(); robots.parse(body.decode(errors='replace').splitlines())
        if not robots.can_fetch('VoiceStudioKnowledgeBot', url):
            raise HTTPException(422, "This website asks crawlers not to read this page. Try a public page you can share.")
    except HTTPException:
        raise
    except Exception:
        pass  # A missing robots file is not a successful read and supplies no business facts.
    target, body, content_type = await asyncio.wait_for(safe_fetch(url, max_bytes=1500000), timeout=12)
    if 'html' not in content_type.lower() and content_type:
        raise HTTPException(422, 'Use a public website page, rather than a file download.')
    page = extract_page(body, target)
    if len(page['text'].split()) < 12:
        raise HTTPException(422, "I couldn't read enough text on this page. Try a product or about page instead.")
    host = urlparse(target).hostname or ''
    name = re.split(r'\s[|–—]\s', page['title'])[0].strip()[:100] or host
    soup=BeautifulSoup(body,'html.parser')
    collections=[]
    discovered=[]
    for link in soup.select('a[href]'):
        text=' '.join(link.get_text(' ',strip=True).split())
        if len(discovered)<300:
            discovered.append({'url':link.get('href',''), 'title':text[:120]})
        if '/collections/' in link.get('href','') and 2<len(text)<45 and text.lower() not in {'all','all products','shop all','view all','shop now','continue shopping','best sellers','bestsellers','new arrivals','featured','sale','collections'} and not re.search(r'rs\.|₹|\d|[|]',text,re.I):
            if text.lower() not in {x.lower() for x in collections}:collections.append(text)
    offer=''
    if collections:
        items=collections[:5]
        offer=name+"’s website lists "+(', '.join(items[:-1])+' and '+items[-1] if len(items)>1 else items[0])+'.'
    else:
        paragraphs=[' '.join(p.get_text(' ',strip=True).split()) for p in soup.select('main p, article p, [role="main"] p')]
        useful=[p for p in paragraphs if 50<len(p)<450 and not re.search(r'cookie|subscribe|newsletter',p,re.I)]
        if useful:offer=useful[0]
    data = {"url": canonical_url(target), "title": page['title'][:300], "name": name,
            "text": page['text'][:40000], "links": page['links'][:150], 'offer':offer}
    data['navigation'] = navigation({**data, 'navigation':discovered})
    return data


@router.post('/v1/public/preview', status_code=201)
async def create_preview(body: Website, request: Request, response: Response):
    check_origin(request)
    limiter.check('preview:' + (request.client.host if request.client else 'unknown'), 8, 3600)
    url = body.url if '://' in body.url else 'https://' + body.url
    started = time.monotonic()
    try:
        data = await fetch_preview(url)
    except HTTPException:
        raise
    except (ValueError, OSError):
        raise HTTPException(422, 'Use a reachable public website. Private addresses and internal services cannot be read.')
    except Exception:
        raise HTTPException(422, "I couldn't read this website in time. Try a public product or about page.")
    token = secrets.token_urlsafe(32)
    def save():
        with session_scope(write=True) as db:
            row = Preview(token_hash=digest(token), expires_at=now()+timedelta(hours=1), website_url=data['url'], data=data)
            db.add(row); db.flush()
            return row.id
    preview_id = await asyncio.to_thread(save)
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.session_secure, samesite='lax', max_age=3600, path='/')
    return {"id": preview_id, "name": data['name'], "website_url": data['url'], "question": "What does this business offer?",
            "answer": source_answer(data, 'What does this business offer?'), "elapsed_ms": round((time.monotonic()-started)*1000),
            "sources_read": 1, "voice_available": settings.capabilities()['live_voice']}


@router.post('/v1/public/preview/question')
async def question(body: Question, request: Request):
    check_origin(request)
    limiter.check('preview-question:' + (request.client.host if request.client else 'unknown'), 30, 3600)
    def load():
        with session_scope() as db:
            return preview_owned(db, request).data
    data = await asyncio.to_thread(load)
    return await answer_question(data, body.question, [entry.model_dump() for entry in body.history])


@router.get('/v1/public/preview')
def current(request: Request):
    with session_scope() as db:
        preview = preview_owned(db, request)
        return {'name': preview.data['name'], 'website_url': preview.website_url, 'claimed': bool(preview.claimed_agent_id)}


@router.post('/v1/workspaces/{workspace_id}/preview/claim', status_code=201)
async def claim(workspace_id: str, request: Request, response: Response, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('agents:write')
    preview = preview_owned(db, request)
    # Serialize claims; a copied request cannot create multiple agents/workspaces.
    preview = db.scalar(select(Preview).where(Preview.id == preview.id).with_for_update().execution_options(populate_existing=True))
    if preview.claimed_agent_id:
        if preview.claimed_workspace_id != workspace_id:
            raise HTTPException(409, 'This preview has already been saved in another workspace')
        return {'agent_id': preview.claimed_agent_id, 'workspace_id': workspace_id}
    data = preview.data
    db.commit()
    key = await asyncio.to_thread(put_checked, workspace_id, 'snapshots', data['text'].encode(), 'text/plain; charset=utf-8')
    preview=db.scalar(select(Preview).where(Preview.id==preview.id).with_for_update().execution_options(populate_existing=True))
    if preview.claimed_agent_id:
        if preview.claimed_workspace_id!=workspace_id:raise HTTPException(409,'This preview has already been saved in another workspace')
        return {'agent_id':preview.claimed_agent_id,'workspace_id':workspace_id}
    from .admission import immediate
    immediate(db,workspace_id,'preview-widget:'+preview.id,'widgets',1)
    kb = KnowledgeBase(workspace_id=workspace_id, name=data['name']+' · website', website_url=data['url'], status='ready')
    db.add(kb); db.flush()
    from .metering import stored,record_usage
    stored(db,workspace_id,key,len(data['text'].encode()))
    record_usage(db,workspace_id,'preview-page:'+kb.id,'crawl_pages',1,scope_id=kb.id)
    source = add_source(db, workspace_id, kb.id, data['url'], data['title'], data['text'], key)
    snapshot = Snapshot(workspace_id=workspace_id, kb_id=kb.id, revision=1, state='published', source_ids=[source.id])
    db.add(snapshot); db.flush()
    kb.active_snapshot_id, kb.pages_indexed = snapshot.id, 1
    chunks = list(db.scalars(select(Chunk).where(Chunk.workspace_id == workspace_id, Chunk.source_id == source.id)))
    kb.chunks_indexed = len(chunks)
    if vector_configured():
        qdrant = Qdrant()
        await qdrant.ensure_collection()
        batch = [as_dict(x) for x in chunks]
        from .metering import scope
        with scope(workspace_id=workspace_id,db=db):vectors = await embed([x['text_content'] for x in batch])
        await qdrant.upsert(workspace_id, snapshot.id, batch, vectors)
    elif settings.app_env == 'production':
        raise HTTPException(503, 'Knowledge indexing is not configured')
    config = default_agent(data['name']+' assistant')
    config['greeting'] = 'Hi, I’m the AI assistant for '+data['name']+'. How can I help?'
    config['knowledge_snapshot_ids'] = [snapshot.id]
    config['tools'] = [{'name':name,'schema_revision':'1','timeout_ms':10000,'side_effecting':name!='search_products'} for name in ['search_products','create_support_ticket','capture_lead']]
    agent = Agent(workspace_id=workspace_id, name=config['name'], draft_config=config)
    db.add(agent); db.flush(); publish_agent(db, workspace_id, agent, 1)
    origins = list(dict.fromkeys([settings.app_origin, settings.app_origin.replace('localhost','127.0.0.1'), urlparse(data['url']).scheme+'://'+urlparse(data['url']).netloc]))
    installation = Installation(workspace_id=workspace_id, agent_id=agent.id, public_id=secrets.token_urlsafe(18), name=data['name']+' website chat', allowed_origins=origins, theme={'preset':'minimal','publishable_key':'cyne_pk_' + secrets.token_urlsafe(24),'website_actions':True,'assistant_name':config['name']})
    db.add(installation); db.flush()
    from .website_routes import CrawlOptions, queue_crawl
    website = WebsiteAssistant(workspace_id=workspace_id,kb_id=kb.id,agent_id=agent.id,installation_id=installation.id,options=CrawlOptions().model_dump())
    db.add(website); db.flush(); queue_crawl(db, workspace_id, website)
    preview.claimed_agent_id, preview.claimed_workspace_id = agent.id, workspace_id
    audit(db, actor, 'preview.claimed', agent.id)
    response.delete_cookie(COOKIE, path='/')
    return {'agent_id': agent.id, 'workspace_id': workspace_id, 'kb_id': kb.id}
