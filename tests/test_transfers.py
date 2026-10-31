import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xml.etree.ElementTree import fromstring

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from studio import admission, carrier_config, media_lifecycle, tool_safety, transfers, transfer_routes, transfer_provider
from studio.config import settings
from studio.db import now, session_scope, uid
from studio.domain import default_agent, settle_call
from studio.models import Call, CallCostRecord, CallTransfer, Job, BudgetAdmission, Reservation, TransferPolicy
from studio.secrets import decrypt
from studio.workers import execute_job
from test_agent_red_team import present
from test_operator_billing import authorize


@pytest.fixture(params=['twilio','plivo'])
def transfer(sample,monkeypatch,request):
    client,ws,base,_=sample
    for name,value in [('live_transfer_enabled',True),('live_calls_enabled',True),('paid_activation_enabled',True),
                       ('media_public_origin','https://media.example.test')]:monkeypatch.setattr(settings,name,value)
    credentials={'account_sid':'synthetic-account','auth_id':'synthetic-id','auth_token':'synthetic-token'}
    monkeypatch.setattr(carrier_config,'credentials',lambda *args:credentials)
    policy=client.put(base+'/transfer-policy',json={'destination':'+12025550124','label':'Support team',
                                                  'maximum_seconds':60,'enabled':True})
    assert policy.status_code==200,policy.text
    authorize((client,ws,base),monkeypatch)
    assert client.post('/v1/operator/transfers/'+ws+'/approval',json={'revision':policy.json()['revision'],'approved':True,'verified_staff':True}).status_code==200
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,mode='live',transport='pstn',state='connected',connected_at=now()-timedelta(seconds=2),
                  provider_call_id='synthetic-parent-'+request.param,metadata_data={'provider':request.param,
                  'carrier_deadline_at':(now()+timedelta(seconds=180)).timestamp()})
        db.add(call);db.flush()
        config=default_agent();config['behavior']['max_connected_seconds']=180
        admission.admit_voice(db,call,config)
        call_id=call.id
    context={'workspace_id':ws,'call_id':call_id,'operation_id':uid(),
             'user_text':'Please connect me to a human','last_assistant_text':''}
    return SimpleNamespace(client=client,ws=ws,base=base,context=context,call_id=call_id,provider=request.param,credentials=credentials)


async def queue(t):
    proposal=tool_safety.propose({},'request_human_transfer',{'reason':'Visitor asked to speak to support'},t.context)
    response=await tool_safety.execute_confirmation({},present(t.context,proposal),proposal['id'])
    assert response['result']['transfer_id'],response
    return response['result']['transfer_id']


def signed(t,identity,endpoint,form):
    path='/v1/transfer-webhooks/'+identity+'/'+endpoint
    url=settings.media_public_origin+path
    if t.provider=='twilio':
        from twilio.request_validator import RequestValidator
        headers={'X-Twilio-Signature':RequestValidator(t.credentials['auth_token']).compute_signature(url,form)}
    else:
        from plivo.utils.signature_v3 import get_signature_v3,construct_post_url
        nonce='synthetic-nonce'
        signature=get_signature_v3(t.credentials['auth_token'].encode(),construct_post_url(url,form).decode(),nonce.encode()).decode()
        headers={'X-Plivo-Signature-V3':signature,'X-Plivo-Signature-V3-Nonce':nonce}
    return t.client.post(path,data=form,headers=headers)


def instruction(t,identity):
    form={'AccountSid':t.credentials['account_sid'],'CallSid':'synthetic-parent-'+t.provider} if t.provider=='twilio' else {'CallUUID':'synthetic-parent-'+t.provider}
    return signed(t,identity,'instructions',form)


def finish(t,identity,duration=12):
    form=({'AccountSid':t.credentials['account_sid'],'CallSid':'synthetic-parent-'+t.provider,
           'DialCallStatus':'completed','DialCallSid':'synthetic-child','DialCallDuration':str(duration)} if t.provider=='twilio' else
          {'DialALegUUID':'synthetic-parent-'+t.provider,'DialBLegUUID':'synthetic-child','DialAction':'hangup',
           'DialBLegBillDuration':str(duration)})
    return signed(t,identity,'status',form)


