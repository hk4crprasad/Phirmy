"""Disposable PostgreSQL upgrade + restricted-role concurrent worker acceptance."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

root=Path.cwd();name='worker-pg-'+secrets.token_hex(4)
docker=['docker','--host=unix:///var/run/docker.sock']
with tempfile.TemporaryDirectory(prefix='worker-pg-') as temporary:
    folder=Path(temporary);password=secrets.token_urlsafe(24);runtime_password=secrets.token_urlsafe(24)
    envfile=folder/'postgres.env';envfile.write_text('POSTGRES_PASSWORD='+password+'\n');envfile.chmod(0o600)
    try:
        started=subprocess.run(docker+['run','--rm','-d','--name',name,'--env-file',str(envfile),'-p','127.0.0.1::5432','postgres:17-alpine'],capture_output=True)
        assert started.returncode==0,'Disposable PostgreSQL did not start'
        for _ in range(60):
            if subprocess.run(docker+['exec',name,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
            time.sleep(.25)
        port=json.loads(subprocess.check_output(docker+['inspect',name]))[0]['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        env=os.environ|{'APP_ENV':'test','DATABASE_URL':'postgresql://postgres:'+password+'@127.0.0.1:'+port+'/postgres','SUPABASE_DB_PASSWORD':'',
            'DATA_DIR':str(folder/'data'),'APP_SECRET':'isolated-worker-test-'+'x'*48,'OBJECT_STORAGE_PROVIDER':'local','AZURE_STORAGE_CONNECTION_STRING':'',
            'AZURE_STORAGE_ACCOUNT_URL':'','REDIS_URL':'','VECTOR_ENDPOINT':'','VECTOR_API_KEY':'','EMBEDDING_API_KEY':'','OPENAI_API_KEY':'',
            'SMTP_HOST':'','REQUIRE_EMAIL_VERIFICATION':'false','SESSION_SECURE':'false','QA_RUNTIME_PASSWORD':runtime_password,'PYTHONPATH':str(root/'services/control')}
        def run(code,environment):
            result=subprocess.run([str(root/'.venv/bin/python'),'-c',code],env=environment,capture_output=True,text=True)
            if result.returncode:
                import re
                print('Failure locations:',re.findall(r'File "([^\"]+)", line (\d+)',result.stderr)[-4:])
                print('Error types:',re.findall(r'(?:psycopg.errors.|^)([A-Za-z]+Error):',result.stderr,re.M)[-3:])
                raise RuntimeError('Disposable PostgreSQL worker check failed; credentials withheld')
            return result.stdout.strip()
        run('''
import os,json
from pathlib import Path
from psycopg import sql
from sqlalchemy import text
from fastapi.testclient import TestClient
from studio.main import initialize_database,create_app,verify_database_schema
from studio.db import engine
from scripts.qa_accounts import bootstrap_account
initialize_database()
# Simulate upgrading the previous release, not only creating a fresh database.
with engine.begin() as db:db.execute(text('ALTER TABLE voice_studio.jobs DROP COLUMN lease_token'))
try:verify_database_schema()
except RuntimeError:pass
else:raise AssertionError('Missing worker migration was accepted')
initialize_database();initialize_database()
with TestClient(create_app(start_worker=False)) as client:
 response=bootstrap_account(client, '/v1/auth/signup',json={'name':'Workers QA','email':'workers@example.test','password':'Long-Isolated-Password','workspace_name':'Workers QA'})
 assert response.status_code==200
 Path(os.environ['DATA_DIR']+'/identity.json').write_text(json.dumps(response.json()['workspaces'][0]['id']))
 client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
 key=client.post('/v1/workspaces/'+response.json()['workspaces'][0]['id']+'/keys',json={'name':'Upgrade survivor','scopes':['kb:read']})
 assert key.status_code==201
 Path(os.environ['DATA_DIR']+'/key.json').write_text(json.dumps(key.json()))
# Existing credentials must survive additive policy migration as well as fresh DDL.
with engine.begin() as db:
 for column in ['expires_at','last_used_at','requests_per_minute']:
  db.execute(text('ALTER TABLE voice_studio.api_keys DROP COLUMN '+column))
try:verify_database_schema()
except RuntimeError:pass
else:raise AssertionError('Missing key-policy migration was accepted')
initialize_database();initialize_database();verify_database_schema()
with engine.begin() as db:
 db.exec_driver_sql(sql.SQL('CREATE ROLE worker_runtime LOGIN PASSWORD {}').format(sql.Literal(os.environ['QA_RUNTIME_PASSWORD'])).as_string())
 db.execute(text('GRANT USAGE ON SCHEMA voice_studio TO worker_runtime'))
 db.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA voice_studio TO worker_runtime'))
 db.execute(text('REVOKE CREATE ON SCHEMA voice_studio FROM worker_runtime'))
''',env)
        env['DATABASE_URL']='postgresql://worker_runtime:'+runtime_password+'@127.0.0.1:'+port+'/postgres'
        output=run('''
import asyncio,json,os,threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select,text
from studio.db import engine,session_scope,now,uid
from studio.models import Job,KnowledgeBase,APIKey
from studio.main import verify_database_schema
from studio.job_control import claim,get_job,LeaseLost
from studio import workers
verify_database_schema()
with engine.connect() as db:assert not db.execute(text("SELECT has_schema_privilege(current_user,'voice_studio','CREATE')")).scalar()
ws=json.loads(Path(os.environ['DATA_DIR']+'/identity.json').read_text())
key=json.loads(Path(os.environ['DATA_DIR']+'/key.json').read_text())
from studio.security import digest
with session_scope() as db:
 row=db.get(APIKey,key['key']['id'])
 assert row.secret_hash==digest(key['secret']) and row.requests_per_minute==60
 assert row.expires_at is None and row.last_used_at is None
with session_scope(write=True) as db:
 db.get(APIKey,key['key']['id']).last_used_at=now()
with session_scope(write=True) as db:db.add_all(Job(workspace_id=ws,kind='fixture') for _ in range(8))
barrier=threading.Barrier(8)
def take(_):barrier.wait();return workers.claim_dispatch()[0]
with ThreadPoolExecutor(max_workers=8) as pool:claims=list(pool.map(take,range(8)))
assert all(claims) and len({item[0] for item in claims})==8
assert workers.claim_dispatch()==(None,None)
async def noop(job_id):pass
workers.HANDLERS['fixture']=noop
async def complete():await asyncio.gather(*(workers.execute_job(*item) for item in claims))
asyncio.run(complete())
with session_scope() as db:assert all(db.get(Job,item[0]).state=='completed' for item in claims)
with session_scope(write=True) as db:
 kb=KnowledgeBase(workspace_id=ws,name='Shared');db.add(kb);db.flush()
 db.add_all(Job(workspace_id=ws,kind='fixture',payload={'kb_id':kb.id}) for _ in range(8))
barrier=threading.Barrier(8)
with ThreadPoolExecutor(max_workers=8) as pool:shared=list(pool.map(take,range(8)))
shared=[item for item in shared if item];assert len(shared)==1
old=shared[0]
with session_scope(write=True) as db:db.get(Job,old[0]).lease_until=now()-timedelta(seconds=1)
replacement=workers.claim_dispatch()[0];assert replacement[0]==old[0] and replacement[1]!=old[1]
token=claim.set(old)
try:
 try:
  with session_scope(write=True) as db:get_job(db,old[0]).result={'stale':True}
 except LeaseLost:pass
 else:raise AssertionError('Stale lease was allowed to write')
finally:claim.reset(token)
asyncio.run(workers.execute_job(*old))
with session_scope() as db:
 job=db.get(Job,old[0]);assert job.state=='running' and job.result=={} and job.lease_token==replacement[1]
print(json.dumps({'upgrade_from_previous_jobs_table':'passed','upgrade_key_policy_preserves_credentials':'passed','runtime_key_usage_write':'passed','repeat_migration':'passed','restricted_role_no_create':'passed','eight_concurrent_unique_claims':'passed','one_owner_per_knowledge_base':'passed','expired_lease_recovery':'passed','stale_owner_fenced':'passed'}))
''',env)
        print(output)
        artifact=root/'artifacts/workers';artifact.mkdir(parents=True,exist_ok=True);(artifact/'postgres.json').write_text(output+'\n')
    finally:
        subprocess.run(docker+['rm','-f',name],capture_output=True)
