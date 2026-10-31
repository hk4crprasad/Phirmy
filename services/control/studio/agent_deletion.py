"""Owner-confirmed, retryable deletion of one agent's exclusively owned data."""
import asyncio, hashlib, json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, delete,or_
from .db import session_scope, as_dict, now
from .models import *
from .schemas import Input
from .domain import owned, enqueue
from .security import principal, db_dependency, audit
from .job_control import get_job
from .config import settings

router=APIRouter(prefix='/v1/workspaces/{workspace_id}')
TERMINAL={'completed','failed','canceled','no_answer','busy'}


def operator(actor):
    actor.require('agents:write')
    if not actor.user_id or actor.role not in {'owner','admin'}:
        raise HTTPException(403,'Only a workspace owner or admin can delete agents and data')


def collect(db,ws,agent_id):
    agent=owned(db,Agent,ws,agent_id)
    cache={}
    def rows(model):
        if model not in cache:cache[model]=list(db.scalars(select(model).where(model.workspace_id==ws)))
        return cache[model]
    versions=[x for x in rows(AgentVersion) if x.agent_id==agent_id];vids={x.id for x in versions}
    installations=[x for x in rows(Installation) if x.agent_id==agent_id];iids={x.id for x in installations}
    websites=[x for x in rows(WebsiteAssistant) if x.agent_id==agent_id]
    calls=[x for x in rows(Call) if x.agent_version_id in vids or x.metadata_data.get('widget_installation_id') in iids];cids={x.id for x in calls}
    conversation_ids={x.id for x in rows(Conversation) if x.installation_id in iids}|{x.metadata_data['conversation_id'] for x in calls if x.metadata_data.get('conversation_id')}
    configurations=[agent.draft_config]+[x.config for x in versions]
    snapshots=rows(Snapshot);candidate_ids={x for cfg in configurations for x in cfg.get('knowledge_snapshot_ids',[])}
    candidates={x.kb_id for x in snapshots if x.id in candidate_ids}|{x.kb_id for x in websites}
    other_configs=[x.draft_config for x in rows(Agent) if x.id!=agent_id]+[x.config for x in rows(AgentVersion) if x.agent_id!=agent_id]
    other_ids={x for cfg in other_configs for x in cfg.get('knowledge_snapshot_ids',[])}
    shared={x.kb_id for x in snapshots if x.id in other_ids}|{x.kb_id for x in rows(WebsiteAssistant) if x.agent_id!=agent_id}
    kbids=candidates-shared
    # Conversation and voice tools identify their records by operation hashes.
    operations={x+':'+m.client_message_id for x in conversation_ids for m in rows(Message) if m.conversation_id==x}
    for call in calls:
        turn_count=sum(1 for t in rows(Turn) if t.call_id==call.id)
        # Widget voice can resume up to24 prior chat messages before its own turns.
        operations.update(call.id+':'+str(i) for i in range(turn_count+27))
    def hashes(name):return {'tool:'+hashlib.sha256((op+':'+name).encode()).hexdigest() for op in operations}
    lead_keys=hashes('capture_lead');appointment_keys=hashes('book_appointment')
    leads=[]
    call_leads={x.metadata_data.get('lead_id') for x in calls}
    for lead in rows(Lead):
        try:proof=json.loads(lead.evidence)
        except (ValueError,TypeError):proof={}
        if lead.id in call_leads or lead.evidence.split('\n',1)[0] in lead_keys or (isinstance(proof,dict) and (proof.get('conversation_id') in conversation_ids or proof.get('installation_id') in iids)):
            leads.append(lead)
    contexts={'conversation:'+x for x in conversation_ids}|{'call:'+x for x in cids}
    bookings=[x for x in rows(SchedulingBooking) if x.context_key in contexts]
    appointment_ids={x.appointment_id for x in bookings if x.appointment_id}|{x.id for x in rows(Appointment) if x.operation_key in appointment_keys}
    sources=[x for x in rows(Source) if x.kb_id in kbids];sids={x.id for x in sources}
    recordings=[x for x in rows(Recording) if x.call_id in cids]
    chunks=[x for x in rows(Chunk) if x.source_id in sids]
    from .cache import cache_key
    cache_keys={cache_key(x.text_content) for x in chunks}
    campaign_ids={x.id for x in rows(Campaign) if x.agent_version_id in vids}
    kb_urls={x.website_url for x in rows(KnowledgeBase) if x.id in kbids}
    other_urls={x.website_url for x in rows(KnowledgeBase) if x.id not in kbids}
    stores=[x for x in rows(Store) if x.website_url in kb_urls-other_urls];storeids={x.id for x in stores}
    tokens={agent_id,*kbids,*cids,*conversation_ids,*campaign_ids,*iids}
    def references(value):
        if isinstance(value,dict):return any(references(v) for v in value.values())
        if isinstance(value,list):return any(references(v) for v in value)
        return isinstance(value,str) and value in tokens
    jobs=[x for x in rows(Job) if x.kind!='agent_delete' and references(x.payload)]
    tools=[x for x in rows(ToolExecution) if x.call_id in cids or references(x.payload)]
    blockers=[]
    if any(x.state not in TERMINAL for x in calls):blockers.append('End active calls before deleting.')
    if any(x.state=='running' for x in jobs):blockers.append('Stop running crawls and tasks before deleting.')
    if any(x.state in {'running','queued'} for x in tools):blockers.append('Wait for running tool actions to finish.')
    if any(x.scope_key in contexts and x.state=='running' for x in rows(ToolConsent)):
        blockers.append('Wait for the confirmed action to finish.')
    keys={x.raw_object_key for x in sources if x.raw_object_key}|{x.object_key for x in recordings}|{x.theme['logo_object_key'] for x in installations if x.theme.get('logo_object_key')}|{x.payload['object_key'] for x in jobs if x.payload.get('object_key')}
    retained_keys={x.raw_object_key for x in rows(Source) if x.kb_id not in kbids}|{x.object_key for x in rows(Recording) if x.call_id not in cids}|{x.theme.get('logo_object_key') for x in rows(Installation) if x.id not in iids}|{x.provenance.get('raw_object_key') for x in rows(Product) if x.store_id not in storeids}|{x.payload.get('object_key') for x in rows(Job) if x.id not in {j.id for j in jobs}}
    return {'agent':agent,'versions':vids,'installations':iids,'websites':{x.id for x in websites},'calls':cids,'conversations':conversation_ids,'kb_ids':kbids,'snapshots':{x.id for x in snapshots if x.kb_id in kbids},'retained_snapshots':{x.id for x in snapshots if x.kb_id not in kbids},'sources':sids,'leads':{x.id for x in leads},'bookings':{x.id for x in bookings},'availability':{x.id for x in rows(SchedulingAvailability) if x.context_key in contexts},'appointments':appointment_ids,'campaigns':campaign_ids,'recordings':{x.id for x in recordings},'stores':storeids,'jobs':{x.id for x in jobs},'tools':{x.id for x in tools},'chunks':{x.id for x in chunks},'cache_keys':cache_keys,'keys':keys-retained_keys,'retained_keys':retained_keys,'shared_knowledge':len(candidates&shared),'blockers':blockers}