@pytest.mark.asyncio
async def test_confirmation_creates_one_job_and_parent_reservations_survive_media_close(transfer):
    t=transfer
    identity=await queue(t)
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(CallTransfer))==1
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind=='call_transfer'))==1
        row=db.get(CallTransfer,identity)
        assert row.maximum_seconds==60 and 'synthetic-token' not in row.encrypted_snapshot
    media_lifecycle.settle(t.ws,t.call_id,None,False,'unused')
    with session_scope() as db:
        call=db.get(Call,t.call_id)
        assert call.state=='connected' and call.ended_at is None
        assert db.scalar(select(Reservation).where(Reservation.call_id==t.call_id)).state=='active'
        assert db.scalar(select(BudgetAdmission).where(BudgetAdmission.operation_key==__import__('hashlib').sha256(('voice-quota:'+t.call_id).encode()).hexdigest())).state=='held'


@pytest.mark.asyncio
async def test_signed_one_shot_instructions_and_child_cost_separate_from_parent(transfer,monkeypatch):
    t=transfer;identity=await queue(t)
    fake=SimpleNamespace(submit=AsyncMock())
    monkeypatch.setattr(transfer_provider,'provider',fake)
    with session_scope() as db:job_id=db.scalar(select(Job.id).where(Job.kind=='call_transfer'))
    await execute_job(job_id)
    assert fake.submit.await_count==1
    response=instruction(t,identity)
    assert response.status_code==200,response.text
    xml=fromstring(response.text)
    assert xml.find('Dial/Number').text=='+12025550124'
    assert int(xml.find('Dial').attrib['timeLimit'])<=60
    # Signed retries cannot authorize another staff dial.
    assert fromstring(instruction(t,identity).text).find('Dial') is None
    assert finish(t,identity).status_code==200
    assert finish(t,identity).status_code==200
    assert finish(t,identity,duration=99).status_code==409
    with session_scope(write=True) as db:
        row=db.get(CallTransfer,identity)
        assert row.state=='completed' and row.child_bill_ms==12_000
        call=db.get(Call,t.call_id)
        settle_call(db,call,25_000,'completed')
    with session_scope() as db:
        costs=list(db.scalars(select(CallCostRecord).where(CallCostRecord.call_id==t.call_id,CallCostRecord.provider==t.provider)))
        assert sorted(row.units['carrier_ms'] for row in costs)==[12_000,25_000]
        assert len(costs)==2
        assert db.scalar(select(Reservation).where(Reservation.call_id==t.call_id)).state in {'released','consumed'}
    listing=t.client.get(t.base+'/call-transfers').json()['items']
    assert len(listing)==1 and listing[0]['connection_confirmed']
    assert 'synthetic-token' not in json.dumps(listing)


@pytest.mark.asyncio
async def test_ambiguous_submission_is_not_replayed_and_keeps_child_hold(transfer,monkeypatch):
    t=transfer;identity=await queue(t)
    fake=SimpleNamespace(submit=AsyncMock(side_effect=httpx.ReadTimeout('Synthetic ambiguous write')))
    monkeypatch.setattr(transfer_provider,'provider',fake)
    with session_scope() as db:job_id=db.scalar(select(Job.id).where(Job.kind=='call_transfer'))
    await execute_job(job_id)
    await execute_job(job_id)
    assert fake.submit.await_count==1
    with session_scope() as db:
        row=db.get(CallTransfer,identity)
        assert row.state=='unknown'
        key=__import__('hashlib').sha256(transfers.cost_key(identity).encode()).hexdigest()
        assert db.scalar(select(BudgetAdmission).where(BudgetAdmission.operation_key==key)).state=='unknown'
    # A signed provider fetch can resolve the ambiguous submission safely.
    assert fromstring(instruction(t,identity).text).find('Dial') is not None
    assert finish(t,identity).status_code==200


