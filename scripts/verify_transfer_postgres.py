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
    root=Path.cwd();name='transfer-pg-'+secrets.token_hex(4);docker=['docker','--host=unix:///var/run/docker.sock']
    with tempfile.TemporaryDirectory(prefix='transfer-pg-') as temporary:
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
                'SUPABASE_DB_PASSWORD':'','DATA_DIR':str(folder/'data'),'APP_SECRET':'isolated-transfer-test-'+'x'*48,
                'OBJECT_STORAGE_PROVIDER':'local','AZURE_STORAGE_CONNECTION_STRING':'','AZURE_STORAGE_ACCOUNT_URL':'',
                'REDIS_URL':'','VECTOR_ENDPOINT':'','OPENAI_API_KEY':'','FISH_API_KEY':'','DEEPGRAM_API_KEY':'','EMBEDDING_API_KEY':'','SMTP_HOST':'','REQUIRE_EMAIL_VERIFICATION':'false',
                'CIPHER_KEY_PROVIDER':'local','CIPHER_KEYS_JSON':'','CIPHER_ACTIVE_KEY_ID':'app-v1',
                'BILLING_DEVELOPMENT_ALLOWANCES_ENABLED':'false','PAID_ACTIVATION_ENABLED':'false',
                'PYTHONPATH':str(root/'services/control')}
            code='''
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import asyncio
import json
from xml.etree.ElementTree import fromstring
from sqlalchemy import select,func
from studio.main import initialize_database,verify_database_schema
from studio.config import settings
from studio.db import session_scope,uid,now
from studio.models import User,Workspace,Membership,Wallet,Call,TransferPolicy,CallTransfer,CallCostRecord
from studio.domain import default_agent,settle_call
from studio import admission,carrier_config,transfers,transfer_routes,tool_safety,media_lifecycle
from studio.secrets import encrypt
initialize_database();verify_database_schema()
settings.live_transfer_enabled=True;settings.live_calls_enabled=True;settings.paid_activation_enabled=True
settings.media_public_origin='https://media.example.test'
carrier_config.credentials=lambda *args:{'auth_id':'synthetic','auth_token':'synthetic'}
with session_scope(write=True) as db:
    user=User(email='transfer@example.test',name='Synthetic',password_hash='not-a-login');db.add(user);db.flush()
    workspace=Workspace(name='Transfer concurrency',free_allowance_user_id=user.id);db.add(workspace);db.flush();ws=workspace.id
    db.add(Membership(workspace_id=ws,user_id=user.id,role='owner'));db.add(Wallet(workspace_id=ws,balance_minor=100000))
    db.add(TransferPolicy(workspace_id=ws,revision=uid(),label='Synthetic staff',encrypted_destination=encrypt('+12025550124'),
                         enabled=True,maximum_seconds=60,approved_at=now(),approved_by=user.id))
    call=Call(workspace_id=ws,state='connected',mode='live',transport='pstn',provider_call_id='synthetic-parent',connected_at=now(),
              metadata_data={'provider':'plivo','carrier_deadline_at':(now()+timedelta(seconds=180)).timestamp()})
    db.add(call);db.flush();call_id=call.id
    config=default_agent();config['behavior']['max_connected_seconds']=180
    admission.admit_voice(db,call,config)
context={'workspace_id':ws,'call_id':call_id,'operation_id':uid(),'user_text':'Please connect me to a human','last_assistant_text':''}
proposal=tool_safety.propose({},'request_human_transfer',{'reason':'Synthetic support'},context)
text=tool_safety.confirmation_text(proposal);tool_safety.mark_presented(context,proposal['id'],text)
response=asyncio.run(tool_safety.execute_confirmation({},{**context,'user_text':'Confirm request','last_assistant_text':text},proposal['id']))
identity=response['result']['transfer_id']
with ThreadPoolExecutor(12) as pool:claims=list(pool.map(transfers.begin,[identity]*24))
assert sum(value is not None for value in claims)==1
with session_scope(write=True) as db:db.get(CallTransfer,identity).state='accepted'
with ThreadPoolExecutor(12) as pool:xml=list(pool.map(transfer_routes.instructions,[identity]*24))
assert sum(fromstring(body).find('Dial') is not None for body in xml)==1
media_lifecycle.settle(ws,call_id,None,False,'unused')
with session_scope() as db:assert db.get(Call,call_id).ended_at is None
transfer_routes.status(identity,{'DialAction':'hangup','DialBLegBillDuration':'11','DialBLegUUID':'synthetic-child'})
with session_scope(write=True) as db:settle_call(db,db.get(Call,call_id),20000,'completed')
with session_scope() as db:
    costs=list(db.scalars(select(CallCostRecord).where(CallCostRecord.call_id==call_id,CallCostRecord.provider=='plivo')))
    assert sorted(row.units['carrier_ms'] for row in costs)==[11000,20000]
print(json.dumps({'database':'disposable PostgreSQL','claims':24,'authorized_submissions':1,
                  'instruction_fetches':24,'authorized_staff_dials':1,'separate_parent_child_costs':'passed'}))
'''
            result=subprocess.run([str(root/'.venv/bin/python'),'-c',code],env=env,capture_output=True,text=True)
            if result.returncode:
                print('Failure locations:',re.findall(r'File "([^\"]+)", line (\d+)',result.stderr)[-4:])
                print('Error types:',re.findall(r'(?:psycopg.errors.|^)([A-Za-z]+Error):',result.stderr,re.M)[-3:])
                raise RuntimeError('Disposable transfer acceptance failed; credentials withheld')
            print(result.stdout.strip())
        finally:subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
