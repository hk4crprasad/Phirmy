from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import asyncio
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

from cryptography.fernet import Fernet,InvalidToken
from sqlalchemy import select,text,update
from sqlalchemy.exc import DBAPIError
import pytest

from studio import key_provider,key_rotation
from studio.config import settings
from studio.db import engine,now,session_scope,uid
from studio.models import CipherRotationJob,CipherRotationAudit,ConnectorCredential,EmailOutbox,HTTPTool,HTTPToolVersion,Workspace,WebhookEndpoint
from studio.secrets import cipher,encrypt,decrypt,key_id,reencrypt


class FakeKeys:
    def __init__(self):self.active='key-a';self.keys={'key-a':Fernet.generate_key(),'key-b':Fernet.generate_key(),'app-v1':key_provider.legacy_key()}
    def active_key_id(self):return self.active
    def key(self,identity):
        if identity not in self.keys:raise key_provider.KeyUnavailable('Key unavailable')
        return self.keys[identity]


@pytest.fixture
def keys(monkeypatch):
    provider=FakeKeys();monkeypatch.setattr(key_provider,'provider',provider);return provider


def seed(workspace_id,secret,identity=None):
    with session_scope(write=True) as db:
        row=ConnectorCredential(id=identity or uid(),workspace_id=workspace_id,provider='rotation-'+uid()[:8],encrypted_data=secret)
        db.add(row);db.flush();return row.id


def queue(target,workspace_id=None):
    with session_scope(write=True) as db:return key_rotation.queue_rotation(db,target,'synthetic-operator',workspace_id).id


def finish(identity,batch_size=2):
    for _ in range(100):
        with session_scope() as db:state=db.get(CipherRotationJob,identity).state
        if state in {'completed','blocked','canceled'}:return state
        key_rotation.process_rotation_batch(batch_size)
    raise AssertionError('Rotation did not finish')


def test_legacy_and_prior_versioned_data_remain_readable_after_real_key_cutover(monkeypatch):
    secret='private synthetic payload'
    legacy=cipher().encrypt(secret.encode()).decode();previous=encrypt(secret)
    monkeypatch.setattr(settings,'cipher_keys_json',json.dumps({'next-key':Fernet.generate_key().decode()}))
    monkeypatch.setattr(settings,'cipher_active_key_id','next-key')
    current=encrypt(secret)
    assert current.startswith('vs1:next-key:') and key_id(previous)=='app-v1'
    assert [decrypt(value) for value in [legacy,previous,current]]==[secret]*3
    assert secret not in current


def test_envelope_authenticates_key_id_and_unknown_missing_corrupt_keys_fail_closed(keys):
    secret='sensitive fixture';token=encrypt(secret)
    keys.keys['alias']=keys.keys['key-a']
    with pytest.raises(InvalidToken):decrypt(token.replace('vs1:key-a:','vs1:alias:',1))
    with pytest.raises(InvalidToken):decrypt(token.replace('vs1:key-a:','vs1:unknown:',1))
    with pytest.raises(InvalidToken):decrypt(token[:-3]+'bad')
    keys.active='key-b';next_token=encrypt(secret)
    assert decrypt(token)==decrypt(next_token)==secret
    del keys.keys['key-a']
    with pytest.raises(InvalidToken):decrypt(token)
    assert decrypt(next_token)==secret


def test_reencrypt_preserves_authenticated_ciphertext_timestamp(keys):
    original=cipher().encrypt_at_time(b'original encrypted payload',1700000000).decode()
    keys.active='key-b';rotated=reencrypt(original,'key-b')
    assert decrypt(rotated)=='original encrypted payload'
    assert Fernet(keys.keys['key-b']).extract_timestamp(rotated.split(':',2)[2].encode())==1700000000


def test_fake_vault_pins_secret_version_and_never_uses_latest(monkeypatch):
    calls=[];material=Fernet.generate_key().decode()
    class Vault:
        def get_secret(self,name,version):calls.append((name,version));return SimpleNamespace(value=material)
    provider=key_provider.AzureVaultKeyProvider(Vault())
    monkeypatch.setattr(settings,'cipher_active_key_id','a'*32)
    assert provider.active_key_id()=='a'*32
    assert provider.key('a'*32)==material.encode()
    assert provider.key('a'*32)==material.encode()
    assert calls==[(settings.cipher_vault_secret_name,'a'*32)]
    class Broken:
        def get_secret(self,*args,**kwargs):raise RuntimeError('sensitive-provider-key-in-error')
    with pytest.raises(key_provider.KeyUnavailable) as error:key_provider.AzureVaultKeyProvider(Broken()).key('b'*32)
    assert 'sensitive-provider-key' not in str(error.value)