@pytest.mark.asyncio
async def test_staff_change_and_activation_revocation_fail_before_dial(transfer,monkeypatch):
    t=transfer;identity=await queue(t)
    monkeypatch.setattr(settings,'live_transfer_enabled',False)
    assert transfers.begin(identity) is None
    with session_scope() as db:assert db.get(CallTransfer,identity).state=='failed'
    assert fromstring(instruction(t,identity).text).find('Dial') is None
    assert t.client.put(t.base+'/transfer-policy',json={'destination':'+12025550125','label':'New team','maximum_seconds':60,'enabled':True}).json()['approved'] is False


@pytest.mark.asyncio
async def test_callbacks_reject_forged_and_foreign_parent_identity(transfer):
    t=transfer;identity=await queue(t)
    transfers.begin(identity)
    path='/v1/transfer-webhooks/'+identity+'/instructions'
    assert t.client.post(path,data={'CallSid':'forged'}).status_code==401
    wrong={'AccountSid':t.credentials['account_sid'],'CallSid':'foreign-parent'} if t.provider=='twilio' else {'CallUUID':'foreign-parent'}
    assert signed(t,identity,'instructions',wrong).status_code==401
    assert instruction(t,identity).status_code==200
    # Disabled activation still accepts valid settlement for an existing leg.
    settings.live_transfer_enabled=False
    assert finish(t,identity).status_code==200


@pytest.mark.asyncio
async def test_concurrent_workers_claim_only_one_paid_submission(transfer):
    identity=await queue(transfer)
    with ThreadPoolExecutor(4) as pool:results=list(pool.map(transfers.begin,[identity]*4))
    assert sum(result is not None for result in results)==1
    with session_scope() as db:assert db.get(CallTransfer,identity).state=='unknown'


def test_policy_approval_is_verified_operator_only_and_api_keys_cannot_change_staff(transfer):
    t=transfer
    policy=t.client.get(t.base+'/transfer-policy').json()
    key=t.client.post(t.base+'/keys',json={'name':'Settings key','scopes':['settings:read','settings:write']}).json()['secret']
    assert t.client.get(t.base+'/transfer-policy',headers={'X-API-Key':key}).status_code==403
    assert t.client.post('/v1/operator/transfers/'+t.ws+'/approval',headers={'X-API-Key':key},json={'revision':policy['revision'],'approved':True,'verified_staff':True}).status_code==403
    assert t.client.post('/v1/operator/transfers/'+t.ws+'/approval',json={'revision':'stale','approved':True,'verified_staff':True}).status_code==409


@pytest.mark.asyncio
async def test_changed_destination_requires_fresh_consent_and_production_draft_prices_are_closed(transfer,monkeypatch):
    t=transfer
    proposal=tool_safety.propose({},'request_human_transfer',{'reason':'Support'},t.context)
    original=present(t.context,proposal)
    t.client.put(t.base+'/transfer-policy',json={'destination':'+12025550125','label':'Changed team','enabled':True})
    # Even a reapproved destination cannot reuse a readback of another target.
    with session_scope(write=True) as db:
        row=db.scalar(select(TransferPolicy));row.approved_at=now()
    result=await tool_safety.execute_confirmation({},original,proposal['id'])
    assert 'transfer_id' not in result.get('result',{})
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(CallTransfer))==0
    monkeypatch.setattr(settings,'app_env','production')
    with session_scope() as db:
        with pytest.raises(HTTPException) as error:transfers.eligible(db,t.ws,t.call_id)
        assert 'Approved prices' in error.value.detail


@pytest.mark.asyncio
async def test_deadline_and_spend_cap_block_transfer_before_job_or_provider(transfer):
    t=transfer
    proposal=tool_safety.propose({},'request_human_transfer',{'reason':'Support'},t.context)
    confirmed=present(t.context,proposal)
    with session_scope(write=True) as db:
        call=db.get(Call,t.call_id)
        call.metadata_data={**call.metadata_data,'carrier_deadline_at':(now()+timedelta(seconds=10)).timestamp()}
    result=await tool_safety.execute_confirmation({},confirmed,proposal['id'])
    assert 'transfer_id' not in result.get('result',{})
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(CallTransfer))==0


