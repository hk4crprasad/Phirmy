"""Disposable local PostgreSQL migration/immutability/deletion acceptance.

Never connects to supplied Supabase or deletes real workspaces. All providers
are disabled. Only the uniquely named temporary container is removed.
"""
import json,os,secrets,subprocess,tempfile,time
from pathlib import Path
name='agent-delete-pg-'+secrets.token_hex(4);root=Path.cwd()
with tempfile.TemporaryDirectory(prefix='agent-delete-pg-') as temporary:
 folder=Path(temporary);password=secrets.token_urlsafe(24);role_password=secrets.token_urlsafe(24)
 envfile=folder/'postgres.env';envfile.write_text('POSTGRES_PASSWORD='+password+'\n');envfile.chmod(0o600)
 docker=['docker','--host=unix:///var/run/docker.sock']
 try:
  result=subprocess.run(docker+['run','--rm','-d','--name',name,'--env-file',str(envfile),'-p','127.0.0.1::5432','postgres:17-alpine'],capture_output=True,text=True)
  if result.returncode:raise RuntimeError('Temporary PostgreSQL could not start')
  for _ in range(30):
   if subprocess.run(docker+['exec',name,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
   time.sleep(.5)
  port=json.loads(subprocess.check_output(docker+['inspect',name]))[0]['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
  env=os.environ|{'APP_ENV':'test','DATABASE_URL':'postgresql://postgres:'+password+'@127.0.0.1:'+port+'/postgres','SUPABASE_DB_PASSWORD':'','DATA_DIR':str(folder/'data'),'APP_SECRET':'isolated-agent-delete-'+'x'*48,'OBJECT_STORAGE_PROVIDER':'local','AZURE_STORAGE_CONNECTION_STRING':'','AZURE_STORAGE_ACCOUNT_URL':'','REDIS_URL':'','VECTOR_ENDPOINT':'','VECTOR_API_KEY':'','EMBEDDING_API_KEY':'','OPENAI_API_KEY':'','FISH_API_KEY':'','DEEPGRAM_API_KEY':'','SMTP_HOST':'','REQUIRE_EMAIL_VERIFICATION':'false','SESSION_SECURE':'false','DEV_SEED_ENABLED':'true','LIVE_PAYMENTS_ENABLED':'false','LIVE_CALLS_ENABLED':'false','PHONE_TRIALS_ENABLED':'false','QA_RUNTIME_PASSWORD':role_password,'PYTHONPATH':str(root/'services/control')}
  def run(code,environment):
   result=subprocess.run([str(root/'.venv/bin/python'),'-c',code],env=environment,capture_output=True,text=True)
   if result.returncode:
    import re
    print('Database error:',re.findall(r'psycopg.errors.([A-Za-z]+): ([^\n]+)',result.stderr)[-2:]);print('Failure locations:',re.findall(r'File "([^\"]+)", line (\d+)',result.stderr)[-3:]);raise RuntimeError('Isolated PostgreSQL check failed; driver details withheld')
   return result.stdout.strip()
  setup='''
import os,json
from psycopg import sql
from sqlalchemy import text
from fastapi.testclient import TestClient
from studio.main import initialize_database,create_app
from studio.db import engine
from scripts.qa_accounts import bootstrap_account
initialize_database();initialize_database()
with TestClient(create_app(start_worker=False)) as client:
 response=bootstrap_account(client, '/v1/auth/signup',json={'name':'Deletion QA','email':'delete@example.test','password':'Long-Isolated-Password','workspace_name':'Deletion QA'});assert response.status_code==200
 ws=response.json()['workspaces'][0]['id'];client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
 fixture=client.post('/v1/workspaces/'+ws+'/fixtures',json={});assert fixture.status_code==201
 agent=client.get('/v1/workspaces/'+ws+'/agents/'+fixture.json()['agent_id']).json()
 from pathlib import Path
 Path(os.environ['DATA_DIR']+'/identity.json').write_text(json.dumps({'ws':ws,'agent':agent['id'],'name':agent['name'],'user':response.json()['user']['id']}))
with engine.begin() as db:
 db.exec_driver_sql(sql.SQL('CREATE ROLE deletion_runtime LOGIN PASSWORD {}').format(sql.Literal(os.environ['QA_RUNTIME_PASSWORD'])).as_string())
 db.execute(text('GRANT USAGE ON SCHEMA voice_studio TO deletion_runtime'))
 db.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA voice_studio TO deletion_runtime'))
 db.execute(text('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA voice_studio TO deletion_runtime'))
 db.execute(text('REVOKE CREATE ON SCHEMA voice_studio FROM deletion_runtime'))
'''
  run(setup,env)
  env['DATABASE_URL']='postgresql://deletion_runtime:'+role_password+'@127.0.0.1:'+port+'/postgres'
  runtime='''
import asyncio,json,os
from pathlib import Path
from sqlalchemy import text,delete
from sqlalchemy.exc import DBAPIError
from studio.db import session_scope,engine
from studio.models import AgentVersion,Agent,Job
from studio.main import verify_database_schema
from studio.security import Principal
from studio.agent_deletion import start,DeleteAgent
from studio.workers import execute_job
identity=json.loads(Path(os.environ['DATA_DIR']+'/identity.json').read_text());verify_database_schema()
with engine.connect() as db:assert not db.execute(text("SELECT has_schema_privilege(current_user,'voice_studio','CREATE')")).scalar()
try:
 with session_scope(write=True) as db:db.execute(delete(AgentVersion).where(AgentVersion.agent_id==identity['agent']))
except DBAPIError:pass
else:raise AssertionError('Published version delete guard missing')
with session_scope(write=True) as db:job=start(identity['ws'],identity['agent'],DeleteAgent(confirmation=identity['name']),actor=Principal(identity['user'],identity['ws'],'owner'),db=db)
asyncio.run(execute_job(job['id']))
with session_scope() as db:
 result=db.get(Job,job['id']);assert result.state=='completed',result.error
 assert db.get(Agent,identity['agent']) is None
print(json.dumps({'migration':'passed','restricted_role_no_create':'passed','ordinary_version_delete_blocked':'passed','confirmed_deletion':'passed'}))
'''
  output=run(runtime,env);print(output)
  artifact=root/'artifacts/agent-deletion';artifact.mkdir(parents=True,exist_ok=True);(artifact/'postgres-results.json').write_text(output+'\n')
 finally:subprocess.run(docker+['rm','-f',name],capture_output=True)
