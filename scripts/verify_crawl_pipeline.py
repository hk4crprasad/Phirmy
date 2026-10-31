"""Synthetic website through real Azure/Qdrant/Redis/LLM; isolated temporary DB.

Uses tiny paid embedding/model requests. No customer DB, phone or email action.
The website boundary is a deterministic fixture, not a live-site crawl claim.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4
from qa_accounts import bootstrap_account
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))
logging.disable(logging.CRITICAL)


async def main(folder):
    os.environ.update(APP_ENV='development', DATABASE_URL='sqlite:///'+folder+'/qa.db', SUPABASE_DB_PASSWORD='',
                      DATA_DIR=folder+'/data', APP_SECRET='synthetic-crawl-pipeline-'+uuid4().hex,
                      REQUIRE_EMAIL_VERIFICATION='false', SESSION_SECURE='false', SMTP_HOST='',
                      LIVE_CALLS_ENABLED='false', PHONE_TRIALS_ENABLED='false', PHONE_NUMBER_PURCHASES_ENABLED='false', LIVE_PAYMENTS_ENABLED='false')
    import httpx
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from studio import knowledge, website_routes
    from studio.main import create_app
    from studio.workers import execute_job
    from studio.db import session_scope
    from studio.models import Source
    from studio.storage import get_store
    from studio.retrieval import Qdrant
    site='https://synthetic-crawl.example/'
    async def validate(url):
        if not url.startswith(site): raise ValueError('Only the exact synthetic site is permitted')
    async def fetch(url, *args, **kwargs):
        await validate(url)
        if url.endswith('robots.txt'): return url,b'User-agent: *\nAllow: /','text/plain'
        if url.endswith('sitemap.xml'): return url,b'<urlset/>','application/xml'
        return url,b'<html><title>Synthetic Workshop</title><main><h1>Workshop delivery</h1><p>Our synthetic workshop ships its products within four business days. Shipping is free on every test order. Returns are accepted within fourteen days for unopened items. For this synthetic business our team answers product questions and explains the shipping policy. Contact workshop@example.test for assistance.</p></main></html>','text/html'
    knowledge.validate_public_url=website_routes.validate_public_url=validate
    knowledge.safe_fetch=fetch
    ws=None
    try:
        with TestClient(create_app(start_worker=False)) as client:
            signup=bootstrap_account(client, '/v1/auth/signup',json={'name':'Pipeline QA','email':'pipeline@example.test','password':'Synthetic-Pipeline-Password','workspace_name':'Synthetic pipeline'})
            assert signup.status_code==200
            ws=signup.json()['workspaces'][0]['id'];base='/v1/workspaces/'+ws
            client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
            created=client.post(base+'/website-assistants',json={'website_url':site,'name':'Synthetic workshop','render_js':False,'refresh_hours':0})
            assert created.status_code==202
            row=created.json();await execute_job(row['job']['id'])
            row=client.get(base+'/website-assistants').json()['items'][0]
            assert row['job']['state']=='completed', 'Crawl/index failed'
            snapshot=row['knowledge']['active_snapshot_id']
            query=await knowledge.retrieve(ws,[snapshot],'How long does shipping take?')
            assert query['retrieval_mode']=='qdrant-hybrid' and query['answerable']
            inst=row['installation']
            public=client.post('/v1/public/sessions',headers={'Origin':site.rstrip('/')},json={'installation_public_id':inst['public_id'],'public_key':inst['theme']['publishable_key']})
            assert public.status_code==201
            state=public.json();assert state['mode']=='live-llm'
            answer=client.post('/v1/public/chat',headers={'Origin':site.rstrip('/'),'Authorization':'Bearer '+state['session_token']},json={'session_id':state['id'],'message':'How many business days does shipping take?','client_message_id':'synthetic-first-turn'})
            assert answer.status_code==200
            completed=[json.loads(x.split('data: ',1)[1]) for x in answer.text.split('\n\n') if x.startswith('event: chat.completed')]
            assert completed and ('four' in completed[0]['text'].lower() or '4' in completed[0]['text'])
            job=client.post(base+'/website-assistants/'+row['id']+'/recrawl').json();await execute_job(job['id'])
            latest=client.get(base+'/website-assistants').json()['items'][0]
            assert latest['knowledge']['active_snapshot_id']==snapshot and latest['job']['result']['unchanged']
            result={'state':'passed','website':'synthetic fixture','database':'temporary SQLite', 'azure_storage':'actual','embeddings':'actual configured model',
                    'qdrant':'actual hybrid retrieval','llm':'actual grounded widget answer','unchanged_recrawl':'reused snapshot','pages':row['knowledge']['pages_indexed']}
    finally:
        if ws:
            qdrant=Qdrant()
            await qdrant.request('POST','/collections/'+qdrant.collection+'/points/delete?wait=true',json={'filter':{'must':[{'key':'workspace_id','match':{'value':ws}}]}})
            with session_scope() as db:
                keys=set(db.scalars(select(Source.raw_object_key).where(Source.workspace_id==ws)))
            for key in keys:
                if key: await asyncio.to_thread(get_store().delete,ws,key)
    result['cleanup']='test blobs and points removed'
    Path('artifacts/crawl-pipeline-results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':
    try:
        with tempfile.TemporaryDirectory(prefix='studio-crawl-pipeline-') as folder: asyncio.run(main(folder))
    except Exception as exc:
        print(json.dumps({'state':'failed','error_type':type(exc).__name__}))
        raise SystemExit(1)