@pytest.mark.asyncio
async def test_frozen_callback_credentials_survive_carrier_key_rotation(transfer,monkeypatch):
    t=transfer;identity=await queue(t)
    transfers.begin(identity)
    monkeypatch.setattr(carrier_config,'credentials',lambda *args:{'auth_token':'rotated','account_sid':'different'})
    with session_scope() as db:
        assert carrier_config.call_credentials(db.get(Call,t.call_id))==t.credentials
    assert instruction(t,identity).status_code==200
    assert finish(t,identity).status_code==200


@pytest.mark.asyncio
async def test_child_spend_reservation_denial_has_no_request_or_job(transfer):
    from studio.models import WorkspaceSubscription
    t=transfer
    proposal=tool_safety.propose({},'request_human_transfer',{'reason':'Support'},t.context)
    confirmed=present(t.context,proposal)
    with session_scope(write=True) as db:
        budget=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==t.ws))
        budget.spend_cap_minor=0
    result=await tool_safety.execute_confirmation({},confirmed,proposal['id'])
    assert 'transfer_id' not in result.get('result',{})
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(CallTransfer))==0
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind=='call_transfer'))==0


@pytest.mark.asyncio
async def test_native_provider_adapter_uses_one_bounded_redirect_without_retries(monkeypatch):
    import httpx
    from studio.carrier_config import twilio_client
    payload={'id':'synthetic-transfer','parent_leg_id':'parent','parent_maximum_seconds':180,
             'credentials':{'auth_token':'fake','account_sid':'account','auth_id':'account'}}
    monkeypatch.setattr(settings,'media_public_origin','https://media.example.test')
    updates=[]
    def client(credentials,timeout):
        assert timeout==15
        def calls(identity):
            assert identity=='parent'
            def update(**kwargs):updates.append(kwargs);return SimpleNamespace(sid='parent')
            return SimpleNamespace(update=update)
        return SimpleNamespace(calls=calls)
    monkeypatch.setattr(carrier_config,'twilio_client',client)
    await transfer_provider.CarrierTransferProvider().submit({**payload,'provider':'twilio'})
    assert len(updates)==1 and updates[0]['time_limit']==180 and updates[0]['method']=='POST'
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'message':'call transferred'})
    real=httpx.AsyncClient
    monkeypatch.setattr(transfer_provider.httpx,'AsyncClient',lambda **kwargs:real(**kwargs,transport=httpx.MockTransport(handler)))
    await transfer_provider.CarrierTransferProvider().submit({**payload,'provider':'plivo'})
    assert len(requests)==1
    assert json.loads(requests[0].content)=={'legs':'aleg','aleg_method':'POST',
        'aleg_url':'https://media.example.test/v1/transfer-webhooks/synthetic-transfer/instructions'}
    assert str(requests[0].url)=='https://api.plivo.com/v1/Account/account/Call/parent/'


@pytest.mark.asyncio
async def test_workspace_kill_switch_blocks_pending_transfer_and_queues_one_parent_hangup(transfer):
    t=transfer;identity=await queue(t)
    body={'paused':True,'reason':'Synthetic transfer kill-switch acceptance'}
    path='/v1/operator/billing/workspaces/'+t.ws+'/control'
    assert t.client.put(path,json=body).status_code==200
    assert t.client.put(path,json=body).status_code==200
    assert transfers.begin(identity) is None
    with session_scope() as db:
        assert db.get(Call,t.call_id).state=='ending'
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind=='hangup'))==1
        assert db.get(CallTransfer,identity).state=='failed'


@pytest.mark.asyncio
async def test_workspace_kill_switch_stops_call_after_transfer_instructions(transfer):
    t=transfer;identity=await queue(t)
    transfers.begin(identity)
    assert fromstring(instruction(t,identity).text).find('Dial') is not None
    path='/v1/operator/billing/workspaces/'+t.ws+'/control'
    assert t.client.put(path,json={'paused':True,'reason':'Synthetic active staff-leg kill test'}).status_code==200
    with session_scope() as db:
        assert db.get(Call,t.call_id).state=='ending'
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind=='hangup'))==1
    assert fromstring(instruction(t,identity).text).find('Dial') is None
    assert finish(t,identity).status_code==200  # Final charges still settle while paused.
