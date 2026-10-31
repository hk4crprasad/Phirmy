"""Confirmed, approved carrier handoff; uncertain writes are never replayed."""
from datetime import timedelta
import json
import math

from fastapi import HTTPException
from sqlalchemy import select

from . import admission
from .config import settings
from .db import now, session_scope
from .domain import enqueue, emit
from .models import Call, CallTransfer, TransferPolicy, Workspace, TariffSnapshot, WorkspaceSubscription
from .secrets import decrypt, encrypt

ACTIVE = {'queued','submitting','accepted','unknown','connected'}


def cost_key(identity):
    return 'transfer-child:'+identity


def locked(db, identity):
    workspace_id=db.scalar(select(CallTransfer.workspace_id).where(CallTransfer.id==identity))
    if workspace_id is None:return None
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    return db.scalar(select(CallTransfer).where(CallTransfer.id==identity).with_for_update()
                     .execution_options(populate_existing=True))


def snapshot(row):
    return json.loads(decrypt(row.encrypted_snapshot))


def result(row):
    return {'transfer_id':row.id, 'state':row.state, 'accepted':True,
            'completion_confirmed':row.state=='completed',
            'message':'Transfer requested; a connection to the team is not confirmed.'}


def eligible(db, workspace_id, call_id):
    if not settings.live_transfer_enabled or not settings.live_calls_enabled or not settings.paid_activation_enabled:
        raise HTTPException(409,'Live transfer activation is disabled')
    spending=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==workspace_id))
    if spending and (spending.operator_paused or spending.billing_blocked):
        raise HTTPException(409,'This workspace is paused')
    call=db.scalar(select(Call).where(Call.workspace_id==workspace_id,Call.id==call_id))
    policy=db.scalar(select(TransferPolicy).where(TransferPolicy.workspace_id==workspace_id))
    if (not call or call.mode!='live' or call.transport!='pstn' or call.state!='connected'
            or not call.provider_call_id or call.metadata_data.get('phone_trial_id')):
        raise HTTPException(409,'This call cannot be transferred')
    if not policy or not policy.enabled or policy.approved_at is None:
        raise HTTPException(409,'The staff destination needs operator approval')
    provider=call.metadata_data.get('provider')
    if provider not in {'twilio','plivo'}:
        raise HTTPException(409,'This carrier does not support live transfer')
    tariff=db.get(TariffSnapshot,call.metadata_data.get('tariff_id'))
    if not tariff or tariff.workspace_id!=workspace_id or tariff.call_id!=call.id:
        raise HTTPException(409,'An admitted call tariff is required')
    if settings.app_env=='production' and tariff.content.get('status')!='APPROVED':
        raise HTTPException(409,'Approved prices are required for paid transfer')
    if not settings.media_public_origin.startswith('https://'):
        raise HTTPException(409,'A public HTTPS media origin is required')
    return call,policy


def proposal(args, context):
    if set(args)!={'reason'} or not isinstance(args['reason'],str) or len(args['reason'])>300:
        raise HTTPException(422,'A short transfer reason is required')
    with session_scope() as db:
        call,policy=eligible(db,context['workspace_id'],context.get('call_id'))
        return {'reason':args['reason'],'team':policy.label,'destination_revision':policy.revision}


