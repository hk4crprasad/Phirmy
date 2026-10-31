"""One-step URL → background knowledge → published agent → public widget."""
import copy
import secrets
from datetime import timedelta
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, func
from .db import as_dict, now,uid
from .models import WebsiteAssistant, KnowledgeBase, Agent, AgentVersion, Installation, Snapshot, Source, Job, Workspace, Conversation, Message
from .schemas import Input
from .domain import owned, enqueue, default_agent, publish_agent
from .security import principal, db_dependency, audit
from .knowledge import canonical_url, validate_public_url
from .config import settings
from .widget_branding import installation_record

router = APIRouter(prefix='/v1/workspaces/{workspace_id}/website-assistants')


class CrawlOptions(Input):
    max_pages: int = Field(default=100, ge=1, le=1000)
    render_js: bool = True
    refresh_hours: int = Field(default=24, ge=0, le=720)
    excluded_urls: list[str] = Field(default_factory=list, max_length=1000)


class WebsiteCreate(CrawlOptions):
    website_url: str = Field(min_length=8, max_length=2000)
    name: str = Field(default='Website assistant', min_length=1, max_length=160)
    agent_id: str | None = None
    goal: str = Field(default="", max_length=10000)


def queue_crawl(db, ws, row):
    for job in db.scalars(select(Job).where(Job.workspace_id == ws, Job.kind == 'crawl', Job.state.in_(['queued','running']))):
        if job.payload.get('kb_id') == row.kb_id:
            return job
    owned(db, KnowledgeBase, ws, row.kb_id).status = 'processing'
    return enqueue(db, ws, 'crawl', {'kb_id': row.kb_id, **row.options})


def records(db, ws, rows):
    if not rows: return []
    kb_ids, installation_ids = [r.kb_id for r in rows], [r.installation_id for r in rows]
    knowledge = {r.id: r for r in db.scalars(select(KnowledgeBase).where(KnowledgeBase.workspace_id == ws, KnowledgeBase.id.in_(kb_ids)))}
    installations = {r.id: r for r in db.scalars(select(Installation).where(Installation.workspace_id == ws, Installation.id.in_(installation_ids)))}
    kb_field = Job.payload['kb_id'].as_string()
    latest = select(Job.id, func.row_number().over(partition_by=kb_field, order_by=(Job.created_at.desc(), Job.id.desc())).label('position')).where(Job.workspace_id == ws, Job.kind == 'crawl', kb_field.in_(kb_ids)).subquery()
    jobs = {r.payload['kb_id']: r for r in db.scalars(select(Job).join(latest, latest.c.id == Job.id).where(latest.c.position == 1))}
    conversations = dict(db.execute(select(Conversation.installation_id, func.count()).where(Conversation.workspace_id == ws, Conversation.installation_id.in_(installation_ids)).group_by(Conversation.installation_id)).all())
    turns = dict(db.execute(select(Conversation.installation_id, func.count(Message.id)).join(Message, Message.conversation_id == Conversation.id).where(Conversation.workspace_id == ws, Message.workspace_id == ws, Conversation.installation_id.in_(installation_ids), Message.role == 'user').group_by(Conversation.installation_id)).all())
    return [{**as_dict(row), 'usage': {'conversations': conversations.get(row.installation_id, 0), 'visitor_turns': turns.get(row.installation_id, 0)},
             'knowledge': as_dict(knowledge[row.kb_id]), 'installation': installation_record(installations[row.installation_id], db),
             'job': as_dict(jobs[row.kb_id]) if row.kb_id in jobs else None} for row in rows]


def record(db, ws, row):
    return records(db, ws, [row])[0]


