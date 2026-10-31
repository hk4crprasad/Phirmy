"""Read-only website acceptance through the real app, isolated from customer DBs.

No model/embedding/speech/carrier credentials are used. Retrieval is explicitly
lexical test mode. Robots, DNS-pinned transport and renderer guards stay enabled.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from qa_accounts import bootstrap_account
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('url')
parser.add_argument('--max-pages',type=int,default=20)
parser.add_argument('--output',default='artifacts/website/live-results.json')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/control'))
with tempfile.TemporaryDirectory(prefix='cynerza-live-site-') as folder:
    os.environ.update(APP_ENV='test',DATABASE_URL='sqlite:///'+folder+'/qa.db',SUPABASE_DB_PASSWORD='',DATA_DIR=folder+'/data',APP_SECRET='isolated-live-website-test-'+'x'*40,
        OBJECT_STORAGE_PROVIDER='local',AZURE_STORAGE_CONNECTION_STRING='',AZURE_STORAGE_ACCOUNT_URL='',OPENAI_API_KEY='',EMBEDDING_API_KEY='',VECTOR_ENDPOINT='',VECTOR_API_KEY='',
        SMTP_HOST='',GOOGLE_CLIENT_ID='',GOOGLE_CLIENT_SECRET='',REQUIRE_EMAIL_VERIFICATION='false',SESSION_SECURE='false',FISH_API_KEY='',DEEPGRAM_API_KEY='',
        TWILIO_ACCOUNT_SID='',TWILIO_AUTH_TOKEN='',TWILIO_API_KEY='',TWILIO_API_SECRET='',PLIVO_AUTH_ID='',PLIVO_AUTH_TOKEN='',LIVE_CALLS_ENABLED='false',PHONE_TRIALS_ENABLED='false',PHONE_NUMBER_PURCHASES_ENABLED='false',LIVE_PAYMENTS_ENABLED='false')
    from fastapi.testclient import TestClient
    from studio.main import create_app
    from studio.workers import execute_job
    from studio.db import session_scope,now
    from studio.knowledge import retrieve
    result={'website':args.url,'tested_at':now().isoformat(),'database':'temporary isolated SQLite','transport':'actual DNS-pinned public crawler, no network mocks','retrieval':'lexical-test; real embeddings/model not exercised','customer_data_changed':False}
    with TestClient(create_app(start_worker=False)) as client:
        response=bootstrap_account(client, '/v1/auth/signup',json={'name':'Live website acceptance','email':'live-site-qa@example.test','password':'Synthetic-Live-Website-Password','workspace_name':'Temporary website acceptance'})
        assert response.status_code==200
        ws=response.json()['workspaces'][0]['id'];base='/v1/workspaces/'+ws
        client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
        response=client.post(base+'/website-assistants',json={'name':'Live website acceptance','website_url':args.url,'max_pages':args.max_pages,'render_js':True,'refresh_hours':0})
        result['creation_http_status']=response.status_code
        if response.status_code!=202:
            result.update(status='blocked_before_crawl',reason=response.json().get('detail'),indexed_pages=0,products=0)
        else:
            row=response.json()
            try:asyncio.run(asyncio.wait_for(execute_job(row['job']['id']),240))
            except asyncio.TimeoutError:result['timeout_seconds']=240
            row=client.get(base+'/website-assistants').json()['items'][0]
            result.update(status=row['job']['state'],indexed_pages=row['knowledge']['pages_indexed'],chunks=row['knowledge']['chunks_indexed'],crawl=row['job']['result'],error=row['job']['error'])
            result['pages']=client.get(base+'/website-assistants/'+row['id']+'/pages').json()['items']
            result['products']=[{key:p[key] for key in ['title','canonical_url','description','price_minor','currency','availability','image_url']} for p in client.get(base+'/products').json()['items']]
            if row['knowledge']['active_snapshot_id']:
                result['retrieval_probes']={query:asyncio.run(retrieve(ws,[row['knowledge']['active_snapshot_id']],query)) for query in ['What products are available?','What are the shipping and return policies?']}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'pages','retrieval_probes','products'}},indent=2))
    print('Evidence:',str(output))
