"""Disposable PostgreSQL key migration, restricted-role and fencing acceptance."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time

root=Path.cwd();name='cipher-pg-'+secrets.token_hex(4);docker=['docker','--host=unix:///var/run/docker.sock']
with tempfile.TemporaryDirectory(prefix='cipher-pg-') as temporary:
    folder=Path(temporary);password=secrets.token_urlsafe(24);runtime_password=secrets.token_urlsafe(24)
    envfile=folder/'postgres.env';envfile.write_text('POSTGRES_PASSWORD='+password+'\n');envfile.chmod(0o600)
    try:
        result=subprocess.run(docker+['run','--rm','-d','--name',name,'--env-file',str(envfile),'-p','127.0.0.1::5432','postgres:17-alpine'],capture_output=True)
        assert result.returncode==0,'Disposable PostgreSQL did not start'
        for _ in range(60):
            if subprocess.run(docker+['exec',name,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
            time.sleep(.25)
        port=json.loads(subprocess.check_output(docker+['inspect',name]))[0]['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        env=os.environ|{'APP_ENV':'test','DATABASE_URL':'postgresql://postgres:'+password+'@127.0.0.1:'+port+'/postgres',
            'SUPABASE_DB_PASSWORD':'','DATA_DIR':str(folder/'data'),'APP_SECRET':'isolated-crypto-test-'+'x'*48,
            'OBJECT_STORAGE_PROVIDER':'local','AZURE_STORAGE_CONNECTION_STRING':'','AZURE_STORAGE_ACCOUNT_URL':'',
            'REDIS_URL':'','VECTOR_ENDPOINT':'','OPENAI_API_KEY':'','SMTP_HOST':'','REQUIRE_EMAIL_VERIFICATION':'false',
            'CIPHER_KEY_PROVIDER':'local','CIPHER_KEYS_JSON':'','CIPHER_ACTIVE_KEY_ID':'app-v1',
            'QA_RUNTIME_PASSWORD':runtime_password,'PYTHONPATH':str(root/'services/control')}
        def run(code,environment):
            result=subprocess.run([str(root/'.venv/bin/python'),'-c',code],env=environment,capture_output=True,text=True)
            if result.returncode:
                print('Failure locations:',re.findall(r'File "([^\"]+)", line (\d+)',result.stderr)[-4:])
                print('Error types:',re.findall(r'(?:psycopg.errors.|^)([A-Za-z]+Error):',result.stderr,re.M)[-3:])
                raise RuntimeError('Disposable key migration failed; credentials withheld')
            return result.stdout.strip()
        run('''
import os,json
from psycopg import sql
from sqlalchemy import text
from studio.main import initialize_database
from studio.db import engine,session_scope
from studio.models import Workspace,ConnectorCredential,HTTPTool,HTTPToolVersion,EmailOutbox,WebhookEndpoint
from studio.secrets import cipher
initialize_database();initialize_database()
old=cipher().encrypt_at_time(b'legacy synthetic secret',1700000000).decode()
with session_scope(write=True) as db:
 ws=Workspace(name='Cipher PostgreSQL QA');db.add(ws);db.flush()
 db.add(ConnectorCredential(workspace_id=ws.id,provider='synthetic',encrypted_data=old))
 tool=HTTPTool(workspace_id=ws.id,name='synthetic',description='Original',config={'method':'GET'},encrypted_headers=old)
 db.add(tool);db.flush()
 db.add(HTTPToolVersion(workspace_id=ws.id,tool_id=tool.id,revision=1,name=tool.name,description=tool.description,config=tool.config,encrypted_headers=old))
 db.add(EmailOutbox(operation_key='cipher-pg',recipient='synthetic@example.test',subject='Synthetic',encrypted_payload=old))
 db.add(WebhookEndpoint(workspace_id=ws.id,url='https://hooks.example.test',secret=old,event_types=[]))
with engine.begin() as db:
 db.exec_driver_sql(sql.SQL('CREATE ROLE cipher_runtime LOGIN PASSWORD {}').format(sql.Literal(os.environ['QA_RUNTIME_PASSWORD'])).as_string())
 db.execute(text('GRANT USAGE ON SCHEMA voice_studio TO cipher_runtime'))
 db.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA voice_studio TO cipher_runtime'))
 db.execute(text('REVOKE CREATE ON SCHEMA voice_studio FROM cipher_runtime'))
''',env)
        runtime={**env,'DATABASE_URL':'postgresql://cipher_runtime:'+runtime_password+'@127.0.0.1:'+port+'/postgres'}
        print(run('''
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from cryptography.fernet import Fernet
from sqlalchemy import select,text,update
from sqlalchemy.exc import DBAPIError
from studio.main import verify_database_schema
from studio.config import settings
from studio.db import engine,session_scope,now,uid
from studio.models import CipherRotationJob,CipherRotationAudit,HTTPToolVersion
from studio.key_rotation import queue_rotation,process_rotation_batch,encrypted_models,rotation_authority
from studio.secrets import decrypt,key_id,encrypt
verify_database_schema()
settings.cipher_keys_json=json.dumps({'key-v2':Fernet.generate_key().decode()});settings.cipher_active_key_id='key-v2'
with session_scope(write=True) as db:identity=queue_rotation(db,'key-v2','isolated-operator').id
with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:process_rotation_batch(1),range(16)))
for _ in range(30):
 with session_scope() as db:state=db.get(CipherRotationJob,identity).state
 if state=='completed':break
 assert state=='queued'
 process_rotation_batch(2)
with session_scope() as db:
 job=db.get(CipherRotationJob,identity);assert job.state=='completed' and job.rotated==5 and job.scanned==5
 for model,columns in encrypted_models().values():
  for row in db.scalars(select(model)):
   for column in columns:
    value=getattr(row,column)
    if value is not None:assert key_id(value)=='key-v2' and decrypt(value)=='legacy synthetic secret'
 version=db.scalar(select(HTTPToolVersion));version_id=version.id
 audit=db.scalar(select(CipherRotationAudit));audit_id=audit.id
with engine.connect() as db:assert not db.execute(text("SELECT has_schema_privilege(current_user,'voice_studio','CREATE')")).scalar()
for mode in ['unleased','metadata','expired']:
 blocked=False
 try:
  with session_scope(write=True) as db:
   job=db.get(CipherRotationJob,identity);job.state='running';job.lease_token=uid()
   job.lease_until=now()+timedelta(seconds=-1 if mode=='expired' else 60);db.flush()
   if mode=='unleased':db.get(HTTPToolVersion,version_id).encrypted_headers=encrypt('tampered')
   else:
    with rotation_authority(db,job):
     version=db.get(HTTPToolVersion,version_id)
     if mode=='metadata':version.description='Tampered'
     else:version.encrypted_headers=encrypt('tampered')
 except DBAPIError:blocked=True
 assert blocked,mode+' must remain blocked'
blocked=False
try:
 with engine.begin() as db:db.execute(update(CipherRotationAudit).where(CipherRotationAudit.id==audit_id).values(event='tampered'))
except DBAPIError:blocked=True
assert blocked
print('PostgreSQL keys: backward reads, versioned rewrite, concurrent checkpoints, restricted role, ciphertext-only lease guard and immutable audit passed')
''',runtime))
    finally:subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