def test_job_resumes_across_batches_and_preserves_all_plaintext_and_scope(sample,keys):
    _,ws,_,_=sample
    with session_scope(write=True) as db:
        other=Workspace(name='Other cipher tenant');db.add(other);db.flush();other_id=other.id
    legacy=cipher().encrypt(b'legacy payload').decode()
    first=seed(ws,legacy);second=seed(ws,encrypt('versioned payload'));foreign=seed(other_id,encrypt('other workspace payload'))
    keys.active='key-b';identity=queue('key-b',ws)
    assert key_rotation.process_rotation_batch(1)
    with session_scope() as db:assert db.get(CipherRotationJob,identity).state=='queued'
    assert finish(identity,1)=='completed'
    with session_scope() as db:
        assert [decrypt(db.get(ConnectorCredential,row).encrypted_data) for row in [first,second]]==['legacy payload','versioned payload']
        assert all(key_id(db.get(ConnectorCredential,row).encrypted_data)=='key-b' for row in [first,second])
        assert key_id(db.get(ConnectorCredential,foreign).encrypted_data)=='key-a'
        job=db.get(CipherRotationJob,identity);assert job.rotated==2 and job.scanned==2
        assert db.scalar(select(CipherRotationAudit).where(CipherRotationAudit.job_id==identity,CipherRotationAudit.event=='completed'))
    del keys.keys['key-a']
    with session_scope() as db:assert decrypt(db.get(ConnectorCredential,second).encrypted_data)=='versioned payload'


def test_global_job_includes_outbox_and_webhook_secrets(account,keys):
    client,ws,base=account
    first=seed(ws,encrypt('tenant secret'))
    with session_scope(write=True) as db:
        mail=EmailOutbox(operation_key='rotation-outbox',recipient='synthetic@example.test',subject='Synthetic',encrypted_payload=encrypt('{"body":"synthetic"}'))
        db.add(mail);db.flush();mail_id=mail.id
        hook=WebhookEndpoint(workspace_id=ws,url='https://hooks.example.test',secret=encrypt('signing fixture'),event_types=['lead.created'])
        db.add(hook);db.flush();hook_id=hook.id
    keys.active='key-b';identity=queue('key-b')
    assert finish(identity)=='completed'
    with session_scope() as db:
        assert key_id(db.get(EmailOutbox,mail_id).encrypted_payload)=='key-b'
        assert key_id(db.get(ConnectorCredential,first).encrypted_data)=='key-b'
        assert key_id(db.get(WebhookEndpoint,hook_id).secret)=='key-b'
        assert decrypt(db.get(WebhookEndpoint,hook_id).secret)=='signing fixture'


def test_immutable_tool_versions_allow_ciphertext_only_under_a_real_running_lease(account,keys):
    _,ws,_=account
    with session_scope(write=True) as db:
        row=HTTPTool(workspace_id=ws,name='safe_lookup',description='Synthetic',config={'method':'GET'},encrypted_headers=encrypt('{"X-Key":"fixture"}'))
        db.add(row);db.flush()
        version=HTTPToolVersion(workspace_id=ws,tool_id=row.id,revision=1,name=row.name,description=row.description,config=row.config,encrypted_headers=row.encrypted_headers)
        db.add(version);db.flush();version_id=version.id
    keys.active='key-b'
    with pytest.raises(DBAPIError):
        with session_scope(write=True) as db:db.get(HTTPToolVersion,version_id).encrypted_headers=encrypt('{}')
    identity=queue('key-b',ws)
    assert finish(identity)=='completed'
    with session_scope() as db:
        row=db.get(HTTPToolVersion,version_id)
        assert decrypt(row.encrypted_headers)=='{"X-Key":"fixture"}' and row.config=={'method':'GET'}
        assert key_id(row.encrypted_headers)=='key-b'
    with pytest.raises(DBAPIError):
        with session_scope(write=True) as db:
            job=db.get(CipherRotationJob,identity);job.state='running';job.lease_token=uid();job.lease_until=now()+timedelta(minutes=1);db.flush()
            with key_rotation.rotation_authority(db,job):db.get(HTTPToolVersion,version_id).description='Tampered'
    with pytest.raises(DBAPIError):
        with session_scope(write=True) as db:
            job=db.get(CipherRotationJob,identity);job.state='running';job.lease_token=uid();job.lease_until=now()-timedelta(seconds=1);db.flush()
            with key_rotation.rotation_authority(db,job):db.get(HTTPToolVersion,version_id).encrypted_headers=encrypt('{}')


def test_corrupt_record_blocks_without_skipping_or_leaking_and_can_resume(account,keys):
    _,ws,_=account
    bad=seed(ws,'not-a-ciphertext');keys.active='key-b';identity=queue('key-b',ws)
    assert finish(identity)=='blocked'
    with session_scope() as db:
        job=db.get(CipherRotationJob,identity);assert job.scanned==0
        assert job.error['record_id']==bad and 'not-a-ciphertext' not in json.dumps(job.error)
    with session_scope(write=True) as db:
        db.get(ConnectorCredential,bad).encrypted_data=encrypt('repaired credential')
        job=db.get(CipherRotationJob,identity);job.state='queued';job.error={}
    assert finish(identity)=='completed'


