"""Controlled full-pipeline and durable-queue throughput; no external providers.

Run against a source revision with --label before/after. Latency is injected at
HTTP, renderer, object storage and embedding boundaries; app/DB/storage are real.
"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from qa_accounts import bootstrap_account
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
logging.disable(logging.CRITICAL)


async def benchmark(folder):
    os.environ.update(APP_ENV='test',DATABASE_URL='sqlite:///'+folder+'/qa.db',SUPABASE_DB_PASSWORD='',DATA_DIR=folder+'/data',
        OBJECT_STORAGE_PROVIDER='local',AZURE_STORAGE_CONNECTION_STRING='',AZURE_STORAGE_ACCOUNT_URL='',REDIS_URL='',
        OPENAI_API_KEY='',EMBEDDING_API_KEY='',VECTOR_ENDPOINT='',VECTOR_API_KEY='',SMTP_HOST='',
        REQUIRE_EMAIL_VERIFICATION='false',SESSION_SECURE='false',APP_SECRET='synthetic-worker-benchmark-'+'x'*32)
    import httpx
    from fastapi.testclient import TestClient
    from studio import knowledge,website_routes,website_crawler,workers
    from studio.config import settings
    from studio.main import create_app
    from studio.db import session_scope
    from studio.models import Job
    from studio.storage import get_store
    root='https://synthetic-pipeline.example'
    active={'fetch':0,'render':0,'upload':0,'embed':0,'job':0};peaks=dict(active);lock=threading.Lock();writes=0
    def enter(stage):
        with lock:active[stage]+=1;peaks[stage]=max(peaks[stage],active[stage])
    def leave(stage):
        with lock:active[stage]-=1
    async def validate(url):assert url.startswith(root)
    async def handler(request):
        url=str(request.url)
        if url.endswith('robots.txt'):return httpx.Response(200,text='User-agent: *\nAllow: /',headers={'content-type':'text/plain'})
        if url.endswith('sitemap.xml'):
            return httpx.Response(200,text='<urlset>'+''.join('<url><loc>'+root+'/page-'+str(i)+'</loc></url>' for i in range(4))+'</urlset>',headers={'content-type':'text/xml'})
        enter('fetch')
        try:await asyncio.sleep(.3)
        finally:leave('fetch')
        return httpx.Response(200,text='<html><main>Loading fixture</main></html>',headers={'content-type':'text/html'})
    async def render(url,*args):
        enter('render')
        try:await asyncio.sleep(.45)
        finally:leave('render')
        return ('<html><title>Fixture</title><main>'+url+' '+('Useful business product pricing and shipping evidence. '*160)+'</main></html>').encode()
    async def embed(texts):
        enter('embed')
        try:await asyncio.sleep(.2)
        finally:leave('embed')
        return [[1.] for _ in texts]
    class Vectors:
        def __init__(self,client=None):pass
        async def ensure_collection(self):pass
        async def upsert(self,*args):await asyncio.sleep(.2)
    store=get_store();put=store.put
    def upload(*args,**kwargs):
        nonlocal writes
        enter('upload')
        try:
            time.sleep(.35);writes+=1
            return put(*args,**kwargs)
        finally:leave('upload')
    knowledge.validate_public_url=website_routes.validate_public_url=validate
    knowledge.PublicTransport=lambda:httpx.MockTransport(handler)
    website_crawler.rendered_html=render;website_crawler.get_store=lambda:store
    store.put=upload;knowledge.vector_configured=lambda:True;knowledge.embed=embed;knowledge.Qdrant=Vectors
    async def noop():pass
    workers.maintenance=noop
    async def task(job_id):
        enter('job')
        try:await asyncio.sleep(.25)
        finally:leave('job')
    workers.HANDLERS['benchmark']=task
    with TestClient(create_app(start_worker=False)) as client:
        response=bootstrap_account(client, '/v1/auth/signup',json={'name':'Benchmark','email':'benchmark@example.test','password':'Synthetic-Benchmark-Password','workspace_name':'Benchmark'})
        assert response.status_code==200
        ws=response.json()['workspaces'][0]['id'];base='/v1/workspaces/'+ws;client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
        created=client.post(base+'/website-assistants',json={'website_url':root,'max_pages':5,'render_js':True,'refresh_hours':0})
        assert created.status_code==202
        row=created.json();started=time.monotonic();await workers.execute_job(row['job']['id']);pipeline_seconds=time.monotonic()-started
        job=client.get(base+'/jobs/'+row['job']['id']).json()
        assert job['state']=='completed' and job['result']['pages']==5,job.get('error')
        first_writes=writes
        repeated=client.post(base+'/website-assistants/'+row['id']+'/recrawl').json();await workers.execute_job(repeated['id'])
        repeat=client.get(base+'/jobs/'+repeated['id']).json()
        assert repeat['result']['unchanged'] and writes==first_writes==5
        with session_scope(write=True) as db:
            jobs=[Job(workspace_id=ws,kind='benchmark') for _ in range(8)];db.add_all(jobs);db.flush();ids=[job.id for job in jobs]
        stop=asyncio.Event();started=time.monotonic();pool=asyncio.create_task(workers.worker_loop(stop))
        try:
            async def completed():
                while True:
                    with session_scope() as db:
                        if all(db.get(Job,job_id).state=='completed' for job_id in ids):return
                    await asyncio.sleep(.01)
            await asyncio.wait_for(completed(),30)
        finally:stop.set();await asyncio.wait_for(pool,5)
        queue_seconds=time.monotonic()-started
    assert not any(active.values())
    return {'pipeline_seconds':round(pipeline_seconds,3),'queue_seconds':round(queue_seconds,3),'pages':5,'chunks':job['result']['chunks'],
            'raw_uploads':writes,'unchanged_recrawl_skips_upload':True,'peak_parallel':peaks,
            'workload':'5 pages: HTTP 300ms, renderer 450ms, upload 350ms, embedding+upsert 400ms/batch; 8 jobs 250ms each; real 250ms request-start gate'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--label',default='after');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='studio-workers-benchmark-') as folder:result=asyncio.run(benchmark(folder))
    artifact=Path('artifacts/workers');artifact.mkdir(parents=True,exist_ok=True)
    (artifact/(args.label+'.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
