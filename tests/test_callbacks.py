import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from studio import callbacks, handoff, tool_safety, agent_tools, llm
from studio.config import settings
from studio.db import session_scope
from studio.domain import default_agent
from studio.models import Ticket, EmailOutbox, Lead
from studio.secrets import decrypt
from test_agent_red_team import scoped, present
from test_voice_latency import voice


@pytest.mark.asyncio
async def test_confirmed_callback_creates_one_inbox_ticket_and_owner_outbox(sample):
    context={**scoped(sample),'user_text':'Please call me back at +1 (202) 555-0123 tomorrow afternoon.'}
    proposal=await handoff.reply(default_agent(),context)
    assert proposal['confirmation']['tool_name']=='request_callback'
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Ticket))==0
        before=db.scalar(select(func.count()).select_from(EmailOutbox))
    with pytest.raises(HTTPException):
        await tool_safety.execute_confirmation({}, {**context,'user_text':'Confirm request'},proposal['confirmation']['id'])
    confirmed=present(context,proposal['confirmation'])
    response=await handoff.reply(default_agent(),confirmed,proposal['confirmation']['id'])
    assert response['result']['callback_requested'] is True and response['text']==callbacks.RECORDED
    assert await handoff.reply(default_agent(),confirmed,proposal['confirmation']['id'])==response
    with session_scope() as db:
        tickets=list(db.scalars(select(Ticket)))
        assert len(tickets)==1 and tickets[0].state=='open'
        assert '+12025550123' in tickets[0].description and 'unverified' in tickets[0].description
        assert 'not marketing consent' in tickets[0].description
        messages=list(db.scalars(select(EmailOutbox).where(EmailOutbox.subject=='A visitor requested a callback')))
        assert len(messages)==1 and messages[0].state=='pending'
        assert '+12025550123' in decrypt(messages[0].encrypted_payload)
        assert db.scalar(select(func.count()).select_from(EmailOutbox))==before+1
        assert db.scalar(select(func.count()).select_from(Lead))==0


@pytest.mark.asyncio
async def test_phone_collection_then_confirmation_and_cancel_without_save(sample):
    context={**scoped(sample),'user_text':'Please call me back'}
    first=await handoff.reply(default_agent(),context)
    assert first=={'text':callbacks.ASK_PHONE}
    followup={**context,'last_assistant_text':first['text'],'user_text':'+12025550123'}
    second=await handoff.reply(default_agent(),followup)
    assert second['confirmation']['tool_name']=='request_callback'
    canceled=await handoff.reply(default_agent(),{**context,'last_assistant_text':callbacks.ASK_PHONE,'user_text':'Cancel'})
    assert 'Canceled' in canceled['text']
    assert await handoff.reply(default_agent(),{**context,'last_assistant_text':callbacks.ASK_PHONE,'user_text':'What are your hours?'}) is None
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Ticket))==0


def test_callback_proposal_rejects_invented_phone_and_time_and_accepts_prior_visitor_details(sample):
    context={**scoped(sample),'user_text':'Call me back at +12025550123 tomorrow morning'}
    args={'phone':'+12025550124','name':'','preferred_time':'','reason':'Support'}
    with pytest.raises(HTTPException):tool_safety.propose({},'request_callback',args,context)
    args['phone']='+12025550123';args['preferred_time']='Tuesday at noon'
    with pytest.raises(HTTPException):tool_safety.propose({},'request_callback',args,context)
    args['preferred_time']='tomorrow morning'
    proposal=tool_safety.propose({},'request_callback',args,{**context,'user_text':'Please use the number I gave you',
                                                         'user_history':[context['user_text']]})
    assert '+12025550123' in proposal['summary']
    for bad in ['12025550123','+1202','+1234567890123456','+12025550123;dial=+1900']:
        with pytest.raises(HTTPException):callbacks.phone(bad)


