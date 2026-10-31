"""Isolated PostgreSQL17 upgrade, restricted runtime, number/booking/OAuth races.

Creates a temporary local container with generated credentials, mocks all
carrier operations and removes only that container/volume on exit. Does not
read or migrate the supplied Supabase database. Requires local Docker.
"""
import json,os,secrets,subprocess,tempfile,time
from pathlib import Path
container='cynerza-phone-pg-'+secrets.token_hex(3)
root=Path.cwd()
with tempfile.TemporaryDirectory(prefix='cynerza-phone-pg-') as folder:
 d=Path(folder);password=secrets.token_urlsafe(24);runtime_password=secrets.token_urlsafe(24)
 envfile=d/'pg.env';envfile.write_text('POSTGRES_PASSWORD='+password+'\n');envfile.chmod(0o600)
 def run(code,env,label):
  result=subprocess.run([str(root/'.venv/bin/python'),'-c',code],env=env,capture_output=True,text=True)
  if result.returncode:
   print('Safe QA progress:',result.stdout)
   import re
   print('Failure classes:',re.findall(r'^[ |+ -]*([A-Za-z_]\w*(?:Error|Exception))(?=:|$)',result.stderr,re.M)[-4:])
   print('Failure locations:',re.findall(r'File \"([^\"]+)\", line (\d+)',result.stderr)[-4:])
   raise RuntimeError(label+' failed; private driver output withheld')
  return result.stdout.strip()
 try:
  started=subprocess.run(['docker','run','--rm','-d','--name',container,'--env-file',str(envfile),'-p','127.0.0.1::5432','postgres:17-alpine'],capture_output=True,text=True)
  if started.returncode:raise RuntimeError('Isolated PostgreSQL could not start')
  for _ in range(30):
   if subprocess.run(['docker','exec',container,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
   time.sleep(.5)
  else:raise RuntimeError('Isolated PostgreSQL not ready')
  port=subprocess.check_output(['docker','port',container,'5432/tcp'],text=True).strip().rsplit(':',1)[1]
  base='@127.0.0.1:'+port+'/postgres'
  env=os.environ|{'APP_ENV':'development','DATABASE_URL':'postgresql://postgres:'+password+base,'SUPABASE_DB_PASSWORD':'','DATA_DIR':str(d/'data'),'APP_SECRET':'isolated-phone-qa-'+'x'*40,'OBJECT_STORAGE_PROVIDER':'local','AZURE_STORAGE_CONNECTION_STRING':'','AZURE_STORAGE_ACCOUNT_URL':'','VECTOR_ENDPOINT':'','VECTOR_API_KEY':'','EMBEDDING_API_KEY':'','OPENAI_API_KEY':'synthetic-key','FISH_API_KEY':'synthetic-key','FISH_VOICE_ID':'synthetic-voice','DEEPGRAM_API_KEY':'synthetic-key','TWILIO_ACCOUNT_SID':'AC-local-qa','TWILIO_AUTH_TOKEN':'synthetic-token','TWILIO_API_KEY':'','TWILIO_API_SECRET':'','PHONE_NUMBER_PURCHASES_ENABLED':'false','PLIVO_AUTH_ID':'','PLIVO_AUTH_TOKEN':'','SMTP_HOST':'','REQUIRE_EMAIL_VERIFICATION':'false','DEV_SEED_ENABLED':'true','SESSION_SECURE':'false','PHONE_TRIALS_ENABLED':'true','LIVE_CALLS_ENABLED':'true','LIVE_PAYMENTS_ENABLED':'false','MEDIA_PUBLIC_ORIGIN':'https://voice.example.test','QA_RUNTIME_PASSWORD':runtime_password}
  setup='''
import os,sys
from datetime import timedelta
from sqlalchemy import text,inspect
from fastapi.testclient import TestClient
from psycopg import sql
from scripts.qa_accounts import bootstrap_account
sys.path.insert(0,'services/control')
from studio.main import initialize_database,verify_database_schema,create_app
from studio.db import Base,engine,session_scope,now
from studio.models import SchemaMigration,Number
from studio.phone_trials import create_pool,grant_trial
with engine.begin() as db:db.execute(text('CREATE SCHEMA voice_studio'))
old=[t for t in Base.metadata.sorted_tables if t.name not in {'phone_number_orders','phone_number_inventory','scheduling_availability','scheduling_bookings','website_assistants'}]
Base.metadata.create_all(engine,tables=old)
assert len(inspect(engine).get_table_names(schema='voice_studio'))==59
with session_scope(write=True) as db:db.add(SchemaMigration(revision='2026-10-23-phone-trials'))
initialize_database();initialize_database();verify_database_schema()
assert len(inspect(engine).get_table_names(schema='voice_studio'))==64
with TestClient(create_app(start_worker=False)) as client:
 response=bootstrap_account(client, '/v1/auth/signup',json={'name':'PG trial QA','email':'pg-trial@example.test','password':'Long-PG-Trial-Password','workspace_name':'PG Trial'})
 assert response.status_code==200
 ws=response.json()['workspaces'][0]['id'];client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
 fixture=client.post('/v1/workspaces/'+ws+'/fixtures',json={});assert fixture.status_code==201
 with session_scope(write=True) as db:
  pool=create_pool(db,name='PG QA',expires_at=now()+timedelta(days=19),alert_email='owner@example.test')
  pool.balance_state,pool.balance_minor,pool.balance_checked_at='ready',1500,now()
  trial=grant_trial(db,pool.id,ws,'+12025550110',['+12025550111'])
  number=db.get(Number,trial.number_id);number.status,number.can_outbound='active',True
with engine.begin() as db:
 db.exec_driver_sql(sql.SQL('CREATE ROLE cynerza_phone_qa LOGIN PASSWORD {}').format(sql.Literal(os.environ['QA_RUNTIME_PASSWORD'])).as_string())
 db.execute(text('GRANT USAGE ON SCHEMA voice_studio TO cynerza_phone_qa'))
 db.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA voice_studio TO cynerza_phone_qa'))
 db.execute(text('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA voice_studio TO cynerza_phone_qa'))
 db.execute(text('REVOKE CREATE ON SCHEMA voice_studio FROM cynerza_phone_qa'))
'''
  run(setup,env,'PostgreSQL setup/upgrade')
  env.update({'DATABASE_URL':'postgresql://cynerza_phone_qa:'+runtime_password+base,'APP_ENV':'production','DEV_SEED_ENABLED':'false','OBJECT_STORAGE_PROVIDER':'azure','SESSION_SECURE':'true','APP_ORIGIN':'https://testserver'})
  runtime='''
import sys,json
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select,text
from fastapi.testclient import TestClient
sys.path.insert(0,'services/control')
from studio.main import create_app
from studio.db import engine,session_scope
from studio.models import PhoneTrial,Agent
with engine.connect() as db:assert not db.execute(text("SELECT has_schema_privilege(current_user,'voice_studio','CREATE')")).scalar()
with TestClient(create_app(start_worker=False),base_url='https://testserver',headers={'Origin':'https://testserver'}) as client:
 response=client.post('/v1/auth/signin',json={'email':'pg-trial@example.test','password':'Long-PG-Trial-Password'})
 print('Signin status:',response.status_code)
 assert response.status_code==200
 me=client.get('/v1/auth/me');assert me.status_code==200
 ws=me.json()['workspaces'][0]['id'];client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
 with session_scope() as db:
  trial=db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id==ws));number=trial.number_id
  agent=db.scalar(select(Agent).where(Agent.workspace_id==ws));agent_id=agent.id
 body={'agent_id':agent_id,'mode':'live','number_id':number,'destination':'+12025550111','budget_minor':1}
 def dispatch(key):return client.post('/v1/workspaces/'+ws+'/calls/outbound',json=body,headers={'Idempotency-Key':key}).status_code
 with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(dispatch,['pg-a','pg-b']))
 print('Parallel results:',sorted(results))
 assert sorted(results)==[202,429],results
 with session_scope() as db:assert db.scalar(select(PhoneTrial).where(PhoneTrial.workspace_id==ws)).calls_used==1

 from types import SimpleNamespace
 from unittest.mock import MagicMock,patch
 from studio.config import settings
 from studio.models import PhoneNumberOrder,PhoneTrialPool,User,Workspace
 from studio.number_provisioning import allocate
 with session_scope(write=True) as db:
  pool=db.scalar(select(PhoneTrialPool));pool.balance_checked_at=__import__('studio.db',fromlist=['now']).now()
  pool.balance_minor=1500
  order_ids=[]
  for index in range(2):
   user=User(name='PG allocation QA',email='pg-allocation-'+str(index)+'@example.test',password_hash='unused synthetic hash')
   workspace=Workspace(name='PG allocation QA '+str(index));db.add_all([user,workspace]);db.flush()
   order=PhoneNumberOrder(workspace_id=workspace.id,user_id=user.id,pool_id=pool.id);db.add(order);db.flush();order_ids.append(order.id)
 settings.phone_number_purchases_enabled=True;settings.phone_number_total_budget_minor=150
 sdk=MagicMock()
 sdk.pricing.v1.phone_numbers.countries.return_value.fetch.return_value=SimpleNamespace(price_unit='USD',phone_number_prices=[{'number_type':'local','current_price':'1.15'}])
 resource=SimpleNamespace(phone_number='+12025550120',sid='PN-synthetic-allocation',account_sid='AC-local-qa',capabilities={'voice':True},address_requirements='none')
 sdk.available_phone_numbers.return_value.local.list.return_value=[resource]
 sdk.incoming_phone_numbers.create.return_value=resource
 with patch('studio.carrier_config.twilio_client',return_value=sdk):
  with ThreadPoolExecutor(max_workers=2) as executor:list(executor.map(allocate,order_ids))
 assert sdk.incoming_phone_numbers.create.call_count==1
 with session_scope() as db:
  states=sorted(db.get(PhoneNumberOrder,oid).state for oid in order_ids)
  assert states==['assigned','unavailable'],states
 print('Parallel allocation: one simulated purchase, global budget enforced')
 import asyncio
 from datetime import timedelta
 from studio import scheduling,scheduling_providers
 from studio.db import now
 from studio.models import Connection,ConnectorCredential,Call,SchedulingBooking
 from studio.secrets import encrypt
 begin=(now()+timedelta(days=2)).replace(second=0,microsecond=0);end=begin+timedelta(minutes=30)
 with session_scope(write=True) as db:
  db.add(Connection(workspace_id=ws,provider='calcom',name='Cal.com QA',state='connected'))
  db.add(ConnectorCredential(workspace_id=ws,provider='calcom',encrypted_data=encrypt(json.dumps({'api_key':'synthetic-scheduler-token','event_type_id':'123'}))))
  call=Call(workspace_id=ws,mode='simulation',transport='browser',state='connected');db.add(call);db.flush();booking_call=call.id
 from studio import scheduling_oauth
 from studio.secrets import decrypt
 settings.calcom_client_id='synthetic-pg-client';settings.calcom_client_secret='synthetic-pg-secret';settings.calcom_oauth_mode='confidential'
 with session_scope(write=True) as db:
  secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==ws,ConnectorCredential.provider=='calcom'))
  token=json.loads(decrypt(secret.encrypted_data))
  token.update(refresh_token='synthetic-pg-refresh',_oauth={'binding_id':'pg-binding','subject':'pg-account','client_id':settings.calcom_client_id,'public':False,'expires_at':(now()-timedelta(seconds=1)).isoformat(),'status':'ready'})
  secret.encrypted_data=encrypt(json.dumps(token))
 refreshes=[]
 async def refresh_token(provider,form):
  refreshes.append(provider);await asyncio.sleep(.1)
  return {'access_token':'synthetic-pg-fresh','refresh_token':'synthetic-pg-rotated','expires_in':1800,'token_type':'bearer','scope':'PROFILE_READ EVENT_TYPE_READ BOOKING_READ'}
 async def refresh_race():
  await asyncio.gather(*(scheduling_oauth.ensure_access(ws,'calcom') for _ in range(2)))
  assert refreshes==['calcom'],refreshes
  with session_scope() as db:
   current,_=scheduling.credentials(db,ws,'calcom')
   assert current['api_key']=='synthetic-pg-fresh' and current['_oauth']['status']=='ready'
 with patch('studio.scheduling_oauth.token_request',refresh_token):asyncio.run(refresh_race())
 print('Parallel OAuth refresh: one simulated token exchange, rotating token preserved')
 posts=[]
 async def scheduler_request(method,url,**kwargs):
  if '/event-types/' in url:return {'status':'success','data':{'id':123,'title':'PG appointment','lengthInMinutes':30,'price':0,'recurrence':None,'bookingFields':[]}}
  if url.endswith('/slots'):return {'status':'success','data':{'date':[{'start':begin.isoformat(),'end':end.isoformat()}]}}
  assert method=='POST' and url.endswith('/bookings')
  body=kwargs['json'];posts.append(body)
  await asyncio.sleep(.05)
  return {'status':'success','data':{'uid':'pg-booking-uid','eventTypeId':123,'start':body['start'],'end':end.isoformat(),'attendees':[{'email':body['attendee']['email']}],'status':'accepted'}}
 async def booking_race():
  ctx={'workspace_id':ws,'call_id':booking_call,'operation_id':'pg-booking-prepare','user_text':'My name is Jane Doe and my email is jane@example.test','user_history':[]}
  offer=await scheduling.agent_action('check_scheduling_availability',{'provider':'calcom','start':begin.isoformat(),'end':end.isoformat(),'timezone':'Asia/Kolkata'},ctx)
  assert 'availability_id' in offer,offer
  prepared=await scheduling.agent_action('prepare_scheduling_booking',{'availability_id':offer['availability_id'],'start':begin.isoformat(),'name':'Jane Doe','email':'jane@example.test'},ctx)
  assert prepared['state']=='prepared',prepared
  ctx={**ctx,'operation_id':'pg-booking-confirm','user_text':'Yes please book it','user_history':[ctx['user_text']],'last_assistant_text':prepared['confirmation_text']}
  values=await asyncio.gather(*(scheduling.agent_action('confirm_scheduling_booking',{'booking_id':prepared['booking_id']},ctx) for _ in range(2)))
  assert len(posts)==1 and any(value.get('booking_confirmed') for value in values),values
  with session_scope() as db:assert db.get(SchedulingBooking,prepared['booking_id']).state=='confirmed'
  return {'simulated_posts':len(posts),'response_states':sorted(value['state'] for value in values),'final_state':'confirmed'}
 with patch('studio.scheduling_providers.request',scheduler_request):booking_check=asyncio.run(booking_race())
 from sqlalchemy import func
 summary_response=client.get('/v1/workspaces/'+ws+'/bootstrap?view=summary')
 assert summary_response.status_code==200 and summary_response.json()['data']=={}
 with session_scope() as db:call_count=db.scalar(select(func.count()).select_from(Call).where(Call.workspace_id==ws))
 assert summary_response.json()['summary']['calls']==call_count
 assert len(summary_response.json()['summary']['daily_calls'])==14
 print('Selective summary: PostgreSQL aggregation and workspace counts passed')
 print(json.dumps({'schema_upgrade':'59 to 64 tables, repeatable','production_startup':'passed with restricted role, no schema CREATE','parallel_admission':sorted(results),'reserved_calls':1,'provider_calls':0,'parallel_allocation':{'orders':2,'simulated_purchases':1,'states':states},'selective_summary':'PostgreSQL aggregate counts passed','parallel_oauth_refresh':{'requests':2,'simulated_token_exchanges':len(refreshes)},'parallel_booking':booking_check,'transport':'isolated loopback PostgreSQL17, not external TLS'}))
'''
  stdout=run(runtime,env,'Restricted PostgreSQL trial check');data=json.loads(stdout.splitlines()[-1]);out=root/'artifacts/automatic-numbers';out.mkdir(parents=True,exist_ok=True);(out/'postgres-results.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data))
 finally:subprocess.run(['docker','rm','-f','-v',container],capture_output=True)
print('Isolated PostgreSQL container/volume removed; no remote DB changes or provider calls.')