@router.get('')
def list_websites(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('widget:read'); actor.require('kb:read')
    return {'items': records(db, workspace_id, list(db.scalars(select(WebsiteAssistant).where(WebsiteAssistant.workspace_id == workspace_id).order_by(WebsiteAssistant.created_at.desc()))))}


@router.post('', status_code=202)
async def create_website(workspace_id: str, body: WebsiteCreate, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    for scope in ['agents:write','kb:write','widget:write','products:write']: actor.require(scope)
    await validate_public_url(body.website_url)
    url = canonical_url(body.website_url)
    db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    # Duplicate button submissions do not create duplicate crawls or agents.
    for row in db.scalars(select(WebsiteAssistant).where(WebsiteAssistant.workspace_id == workspace_id)):
        kb = owned(db, KnowledgeBase, workspace_id, row.kb_id)
        if kb.website_url == url and (not body.agent_id or row.agent_id == body.agent_id): return record(db, workspace_id, row)
    from .admission import immediate
    immediate(db,workspace_id,'website-widget:'+uid(),'widgets',1)
    if body.agent_id:
        agent = owned(db, Agent, workspace_id, body.agent_id)
        if agent.archived: raise HTTPException(409, 'This agent is archived')
    else:
        config = default_agent(body.name)
        if body.goal: config['instructions'] += '\nOwner goal (not verified business facts): ' + body.goal
        config['tools'] = [{'name': x, 'schema_revision':'1', 'timeout_ms':10000, 'side_effecting':x!='search_products'} for x in ['search_products','create_support_ticket','capture_lead']]
        config['instructions'] += ' Use website_search and website_open_page for permitted website interactions. Ask for booking details only when a scheduling tool is configured.'
        agent = Agent(workspace_id=workspace_id, name=body.name, draft_config=config)
        db.add(agent); db.flush()
    kb = KnowledgeBase(workspace_id=workspace_id, name=body.name, website_url=url)
    db.add(kb); db.flush()
    parsed = urlparse(url); site_origin = parsed.scheme + '://' + parsed.netloc
    installation = Installation(workspace_id=workspace_id, agent_id=agent.id, name=body.name,
                                public_id='cyne-' + secrets.token_urlsafe(18), allowed_origins=list(dict.fromkeys([site_origin, settings.app_origin, settings.app_origin.replace('localhost','127.0.0.1')])),
                                theme={'preset':'minimal', 'assistant_name':body.name, 'welcome_message':'Hello! Ask me about this business.',
                                       'publishable_key':'cyne_pk_' + secrets.token_urlsafe(24), 'website_actions':True, 'position':'right'})
    db.add(installation); db.flush()
    row = WebsiteAssistant(workspace_id=workspace_id, kb_id=kb.id, agent_id=agent.id, installation_id=installation.id,
                           options=CrawlOptions(**{k:v for k,v in body.model_dump().items() if k in CrawlOptions.model_fields}).model_dump())
    db.add(row); db.flush(); queue_crawl(db, workspace_id, row)
    audit(db, actor, 'website.created', row.id)
    return record(db, workspace_id, row)


@router.put('/{website_id}/options')
def options(workspace_id: str, website_id: str, body: CrawlOptions, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('kb:write')
    row = owned(db, WebsiteAssistant, workspace_id, website_id)
    for job in db.scalars(select(Job).where(Job.workspace_id == workspace_id, Job.kind == 'crawl', Job.state.in_(['queued','running']))):
        if job.payload.get('kb_id') == row.kb_id: raise HTTPException(409, 'Wait for the current crawl to finish before changing crawl settings')
    row.options = body.model_dump()
    row.next_crawl_at = now() + timedelta(hours=body.refresh_hours) if body.refresh_hours else None
    return record(db, workspace_id, row)


@router.post('/{website_id}/recrawl', status_code=202)
def recrawl(workspace_id: str, website_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('kb:write')
    row = owned(db, WebsiteAssistant, workspace_id, website_id)
    return as_dict(queue_crawl(db, workspace_id, row))


@router.post('/{website_id}/rotate-key')
def rotate_key(workspace_id: str, website_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('widget:write')
    row = owned(db, WebsiteAssistant, workspace_id, website_id)
    installation = owned(db, Installation, workspace_id, row.installation_id)
    installation.theme = {**installation.theme, 'publishable_key': 'cyne_pk_' + secrets.token_urlsafe(24)}
    audit(db, actor, 'widget.key_rotated', installation.id)
    return record(db, workspace_id, row)


def connect_snapshot(db, ws, kb_id, snapshot_id):
    row = db.scalar(select(WebsiteAssistant).where(WebsiteAssistant.workspace_id == ws, WebsiteAssistant.kb_id == kb_id))
    if not row: return
    agent = db.scalar(select(Agent).where(Agent.workspace_id == ws, Agent.id == row.agent_id).with_for_update())
    if agent.archived: return
    old_ids = set(db.scalars(select(Snapshot.id).where(Snapshot.workspace_id == ws, Snapshot.kb_id == kb_id)))
    def attach(config):
        config = copy.deepcopy(config)
        config['knowledge_snapshot_ids'] = [x for x in config.get('knowledge_snapshot_ids', []) if x not in old_ids] + [snapshot_id]
        return config
    # Keep unpublished human edits unpublished. Refresh only the existing live config.
    draft = attach(agent.draft_config)
    if agent.published_version_id:
        published = owned(db, AgentVersion, ws, agent.published_version_id)
        agent.draft_config = attach(published.config)
    else: agent.draft_config = draft
    publish_agent(db, ws, agent, agent.draft_revision)
    agent.draft_config = draft; agent.draft_revision += 1
    hours = row.options.get('refresh_hours', 24)
    row.next_crawl_at = now() + timedelta(hours=hours) if hours else None


def schedule_updates(db):
    for row in db.scalars(select(WebsiteAssistant).where(WebsiteAssistant.next_crawl_at <= now()).with_for_update(skip_locked=True)):
        installation = owned(db, Installation, row.workspace_id, row.installation_id)
        agent = owned(db, Agent, row.workspace_id, row.agent_id)
        if installation.enabled and not agent.archived: queue_crawl(db, row.workspace_id, row)
        row.next_crawl_at = now() + timedelta(hours=max(1, row.options.get('refresh_hours', 24)))


@router.get('/{website_id}/pages')
def website_pages(workspace_id: str, website_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('kb:read')
    row = owned(db, WebsiteAssistant, workspace_id, website_id)
    kb = owned(db, KnowledgeBase, workspace_id, row.kb_id)
    snapshot = owned(db, Snapshot, workspace_id, kb.active_snapshot_id) if kb.active_snapshot_id else None
    active = set(snapshot.source_ids if snapshot else [])
    latest = {}
    for source in db.scalars(select(Source).where(Source.workspace_id == workspace_id, Source.kb_id == row.kb_id).order_by(Source.fetched_at.desc()).limit(3000)):
        if source.canonical_url not in latest or source.id in active:
            latest[source.canonical_url] = {'id':source.id,'url':source.canonical_url,'title':source.title,'fetched_at':source.fetched_at.isoformat(),'indexed':source.id in active,'excluded':source.canonical_url in row.options.get('excluded_urls',[])}
    return {'items':list(latest.values())}