def summary(plan):
    return {'agent_id':plan['agent'].id,'name':plan['agent'].name,'counts':{key:len(plan[key]) for key in ['versions','installations','websites','calls','conversations','kb_ids','snapshots','sources','chunks','leads','bookings','appointments','campaigns','recordings','stores']},'shared_knowledge_preserved':plan['shared_knowledge'],'blockers':plan['blockers'],'retained':['Shared workspace resources','Billing and audit records','Phone numbers (unassigned)','External calendar meetings and previously exported data']}


@router.get('/agents/{agent_id}/deletion-preview')
def preview(workspace_id:str,agent_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    operator(actor);return summary(collect(db,workspace_id,agent_id))


class DeleteAgent(Input):
    confirmation: str=Field(min_length=1,max_length=160)


@router.post('/agents/{agent_id}/delete',status_code=202)
def start(workspace_id:str,agent_id:str,body:DeleteAgent,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    operator(actor)
    agent=db.scalar(select(Agent).where(Agent.workspace_id==workspace_id,Agent.id==agent_id).with_for_update())
    if not agent:raise HTTPException(404,'Agent not found')
    if body.confirmation!=agent.name:raise HTTPException(422,'Type the exact agent name to confirm deletion')
    previous=next((x for x in db.scalars(select(Job).where(Job.workspace_id==workspace_id,Job.kind=='agent_delete')) if x.payload.get('agent_id')==agent_id),None)
    if previous:return as_dict(previous)
    # Serialize with dispatcher claims; never erase data under a running crawler.
    list(db.scalars(select(Job).where(Job.workspace_id==workspace_id).with_for_update()))
    list(db.scalars(select(Snapshot).where(Snapshot.workspace_id==workspace_id).with_for_update().execution_options(populate_existing=True)))
    plan=collect(db,workspace_id,agent_id)
    if plan['blockers']:raise HTTPException(409,' '.join(plan['blockers']))
    agent.archived=True
    for row in db.scalars(select(KnowledgeBase).where(KnowledgeBase.workspace_id==workspace_id,KnowledgeBase.id.in_(plan['kb_ids']))):row.status='deleting'
    for row in db.scalars(select(Snapshot).where(Snapshot.workspace_id==workspace_id,Snapshot.id.in_(plan['snapshots']))):row.state='deleting'
    for row in db.scalars(select(Conversation).where(Conversation.workspace_id==workspace_id,Conversation.id.in_(plan['conversations']))):row.state='resolved'
    for row in db.scalars(select(Installation).where(Installation.workspace_id==workspace_id,Installation.agent_id==agent_id)):row.enabled=False
    for row in db.scalars(select(WebsiteAssistant).where(WebsiteAssistant.workspace_id==workspace_id,WebsiteAssistant.agent_id==agent_id)):row.next_crawl_at=None
    for row in db.scalars(select(Number).where(Number.workspace_id==workspace_id,Number.agent_id==agent_id)):row.agent_id=None
    for row in db.scalars(select(Job).where(Job.workspace_id==workspace_id,Job.id.in_(plan['jobs']))):row.cancel_requested=True;row.state='canceled'
    for row in db.scalars(select(Campaign).where(Campaign.workspace_id==workspace_id,Campaign.id.in_(plan['campaigns']))):row.state='canceled'
    job=enqueue(db,workspace_id,'agent_delete',{'agent_id':agent_id})
    audit(db,actor,'agent.deletion_requested',agent_id,{'job_id':job.id,'counts':summary(plan)['counts']})
    return as_dict(job)


async def purge_job(job_id):
    from .storage import get_store
    from .retrieval import Qdrant
    import httpx
    with session_scope() as db:
        job=get_job(db,job_id);ws=job.workspace_id;aid=job.payload['agent_id']
        if not db.get(Agent,aid):return
        plan=collect(db,ws,aid)
        if plan['blockers']:raise RuntimeError(' '.join(plan['blockers']))
        keys=(set(plan['keys'])|set(job.payload.get('object_keys',[])))-plan['retained_keys']
        snapshots=(set(plan['snapshots'])|set(job.payload.get('snapshot_ids',[])))-plan['retained_snapshots']
        cache_keys=set(plan['cache_keys'])|set(job.payload.get('cache_keys',[]))
    # Persist cleanup manifest before external deletions for retries after interruption.
    with session_scope(write=True) as db:
        job=get_job(db,job_id);job.payload={**job.payload,'object_keys':sorted(keys),'snapshot_ids':sorted(snapshots),'cache_keys':sorted(cache_keys)};job.phase='removing_stored_data'
    if settings.vector_endpoint and snapshots:
        client=Qdrant()
        try:
            await client.request('POST','/collections/'+client.collection+'/points/delete?wait=true',json={'filter':{'must':[{'key':'workspace_id','match':{'value':ws}},{'key':'snapshot_id','match':{'any':sorted(snapshots)}}]}})
        except httpx.HTTPStatusError as error:
            if error.response.status_code!=404:raise
    if settings.redis_url and cache_keys:
        from .cache import connection
        def remove_cache():
            client=connection(settings.redis_url);values=sorted(cache_keys)
            for offset in range(0,len(values),500):client.delete(*values[offset:offset+500])
        await asyncio.to_thread(remove_cache)
    store=get_store() if keys else None
    from datetime import timedelta
    for index,key in enumerate(keys):
        if index%10==0:
            with session_scope(write=True) as db:get_job(db,job_id).lease_until=now()+timedelta(minutes=3)
        await asyncio.to_thread(store.delete,ws,key)
        with session_scope(write=True) as db:
            get_job(db,job_id)
            from .metering import removed
            removed(db,ws,key)
    with session_scope(write=True) as db:
        job=get_job(db,job_id)
        if job.state!='running':raise RuntimeError('Deletion task must be running')
        plan=collect(db,ws,aid)
        if plan['blockers']:raise RuntimeError(' '.join(plan['blockers']))
        def erase(model,ids,column=None):
            db.execute(delete(model).where(model.workspace_id==ws,(column if column is not None else model.id).in_(ids)),execution_options={'synchronize_session':False})
        scope_keys={'conversation:'+identity for identity in plan['conversations']}|{'call:'+identity for identity in plan['calls']}
        for model in [ToolConsent,ToolAttempt,ToolBudget]:erase(model,scope_keys,model.scope_key)
        challenges=set(db.scalars(select(WidgetEmailChallenge.id).where(WidgetEmailChallenge.workspace_id==ws,
            WidgetEmailChallenge.conversation_id.in_(plan['conversations']))))
        db.execute(delete(WidgetMarketingConsent).where(WidgetMarketingConsent.workspace_id==ws,
            or_(WidgetMarketingConsent.challenge_id.in_(challenges),WidgetMarketingConsent.lead_id.in_(plan['leads']))))
        erase(WidgetEmailChallenge,challenges)
        db.execute(delete(EmailOutbox).where(EmailOutbox.operation_key.in_({'widget-otp:'+identity for identity in challenges})))
        for model in [WidgetProtection,WidgetBucket,WidgetAdmission]:erase(model,plan['installations'],model.installation_id)
        erase(SchedulingBooking,plan['bookings']);erase(SchedulingAvailability,plan['availability']);erase(Appointment,plan['appointments'])
        erase(Ticket,plan['conversations'],Ticket.conversation_id);erase(Message,plan['conversations'],Message.conversation_id);erase(ConversationContext,plan['conversations'],ConversationContext.conversation_id)
        erase(Conversation,plan['conversations']);erase(Lead,plan['leads']);erase(ToolExecution,plan['tools'])
        erase(Recording,plan['recordings']);erase(Turn,plan['calls'],Turn.call_id);erase(Attempt,plan['campaigns'],Attempt.campaign_id);erase(Campaign,plan['campaigns'])
        financial={x for x in db.scalars(select(Ledger.call_id).where(Ledger.workspace_id==ws,Ledger.call_id.in_(plan['calls'])))}|set(db.scalars(select(Reservation.call_id).where(Reservation.workspace_id==ws,Reservation.call_id.in_(plan['calls']))))|set(db.scalars(select(CallCostRecord.call_id).where(CallCostRecord.workspace_id==ws,CallCostRecord.call_id.in_(plan['calls']))))
        for call in db.scalars(select(Call).where(Call.workspace_id==ws,Call.id.in_(financial))):
            call.agent_version_id=None;call.agent_name='Deleted agent';call.destination='';call.analysis={};call.metadata_data={};call.failure_code=None
        db.flush();erase(Call,plan['calls']-financial)
        erase(WebsiteAssistant,plan['websites']);erase(Installation,plan['installations'])
        erase(Product,plan['stores'],Product.store_id);erase(Store,plan['stores'])
        erase(Chunk,plan['sources'],Chunk.source_id);erase(Source,plan['sources']);erase(Snapshot,plan['snapshots']);erase(KnowledgeBase,plan['kb_ids'])
        erase(Job,plan['jobs']);erase(AgentVersion,plan['versions'])
        db.delete(plan['agent']);db.flush()
        job.payload={'agent_id':aid};job.result={'status':'deleted','counts':summary(plan)['counts'],'shared_knowledge_preserved':plan['shared_knowledge']}


def lock_knowledge_for_write(db,ws,config):
    ids=config.get('knowledge_snapshot_ids',[])
    for snapshot in db.scalars(select(Snapshot).where(Snapshot.workspace_id==ws,Snapshot.id.in_(ids)).with_for_update().execution_options(populate_existing=True)):
        if snapshot.state=='deleting':raise HTTPException(409,'This knowledge is being permanently deleted; choose another source')