def test_parallel_workers_claim_each_batch_once_and_rotation_audit_is_immutable(account,keys):
    _,ws,_=account
    for _ in range(8):seed(ws,encrypt('parallel fixture'))
    keys.active='key-b';identity=queue('key-b',ws)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:key_rotation.process_rotation_batch(1),range(16)))
    assert finish(identity)=='completed'
    with session_scope() as db:
        job=db.get(CipherRotationJob,identity);assert job.rotated==8 and job.scanned==8
        audit=db.scalar(select(CipherRotationAudit).where(CipherRotationAudit.job_id==identity));audit_id=audit.id
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:connection.execute(update(CipherRotationAudit).where(CipherRotationAudit.id==audit_id).values(event='altered'))


def test_operator_api_is_browser_only_and_allowlist_closed(account,keys,monkeypatch):
    client,_,_=account
    assert client.get('/v1/operator/encryption').status_code==403
    monkeypatch.setattr(settings,'cipher_rotation_operator_emails','qa@example.test')
    assert client.get('/v1/operator/encryption').status_code==200
    keys.active='key-b'
    response=client.post('/v1/operator/encryption/rotations',json={'target_key_id':'key-b'})
    assert response.status_code==202
    identity=response.json()['id']
    assert client.post('/v1/operator/encryption/rotations/'+identity+'/pause',json={}).json()['state']=='paused'
    assert client.post('/v1/operator/encryption/rotations/'+identity+'/resume',json={}).json()['state']=='queued'


def test_expired_worker_claim_is_recovered_and_active_key_changes_block_before_writes(account,keys):
    _,ws,_=account;row_id=seed(ws,encrypt('recovery fixture'));keys.active='key-b';identity=queue('key-b',ws)
    with session_scope(write=True) as db:
        job=db.get(CipherRotationJob,identity);job.state='running';job.lease_token='expired-owner';job.lease_until=now()-timedelta(seconds=1)
    keys.active='key-a'
    assert key_rotation.process_rotation_batch() is False
    with session_scope() as db:
        job=db.get(CipherRotationJob,identity)
        assert job.state=='blocked' and job.error['code']=='active_key_changed'
        assert key_id(db.get(ConnectorCredential,row_id).encrypted_data)=='key-a'
    keys.active='key-b'
    with session_scope(write=True) as db:db.get(CipherRotationJob,identity).state='queued'
    assert finish(identity)=='completed'


def test_encryption_material_cannot_be_forwarded_into_model_context(keys):
    from studio.prompt_safety import redact_text
    encrypt('register active material')
    material=keys.keys['key-a'].decode()
    assert material not in redact_text('Accidentally pasted '+material)


@pytest.mark.asyncio
async def test_dedicated_dispatcher_drives_real_rotation_batches(account,keys):
    from studio.workers import worker_loop
    _,ws,_=account;seed(ws,encrypt('dispatcher fixture'))
    keys.active='key-b';identity=queue('key-b',ws);stop=asyncio.Event()
    task=asyncio.create_task(worker_loop(stop,local_browser_sessions=False))
    try:
        def state():
            with session_scope() as db:return db.get(CipherRotationJob,identity).state
        for _ in range(200):
            if await asyncio.to_thread(state)=='completed':break
            await asyncio.sleep(.025)
        assert await asyncio.to_thread(state)=='completed'
    finally:stop.set();await asyncio.wait_for(task,10)


def test_actual_cli_queues_and_runs_an_isolated_job(account,keys):
    _,ws,_=account
    row=seed(ws,cipher().encrypt(b'cli legacy fixture').decode());keys.active='key-b'
    runenv={**os.environ,'CIPHER_KEY_PROVIDER':'local','CIPHER_ACTIVE_KEY_ID':'key-b',
            'CIPHER_KEYS_JSON':json.dumps({name:value.decode() for name,value in keys.keys.items() if name!='app-v1'})}
    root=Path(__file__).resolve().parents[1];command=[str(root/'.venv/bin/python'),'scripts/reencrypt_secrets.py']
    def run(args):
        response=subprocess.run(command+args,cwd=root,env=runenv,capture_output=True,text=True,timeout=20)
        assert response.returncode==0,response.stdout
        assert all(material.decode() not in response.stdout for material in keys.keys.values())
        return json.loads(response.stdout)
    identity=run(['--queue','--target-key-id','key-b','--workspace-id',ws])['queued_job_id']
    assert run(['--run-one-batch'])['processed_batch'] is True
    result=run([]);assert any(job['id']==identity and job['state']=='completed' for job in result['jobs'])
    with session_scope() as db:assert decrypt(db.get(ConnectorCredential,row).encrypted_data)=='cli legacy fixture'