def request(args, context):
    from .tool_safety import approved
    if not approved('request_human_transfer',args,context):
        raise HTTPException(409,'Confirm the complete transfer request first')
    ws=context['workspace_id']
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id==ws).with_for_update())
        call=db.scalar(select(Call).where(Call.workspace_id==ws,Call.id==context.get('call_id')).with_for_update())
        previous=db.scalar(select(CallTransfer).where(CallTransfer.workspace_id==ws,CallTransfer.call_id==call.id)) if call else None
        if previous:
            return result(previous)  # No second dial, including failed or unknown writes.
        call,policy=eligible(db,ws,context.get('call_id'))
        if args.get('destination_revision')!=policy.revision or args.get('team')!=policy.label:
            raise HTTPException(409,'The staff destination changed; request a new readback')
        stamp=now()
        deadline_stamp=call.metadata_data.get('carrier_deadline_at')
        if deadline_stamp is None:
            # Never create a fresh deadline from a transfer request.
            raise HTTPException(409,'The admitted carrier deadline is unavailable')
        from datetime import datetime,timezone
        deadline=datetime.fromtimestamp(float(deadline_stamp),tz=timezone.utc)
        seconds=min(policy.maximum_seconds,math.floor((deadline-stamp).total_seconds())-20)
        if seconds<5:
            raise HTTPException(409,'Too little admitted call time remains for transfer')
        from .carrier_config import call_credentials
        credentials=call_credentials(call)
        if not credentials.get('auth_token') or not credentials.get('account_sid' if call.metadata_data['provider']=='twilio' else 'auth_id'):
            raise HTTPException(409,'The call carrier binding is unavailable')
        from .db import uid
        row=CallTransfer(id=uid(),workspace_id=ws,call_id=call.id,consent_id=context['_approved_consent_id'],
            provider=call.metadata_data['provider'],parent_leg_id=call.provider_call_id,maximum_seconds=seconds,
            deadline_at=deadline,encrypted_snapshot=encrypt(json.dumps({'destination':decrypt(policy.encrypted_destination),
                'team':policy.label,'revision':policy.revision,'credentials':credentials,
                'parent_maximum_seconds':call.metadata_data['admitted_max_seconds']})))
        db.add(row);db.flush()
        # Parent wallet, voice allowance and carrier hold remain active until
        # its real hangup. Only the new staff leg needs another reservation.
        admission.provider_hold({'workspace_id':ws,'call_id':call.id,'db':db},cost_key(row.id),row.provider,
                                {'carrier_ms':((seconds+59)//60)*60_000})
        call.metadata_data={**call.metadata_data,'transfer_request_id':row.id}
        enqueue(db,ws,'call_transfer',{'transfer_id':row.id})
        emit(db,ws,'transfer.requested',{'call_id':call.id,'transfer_id':row.id})
        return result(row)


def retain_parent(db,call):
    identity=call.metadata_data.get('transfer_request_id')
    if not identity:return False
    row=db.scalar(select(CallTransfer).where(CallTransfer.workspace_id==call.workspace_id,CallTransfer.id==identity))
    if row and row.state in ACTIVE and call.state not in {'completed','failed','canceled','busy','no_answer'}:
        call.metadata_data={**call.metadata_data,'transfer_media_detached':True}
        return True
    return False


def begin(identity):
    with session_scope(write=True) as db:
        row=locked(db,identity)
        if row is None:return None
        if row.state!='queued':
            if row.state=='submitting':
                row.state='unknown';row.error_code='submission_interrupted'
                admission.finish(db,row.workspace_id,cost_key(row.id),unknown=True)
            return None
        call=db.get(Call,row.call_id)
        try:
            _,policy=eligible(db,row.workspace_id,row.call_id)
            if policy.revision!=snapshot(row)['revision'] or now()>=row.deadline_at-timedelta(seconds=20):
                raise HTTPException(409,'Transfer permission or deadline changed')
        except HTTPException:
            row.state='failed';row.error_code='preflight_denied'
            admission.finish(db,row.workspace_id,cost_key(row.id))
            return None
        row.state='submitting';row.submitted_at=now()
        return {'id':row.id,'provider':row.provider,'parent_leg_id':row.parent_leg_id,**snapshot(row)}


def submitted(identity, successful):
    with session_scope(write=True) as db:
        row=locked(db,identity)
        if row is None or row.state not in {'submitting','unknown'}:return
        if successful:
            row.state='accepted'
        else:
            row.state='unknown';row.error_code='provider_outcome_unknown'
            admission.finish(db,row.workspace_id,cost_key(row.id),unknown=True)
            emit(db,row.workspace_id,'transfer.unknown',{'transfer_id':row.id,'call_id':row.call_id})


async def transfer_job(job_id):
    import asyncio
    from .async_work import durable_to_thread
    from .job_control import get_job
    def identity():
        with session_scope() as db:return get_job(db,job_id).payload['transfer_id']
    identity=await asyncio.to_thread(identity)
    payload=await durable_to_thread(begin,identity)
    if payload is None:return
    from .transfer_provider import provider
    try:
        await provider.submit(payload)
    except BaseException:
        await durable_to_thread(submitted,identity,False)
        raise
    else:
        await durable_to_thread(submitted,identity,True)
