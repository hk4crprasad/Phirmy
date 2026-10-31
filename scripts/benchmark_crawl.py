"""Compare one vs four downloads with actual pacing and synthetic HTTP latency.

No external website or provider is contacted. This is a local controlled workload,
not a real-site latency guarantee. The real crawler/extractor/database are used.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from qa_accounts import bootstrap_account
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
logging.disable(logging.CRITICAL)


async def main(folder):
    os.environ.update(APP_ENV='test',DATABASE_URL='sqlite:///'+folder+'/qa.db',SUPABASE_DB_PASSWORD='',DATA_DIR=folder+'/data',
        OBJECT_STORAGE_PROVIDER='local',AZURE_STORAGE_CONNECTION_STRING='',AZURE_STORAGE_ACCOUNT_URL='',REDIS_URL='',
        OPENAI_API_KEY='',EMBEDDING_API_KEY='',VECTOR_ENDPOINT='',VECTOR_API_KEY='',SMTP_HOST='',
        REQUIRE_EMAIL_VERIFICATION='false',SESSION_SECURE='false',APP_SECRET='synthetic-performance-'+'x'*32)
    import httpx
    from fastapi.testclient import TestClient
    from studio import knowledge,website_routes
    from studio.config import settings
    from studio.main import create_app
    from studio.workers import execute_job
    prefix='https://synthetic-performance.example/'
    root=prefix
    active=peak=0
    async def validate(url):
        assert url.startswith(prefix)
    async def handler(request):
        nonlocal active,peak
        url=str(request.url)
        if url.endswith('robots.txt'): return httpx.Response(200,text='User-agent: *\nAllow: /',headers={'content-type':'text/plain'})
        if url.endswith('sitemap.xml'):
            return httpx.Response(200,text='<urlset>'+''.join('<url><loc>'+root+'/page-'+str(i)+'</loc></url>' for i in range(4))+'</urlset>',headers={'content-type':'application/xml'})
        active+=1;peak=max(peak,active)
        try: await asyncio.sleep(.6)
        finally: active-=1
        body='<html><title>Fixture</title><main>'+url+' '+('Useful synthetic business evidence. '*40)+'</main></html>'
        return httpx.Response(200,text=body,headers={'content-type':'text/html'})
    knowledge.validate_public_url=website_routes.validate_public_url=validate
    knowledge.PublicTransport=lambda:httpx.MockTransport(handler)
    results=[]
    with TestClient(create_app(start_worker=False)) as client:
        response=bootstrap_account(client, '/v1/auth/signup',json={'name':'Benchmark','email':'benchmark@example.test','password':'Synthetic-Benchmark-Password','workspace_name':'Benchmark'})
        ws=response.json()['workspaces'][0]['id'];base='/v1/workspaces/'+ws
        client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
        for concurrency in (1,4):
            settings.crawl_concurrency=concurrency;peak=0;root=prefix+str(concurrency)
            created=client.post(base+'/website-assistants',json={'website_url':root,'name':'Benchmark','max_pages':5,'render_js':False,'refresh_hours':0})
            assert created.status_code==202
            row=created.json();started=time.monotonic();await execute_job(row['job']['id']);elapsed=time.monotonic()-started
            job=client.get(base+'/jobs/'+row['job']['id']).json()
            assert job['state']=='completed' and job['result']['pages']==5
            results.append({'concurrency':concurrency,'pages':5,'seconds':round(elapsed,3),'peak_downloads':peak})
    assert results[0]['peak_downloads']==1 and 1<results[1]['peak_downloads']<=4
    output={'workload':'5 synthetic pages, 600ms each, real 250ms request-start gate', 'runs':results,'speedup':round(results[0]['seconds']/results[1]['seconds'],2)}
    Path('artifacts/crawl-benchmark.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output))

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='studio-crawl-benchmark-') as folder:asyncio.run(main(folder))
