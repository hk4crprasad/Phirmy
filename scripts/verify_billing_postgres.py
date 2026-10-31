"""Disposable PostgreSQL concurrent admission and immutable accounting acceptance."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time


def main():
    root=Path.cwd();name='billing-pg-'+secrets.token_hex(4);docker=['docker','--host=unix:///var/run/docker.sock']
    with tempfile.TemporaryDirectory(prefix='billing-pg-') as temporary:
        folder=Path(temporary);password=secrets.token_urlsafe(24)
        envfile=folder/'postgres.env';envfile.write_text('POSTGRES_PASSWORD='+password+'\n');envfile.chmod(0o600)
        try:
            result=subprocess.run(docker+['run','--rm','-d','--name',name,'--env-file',str(envfile),'-p','127.0.0.1::5432','postgres:17-alpine'],capture_output=True)
            assert result.returncode==0,'Disposable PostgreSQL did not start'
            for _ in range(60):
                if subprocess.run(docker+['exec',name,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
                time.sleep(.25)
            port=json.loads(subprocess.check_output(docker+['inspect',name]))[0]['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
            env=os.environ|{'APP_ENV':'test','DATABASE_URL':'postgresql://postgres:'+password+'@127.0.0.1:'+port+'/postgres',
                'SUPABASE_DB_PASSWORD':'','DATA_DIR':str(folder/'data'),'APP_SECRET':'isolated-billing-test-'+'x'*48,
                'OBJECT_STORAGE_PROVIDER':'local','AZURE_STORAGE_CONNECTION_STRING':'','AZURE_STORAGE_ACCOUNT_URL':'',
                'REDIS_URL':'','VECTOR_ENDPOINT':'','OPENAI_API_KEY':'','SMTP_HOST':'','REQUIRE_EMAIL_VERIFICATION':'false',
                'CIPHER_KEY_PROVIDER':'local','CIPHER_KEYS_JSON':'','CIPHER_ACTIVE_KEY_ID':'app-v1',
                'BILLING_DEVELOPMENT_ALLOWANCES_ENABLED':'false','PAID_ACTIVATION_ENABLED':'false',
                'PYTHONPATH':str(root/'services/control')}
            code='''
from concurrent.futures import ThreadPoolExecutor
import json
from fastapi import HTTPException
from sqlalchemy import select,func,update,delete,text
from sqlalchemy.exc import DBAPIError
from studio.main import initialize_database,verify_database_schema
from studio.db import engine,session_scope
from studio.models import User,Membership,Workspace,WorkspaceSubscription,BudgetAdmission,MeterEvent,CallCostRecord,TariffSnapshot
from studio.config import settings
from pathlib import Path
from studio import admission,metering,plans
initialize_database();initialize_database();verify_database_schema()
with engine.begin() as db:db.execute(text('ALTER TABLE voice_studio.call_cost_records DROP COLUMN model'))
try:verify_database_schema()
except RuntimeError:pass
else:raise AssertionError('Missing provider-model migration was accepted')
initialize_database();verify_database_schema()
with session_scope(write=True) as db:
 user=User(name='Billing QA owner',email='billing-pg@example.test',password_hash='synthetic-unused');db.add(user);db.flush()
 user_id=user.id
 ws=Workspace(name='Isolated billing concurrency',free_allowance_user_id=user.id);db.add(ws);db.flush();identity=ws.id
 db.add(Membership(workspace_id=identity,user_id=user_id,role='owner'))
 current=plans.subscription(db,identity);current.spend_cap_minor=100
with engine.begin() as db:db.execute(text('ALTER TABLE voice_studio.workspaces DROP COLUMN free_allowance_user_id'))
try:verify_database_schema()
except RuntimeError:pass
else:raise AssertionError('Missing shared-Free migration was accepted')
initialize_database();verify_database_schema()
with session_scope() as db:assert db.get(Workspace,identity).free_allowance_user_id==user_id
try:
 with engine.begin() as db:db.execute(update(Workspace).where(Workspace.id==identity).values(free_allowance_user_id=None))
except DBAPIError:pass
else:raise AssertionError('Free sponsor reset was accepted')

def hold(index):
 try:
  with session_scope(write=True) as db:admission.reserve(db,identity,'parallel:'+str(index),cost=10*metering.MICRO)
  return 'held'
 except HTTPException as error:
  assert error.status_code==429
  return 'denied'
with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(hold,range(24)))
assert results.count('held')==10 and results.count('denied')==14
with session_scope(write=True) as db:
 current=db.scalar(select(WorkspaceSubscription));current.spend_cap_minor=10000
 metering.record_usage(db,identity,'immutable-turn','chat_turns',1)
 tariff=metering.snapshot(db,identity,'immutable-tariff')
 cost=metering.record_cost(db,identity,'immutable-cost','openai','llm',{'input_tokens':1})
for model in [MeterEvent,TariffSnapshot,CallCostRecord]:
 try:
  with engine.begin() as db:db.execute(delete(model))
 except DBAPIError:pass
 else:raise AssertionError('Financial history deletion was accepted')
with session_scope() as db:
 assert db.scalar(select(func.count()).select_from(BudgetAdmission).where(BudgetAdmission.state=='held'))==10
 assert metering.usage_summary(db,identity)['held_cost_micro_minor']==100*metering.MICRO
body=plans.catalog();body.pop('content_hash');body['plans']['free']['included']['chat_turns']=10
path=Path(settings.data_dir)/'shared-free.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(body));settings.plans_config_path=str(path)
workspaces=[]
with session_scope(write=True) as db:
 for index in range(3):
  ws=Workspace(name='Shared pool '+str(index),free_allowance_user_id=user_id);db.add(ws);db.flush();workspaces.append(ws.id)
def free_hold(index):
 try:
  with session_scope(write=True) as db:admission.reserve(db,workspaces[index%3],'shared:'+str(index),resources={'chat_turns':1})
  return 'held'
 except HTTPException as error:
  assert error.status_code==429
  return 'denied'
with ThreadPoolExecutor(max_workers=8) as pool:shared_results=list(pool.map(free_hold,range(24)))
# The earlier immutable-turn consumed one of the same owner's ten Free turns.
assert shared_results.count('held')==9 and shared_results.count('denied')==15
print(json.dumps({'concurrent_requests':24,'admitted':10,'rejected':14,'immutable_accounting':'passed','schema':'passed',
 'shared_free_workspaces':3,'shared_free_requests':24,'shared_free_admitted':9,'shared_free_rejected':15,'prior_free_turns':1,
 'owner_backfill':'passed','owner_reset_rejected':True}))
'''
            result=subprocess.run([str(root/'.venv/bin/python'),'-c',code],env=env,capture_output=True,text=True)
            if result.returncode:
                print('Failure locations:',re.findall(r'File "([^\"]+)", line (\d+)',result.stderr)[-4:])
                print('Error types:',re.findall(r'(?:psycopg.errors.|^)([A-Za-z]+Error):',result.stderr,re.M)[-3:])
                raise RuntimeError('Disposable billing acceptance failed; credentials withheld')
            print(result.stdout.strip())
        finally:subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
