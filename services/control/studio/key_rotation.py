"""Leased, resumable, audited ciphertext migration; plaintext never enters records."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import re

from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from sqlalchemy import event,or_,select,text

from .db import Base,engine,now,session_scope,uid,as_dict
from .models import CipherRotationJob,CipherRotationAudit,WebhookEndpoint,SchemaMigration
from .key_provider import get_provider,valid_id
from .secrets import encrypt,decrypt,key_id,reencrypt
from .security import active_user,db_dependency
from .config import settings

authority=ContextVar('cipher_rotation_authority',default='')
router=APIRouter(prefix='/v1/operator/encryption')


if engine.dialect.name=='sqlite':
    @event.listens_for(engine,'connect')
    def sqlite_authority(connection,_):
        connection.create_function('cipher_rotation_authority',0,lambda:authority.get())


def encrypted_models():
    output={}
    for mapper in Base.registry.mappers:
        columns=[column.name for column in mapper.columns if column.name.startswith('encrypted_')]
        if mapper.class_ is WebhookEndpoint:columns.append('secret')
        if columns:output[mapper.local_table.name]=(mapper.class_,sorted(columns))
    return output


def install_rotation_guard(connection):
    """Only the ciphertext field may change; metadata/version immutability stays."""
    table='http_tool_versions'
    columns=[column.name for column in Base.metadata.tables[(('voice_studio.' if engine.dialect.name=='postgresql' else '')+table)].columns
             if column.name!='encrypted_headers']
    if engine.dialect.name=='postgresql':
        connection.execute(text('''CREATE OR REPLACE FUNCTION voice_studio.authorized_tool_reencryption()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF (to_jsonb(NEW)-'encrypted_headers')=(to_jsonb(OLD)-'encrypted_headers') AND EXISTS(
              SELECT 1 FROM voice_studio.cipher_rotation_jobs j WHERE
              j.id||':'||j.lease_token=current_setting('app.cipher_rotation_authority',true)
              AND j.state='running' AND j.lease_until>clock_timestamp()
              AND (j.workspace_id IS NULL OR j.workspace_id=OLD.workspace_id)
              AND left(NEW.encrypted_headers,length('vs1:'||j.target_key_id||':'))='vs1:'||j.target_key_id||':'
            ) THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'append-only record'; END; $$'''))
        connection.execute(text('DROP TRIGGER IF EXISTS immutable_record ON voice_studio.http_tool_versions'))
        connection.execute(text('CREATE TRIGGER immutable_record BEFORE DELETE ON voice_studio.http_tool_versions FOR EACH ROW EXECUTE FUNCTION voice_studio.reject_record_mutation()'))
        connection.execute(text('DROP TRIGGER IF EXISTS authorized_tool_reencryption ON voice_studio.http_tool_versions'))
        connection.execute(text('CREATE TRIGGER authorized_tool_reencryption BEFORE UPDATE ON voice_studio.http_tool_versions FOR EACH ROW EXECUTE FUNCTION voice_studio.authorized_tool_reencryption()'))
    else:
        unchanged=' AND '.join('NEW.'+name+' IS OLD.'+name for name in columns)
        connection.execute(text('DROP TRIGGER IF EXISTS immutable_http_tool_versions_update'))
        connection.execute(text('DROP TRIGGER IF EXISTS authorized_tool_reencryption'))
        connection.execute(text(f'''CREATE TRIGGER authorized_tool_reencryption BEFORE UPDATE ON http_tool_versions
            WHEN NOT (({unchanged}) AND EXISTS(SELECT 1 FROM cipher_rotation_jobs j
              WHERE j.id||':'||j.lease_token=cipher_rotation_authority() AND j.state='running'
              AND j.lease_until>CURRENT_TIMESTAMP AND (j.workspace_id IS NULL OR j.workspace_id=OLD.workspace_id)
              AND substr(NEW.encrypted_headers,1,length('vs1:'||j.target_key_id||':'))='vs1:'||j.target_key_id||':'))
            BEGIN SELECT RAISE(ABORT,'append-only record'); END'''))


@contextmanager
def rotation_authority(db,job):
    token=authority.set(job.id+':'+job.lease_token)
    try:
        if engine.dialect.name=='postgresql':
            db.execute(text("SELECT set_config('app.cipher_rotation_authority',:authority,true)"),{'authority':authority.get()})
        yield
        db.flush()
    finally:authority.reset(token)


def queue_rotation(db,target,requested_by,workspace_id=None):
    db.scalar(select(SchemaMigration).order_by(SchemaMigration.id).limit(1).with_for_update())
    valid_id(target)
    provider=get_provider()
    if target!=provider.active_key_id():raise ValueError('Target must be the active encryption key ID')
    provider.key(target)
    if db.scalar(select(CipherRotationJob.id).where(CipherRotationJob.state.in_(['queued','running']),
        CipherRotationJob.workspace_id==workspace_id)):
        raise ValueError('An encryption rotation is already active for this scope')
    job=CipherRotationJob(id=uid(),workspace_id=workspace_id,target_key_id=target,requested_by=requested_by,
        tables=sorted(encrypted_models()),cursor={'table':0,'last_id':''},state='queued',scanned=0,rotated=0,error={})
    db.add(job);db.flush();db.add(CipherRotationAudit(job_id=job.id,event='requested',data={'target_key_id':target,'workspace_id':workspace_id}))
    return job


class RotationLost(Exception):pass


def process_rotation_batch(batch_size=25):
    with session_scope(write=True) as db:
        job=db.scalar(select(CipherRotationJob).where(or_(CipherRotationJob.state=='queued',
            (CipherRotationJob.state=='running') & (CipherRotationJob.lease_until<=now()))).order_by(
            CipherRotationJob.created_at,CipherRotationJob.id).limit(1).with_for_update(skip_locked=True))
        if not job:return False
        job.state='running';job.lease_token=uid();job.lease_until=now()+timedelta(minutes=3)
        identity,lease=job.id,job.lease_token
    location={}
    try:
        with session_scope(write=True) as db:
            job=db.get(CipherRotationJob,identity,with_for_update=True)
            if job.state!='running' or job.lease_token!=lease or job.lease_until<=now():raise RotationLost()
            if job.target_key_id!=get_provider().active_key_id():raise ValueError('active_key_changed')
            mappings=encrypted_models();position=job.cursor.get('table',0);last=job.cursor.get('last_id','')
            left=batch_size
            with rotation_authority(db,job):
                while position<len(job.tables) and left:
                    table=job.tables[position]
                    if table not in mappings:raise ValueError('schema_changed')
                    model,columns=mappings[table]
                    if job.workspace_id and not hasattr(model,'workspace_id'):
                        position+=1;last='';continue
                    query=select(model).where(model.id>last).order_by(model.id).limit(left).with_for_update()
                    if job.workspace_id:query=query.where(model.workspace_id==job.workspace_id)
                    rows=list(db.scalars(query))
                    if not rows:position+=1;last='';continue
                    for row in rows:
                        if job.target_key_id!=get_provider().active_key_id():raise ValueError('active_key_changed')
                        for column in columns:
                            value=getattr(row,column)
                            if value is None:continue
                            location={'table':table,'record_id':row.id,'column':column}
                            plain=decrypt(value)
                            if key_id(value)!=job.target_key_id:
                                setattr(row,column,reencrypt(value,job.target_key_id));job.rotated+=1
                        job.scanned+=1;left-=1;last=row.id
                    if job.lease_until<=now():raise RotationLost()
                if job.target_key_id!=get_provider().active_key_id():raise ValueError('active_key_changed')
                job.cursor={'table':position,'last_id':last}
                db.flush() # Guard checks the running lease before clearing it.
            job.state='completed' if position>=len(job.tables) else 'queued'
            job.lease_token=None;job.lease_until=None;job.error={}
            db.add(CipherRotationAudit(job_id=identity,event=job.state,data={'scanned':job.scanned,'rotated':job.rotated}))
        return True
    except RotationLost:return False
    except Exception as error:
        with session_scope(write=True) as db:
            job=db.get(CipherRotationJob,identity,with_for_update=True)
            if job.lease_token!=lease:return False
            code='active_key_changed' if isinstance(error,ValueError) and str(error)=='active_key_changed' else 'reencryption_failed'
            job.state='blocked';job.error={'code':code,**location};job.lease_token=None;job.lease_until=None
            db.add(CipherRotationAudit(job_id=identity,event='blocked',data=job.error))
        return False


def operator(request:Request,db=Depends(db_dependency,scope='function')):
    from .account_policy import require_verified
    user=active_user(request,db)
    require_verified(db,user)
    allowed={email.strip().lower() for email in settings.cipher_rotation_operator_emails.split(',') if email.strip()}
    if user.email.lower() not in allowed:raise HTTPException(403,'Encryption operator access is required')
    return user


class RotationWrite(BaseModel):
    target_key_id:str=Field(min_length=1,max_length=64)
    workspace_id:str|None=Field(default=None,max_length=36)


@router.get('')
def status(user=Depends(operator),db=Depends(db_dependency,scope='function')):
    return {'provider':settings.cipher_key_provider,'active_key_id':get_provider().active_key_id(),
            'jobs':[as_dict(row) for row in db.scalars(select(CipherRotationJob).order_by(CipherRotationJob.created_at.desc()).limit(50))]}


@router.post('/rotations',status_code=202)
def start(body:RotationWrite,user=Depends(operator),db=Depends(db_dependency,scope='function')):
    return as_dict(queue_rotation(db,body.target_key_id,user.id,body.workspace_id))


@router.post('/rotations/{job_id}/{action}')
def change(job_id:str,action:str,user=Depends(operator),db=Depends(db_dependency,scope='function')):
    job=db.get(CipherRotationJob,job_id,with_for_update=True)
    if not job:raise HTTPException(404,'Encryption job not found')
    if job.state=='running':raise HTTPException(409,'Wait for the current bounded batch before changing this job')
    if action=='resume' and job.state in {'paused','blocked'}:
        if job.target_key_id!=get_provider().active_key_id():raise HTTPException(409,'Restore the pinned active key before resuming')
        job.state='queued';job.error={}
    elif action=='pause' and job.state=='queued':job.state='paused'
    elif action=='cancel' and job.state in {'queued','paused','blocked'}:job.state='canceled'
    else:raise HTTPException(409,'That job transition is unavailable')
    db.add(CipherRotationAudit(job_id=job.id,event=action,data={'operator_id':user.id}))
    return as_dict(job)
