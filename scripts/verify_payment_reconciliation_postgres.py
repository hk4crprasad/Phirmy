"""Disposable PostgreSQL payment fencing, duplicate capture and invoice sequence acceptance."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time


def main():
    root=Path.cwd();name='payments-pg-'+secrets.token_hex(4);docker=['docker','--host=unix:///var/run/docker.sock']
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
import hashlib,hmac,json
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select,func,update
from studio.main import initialize_database,verify_database_schema
from studio.db import engine,session_scope,uid
from studio.config import settings
from studio.models import Workspace,Wallet,PaymentOrder,BillingWebhookInbox,Ledger,Invoice,BillingFinancialEvent
from studio import billing_inbox,billing_events,gst,invoices
initialize_database();verify_database_schema()
settings.razorpay_webhook_secret='synthetic_pg_webhook_secret'

def workspace(label):
 with session_scope(write=True) as db:
  ws=Workspace(name=label);db.add(ws);db.flush();identity=ws.id
  db.add(Wallet(workspace_id=identity,balance_minor=0));db.add(PaymentOrder(workspace_id=identity,amount_minor=10000,provider_order_id='order_'+label,operation_key='order'))
 return identity

def receipt(label,event_id):
 payment={'id':'pay_'+label,'order_id':'order_'+label,'status':'captured','amount':10000,'currency':'INR'}
 event={'event':'payment.captured','payload':{'payment':{'entity':payment}}}
 body=json.dumps(event).encode();signature=hmac.new(b'synthetic_pg_webhook_secret',body,hashlib.sha256).hexdigest()
 billing_inbox.accept(body,event_id,signature)
 return event,payment

identity=workspace('fenced');event,payment=receipt('fenced','event_fenced')
claimed=billing_inbox.claim();receipt_id,old_lease,attempt,event_id,_=claimed;replacement=uid()
original_capture=billing_events.capture

def take_over(*args,**kwargs):
 result=original_capture(*args,**kwargs)
 with engine.begin() as connection:
  connection.execute(update(BillingWebhookInbox).where(BillingWebhookInbox.id==receipt_id).values(lease_token=replacement))
 return result
billing_events.capture=take_over
try:billing_inbox.apply(receipt_id,old_lease,event_id,event,payment)
except RuntimeError:pass
else:raise AssertionError('Expired billing worker committed a capture')
finally:billing_events.capture=original_capture
with session_scope() as db:
 assert db.scalar(select(Wallet.balance_minor).where(Wallet.workspace_id==identity))==0
 assert db.scalar(select(func.count()).select_from(Invoice))==0
 assert db.scalar(select(func.count()).select_from(BillingFinancialEvent))==0
assert billing_inbox.apply(receipt_id,replacement,event_id,event,payment)
with session_scope() as db:assert db.scalar(select(Wallet.balance_minor).where(Wallet.workspace_id==identity))==10000

parallel=workspace('parallel');events=[]
for index in range(4):
 event,payment=receipt('parallel','event_parallel_'+str(index));claim=billing_inbox.claim()
 events.append((claim[0],claim[1],claim[3],event,payment))
with ThreadPoolExecutor(max_workers=4) as pool:assert all(pool.map(lambda args:billing_inbox.apply(*args),events))
with session_scope() as db:
 assert db.scalar(select(Wallet.balance_minor).where(Wallet.workspace_id==parallel))==10000
 assert db.scalar(select(func.count()).select_from(Ledger).where(Ledger.workspace_id==parallel))==1
 assert db.scalar(select(func.count()).select_from(Invoice).where(Invoice.workspace_id==parallel))==1

seller={**gst.business(),'entity_id':'synthetic_counter_entity'}
quote={'seller':seller,'buyer':{'legal_name':'Synthetic counter buyer','address':'Synthetic address','email':'','state_code':'07','gstin':''},
 'tax':gst.tax_lines(10000,'07',seller),'price_status':'DRAFT','payment_mode':'test','authorized_paid':False,'description':'Synthetic concurrency invoice'}

def numbered(index):
 with session_scope(write=True) as db:
  ws=Workspace(name='Invoice counter '+str(index));db.add(ws);db.flush()
  row=invoices.issue(db,ws.id,'counter-test',quote,'synthetic_'+str(index))
  return row.number
with ThreadPoolExecutor(max_workers=8) as pool:numbers=list(pool.map(numbered,range(12)))
assert len(set(numbers))==12
assert sorted(int(value.rsplit('/',1)[-1]) for value in numbers)==list(range(1,13))
from studio import billing_accounting,metering
from studio.operator_billing import report
from studio.db import now
from datetime import timedelta
with session_scope(write=True) as db:
 billing_accounting.financial_event(db,parallel,'operator-income','subscription_fee',{'revenue_delta_minor':1000,'provider_fee_minor':20})
 metering.record_cost(db,parallel,'operator-cost','openai','llm',{'input_tokens':1000},source='provider_usage')
with session_scope() as db:
 observed=report(db,now()-timedelta(days=1))[parallel]
 assert observed['recognized_receipts_minor']==1000 and observed['reported_payment_fees_minor']==20
 assert observed['provider_cost_micro_minor']==100_000_000
 assert observed['contribution_micro_minor']==880_000_000
 assert observed['unreported_payment_fee_receipts']==1
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from studio.main import create_app
from studio import legal
from studio.models import LegalAcceptance,LegalPolicySnapshot
with TestClient(create_app(start_worker=False)) as client:
 response=client.post('/v1/auth/signup',json={'name':'Legal PG fixture','email':'legal-pg@example.test',
  'password':'Long-Synthetic-PG-Password','workspace_name':'Legal PG fixture',
  'legal_accepted':True,'legal_version':legal.current()['version']})
 assert response.status_code==202
with session_scope() as db:
 assert db.scalar(select(func.count()).select_from(LegalAcceptance))==1
 assert db.scalar(select(func.count()).select_from(LegalPolicySnapshot))==1
for model,values in [(LegalAcceptance,{'source':'forged'}),(LegalPolicySnapshot,{'status':'APPROVED'})]:
 try:
  with engine.begin() as connection:connection.execute(update(model).values(**values))
 except DBAPIError:pass
 else:raise AssertionError('Legal evidence was mutable')
print(json.dumps({'old_worker_fenced':True,'concurrent_capture_receipts':4,'wallet_credits':1,'unique_invoice_numbers':12,'operator_aggregates':'passed','legal_evidence':'immutable','provider':'synthetic'}))
'''
            result=subprocess.run([str(root/'.venv/bin/python'),'-c',code],env=env,capture_output=True,text=True)
            if result.returncode:
                print('Failure locations:',re.findall(r'File "([^\"]+)", line (\d+)',result.stderr)[-4:])
                print('Error types:',re.findall(r'(?:psycopg.errors.|^)([A-Za-z]+Error):',result.stderr,re.M)[-3:])
                raise RuntimeError('Disposable billing acceptance failed; credentials withheld')
            print(result.stdout.strip())
        finally:subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