@pytest.mark.asyncio
async def test_feature_revocation_and_forged_scope_cannot_create_callback(sample,monkeypatch):
    context={**scoped(sample),'user_text':'Please call me back at +12025550123'}
    args=callbacks.draft(context['user_text'])
    proposal=tool_safety.propose({},'request_callback',args,context)
    confirmed=present(context,proposal)
    other=scoped(sample)
    with pytest.raises(HTTPException):await tool_safety.execute_confirmation({},present(other,proposal),proposal['id'])
    monkeypatch.setattr(settings,'callback_requests_enabled',False)
    result=await tool_safety.execute_confirmation({},confirmed,proposal['id'])
    assert result['result']['state']=='failed'
    assert agent_tools.tool_definitions({'tools':[{'name':'request_callback'}]})==[]
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Ticket))==0


@pytest.mark.asyncio
async def test_callback_wording_still_requires_positive_intent_classification(sample,monkeypatch):
    context={**scoped(sample),'user_text':'Do not call me back at +12025550123'}
    monkeypatch.setattr(handoff,'classifier',type('Classifier',(),{'requested':AsyncMock(return_value=False)})())
    assert await handoff.reply(default_agent(),context) is None
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Ticket))==0


@pytest.mark.asyncio
async def test_live_classifier_screens_call_me_back_for_model_decision(monkeypatch):
    captured=[]
    class Classifier:
        def __init__(self,*args,**kwargs):captured.append(args);self.calls=[]
        async def stream(self):
            self.calls=[{'name':'classify_handoff','arguments':json.dumps({'requested':True})}]
            if False:yield ''
    monkeypatch.setattr(llm,'Turn',Classifier)
    assert await handoff.ModelIntentClassifier().requested('Please call me back',{'api_key':'fake','model':'fake'})
    assert len(captured)==1


def test_widget_callback_request_confirmation_and_owner_resolution(sample):
    from test_widget_live import start
    client,_,base,_=sample
    state,headers=start(sample)
    def chat(text,identity):
        response=client.post('/v1/public/chat',headers=headers,json={'session_id':state['id'],
            'client_message_id':identity,'message':text})
        assert response.status_code==200,response.text
        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        return events[-1]
    assert callbacks.ASK_PHONE in chat('Please call me back','callback-one')['text']
    proposal=chat('+12025550123','callback-two')
    assert proposal['confirmation']['tool_name']=='request_callback'
    assert client.get(base+'/tickets').json()['items']==[]
    result=chat('Confirm request','callback-three')
    assert result['text']==callbacks.RECORDED and result['ticket_id']
    tickets=client.get(base+'/tickets').json()['items']
    assert len(tickets)==1 and tickets[0]['conversation_id']==state['id']
    changed=client.patch(base+'/tickets/'+result['ticket_id'],json={'state':'resolved'})
    assert changed.status_code==200 and changed.json()['state']=='resolved'
    assert chat('Confirm request','callback-three')['ticket_id']==result['ticket_id']
    assert len(client.get(base+'/tickets').json()['items'])==1


@pytest.mark.asyncio
async def test_voice_callback_readback_creates_inbox_only_after_later_turn(voice):
    _,_,_,_,session,transport=voice
    session.mode='simulation'
    await session.user_text('Please call me back at +12025550123')
    await session.task
    final=[event for event in transport.events if event['type']=='server.transcript' and event['speaker']=='assistant' and event['final']]
    assert 'Confirm request' in final[-1]['text']
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Ticket))==0
    await session.user_text('Confirm request')
    await session.task
    final=[event for event in transport.events if event['type']=='server.transcript' and event['speaker']=='assistant' and event['final']]
    assert final[-1]['text']==callbacks.RECORDED
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Ticket))==1


@pytest.mark.asyncio
async def test_support_ticket_about_callback_function_is_not_rerouted_to_phone_collection(sample):
    context={**scoped(sample),'user_text':'Please create a support ticket about my callback function'}
    result=await handoff.reply(default_agent(),context)
    assert result['confirmation']['tool_name']=='create_support_ticket'
