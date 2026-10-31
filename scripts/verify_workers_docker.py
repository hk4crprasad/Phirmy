"""Actual API/worker image acceptance with disposable local SQLite + objects.

Uses no private .env, external website, provider credentials or customer data.
Requires a locally built studio-worker-qa:local image.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import httpx

from qa_accounts import bootstrap_account
root=Path.cwd();suffix=secrets.token_hex(4);api='worker-api-'+suffix;worker='worker-process-'+suffix
docker=['docker','--host=unix:///var/run/docker.sock']
with tempfile.TemporaryDirectory(prefix='worker-docker-') as temporary:
    folder=Path(temporary);folder.chmod(0o755);data=folder/'data';data.mkdir();data.chmod(0o777)
    env={'APP_ENV':'test','DATABASE_URL':'sqlite:////app/data/qa.db','DATA_DIR':'/app/data','OBJECT_STORAGE_PROVIDER':'local',
         'APP_SECRET':'disposable-worker-'+secrets.token_urlsafe(40),'WORKER_ENABLED':'false','REQUIRE_EMAIL_VERIFICATION':'false',
         'SESSION_SECURE':'false','DEV_SEED_ENABLED':'true','WORKER_CONCURRENCY':'4'}
    envfile=folder/'runtime.env';envfile.write_text(''.join(key+'='+value+'\n' for key,value in env.items()));envfile.chmod(0o600)
    def run(*args):
        result=subprocess.run(docker+list(args),capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Disposable Docker command failed: '+result.stderr[-400:])
        return result.stdout.strip()
    try:
        run('run','--rm','-d','--name',api,'--env-file',str(envfile),'-v',str(data)+':/app/data','-p','127.0.0.1::8100','studio-worker-qa:local')
        port=json.loads(run('inspect',api))[0]['NetworkSettings']['Ports']['8100/tcp'][0]['HostPort'];origin='http://127.0.0.1:'+port
        with httpx.Client(base_url=origin,timeout=10,trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get('/healthz').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            response=bootstrap_account(client, '/v1/auth/signup',json={'name':'Docker QA','email':'docker@example.test','password':'Long-Isolated-Password','workspace_name':'Docker QA'})
            assert response.status_code==200,response.text
            base='/v1/workspaces/'+response.json()['workspaces'][0]['id'];client.headers['X-CSRF-Token']=client.cookies['studio_csrf']
            fixture=client.post(base+'/fixtures',json={});assert fixture.status_code==201
            knowledge=client.get(base+'/knowledge').json()['items'][0]
            response=client.post(base+'/knowledge/'+knowledge['id']+'/documents',files={'file':('worker.txt',b'Synthetic worker document. Shipping takes five business days.','text/plain')})
            assert response.status_code==202,response.text
            job_id=response.json()['id'];time.sleep(.4)
            assert client.get(base+'/jobs/'+job_id).json()['state']=='queued','API unexpectedly claimed a worker job'
            run('run','-d','--init','--name',worker,'--env-file',str(envfile),'-v',str(data)+':/app/data','studio-worker-qa:local','python','-m','studio.worker_main')
            for _ in range(120):
                job=client.get(base+'/jobs/'+job_id).json()
                if job['state'] in {'completed','failed'}:break
                time.sleep(.1)
            assert job['state']=='completed',job.get('error')
            health=run('exec',worker,'python','-c',"import time; from pathlib import Path; p=Path('/tmp/studio-worker-heartbeat'); assert p.exists() and time.time()-p.stat().st_mtime<30; print('healthy')")
            assert health=='healthy'
            kb=client.get(base+'/knowledge/'+knowledge['id']).json();assert kb['active_snapshot_id']==job['result']['snapshot_id']
            assert client.get('/healthz').status_code==200
            run('stop','--timeout','10',worker)
            assert json.loads(run('inspect',worker))[0]['State']['ExitCode']==0
        output={'api_without_dispatcher':'passed','queued_document_completed_in_dedicated_container':'passed','shared_objects_and_database':'passed',
                'knowledge_published':'passed','worker_heartbeat':'passed','worker_sigterm_shutdown':'passed','image':'studio-worker-qa:local'}
        artifact=root/'artifacts/workers';artifact.mkdir(parents=True,exist_ok=True);(artifact/'docker.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output))
    finally:
        for name in (worker,api):subprocess.run(docker+['rm','-f',name],capture_output=True)
        # Image UID10001 owns nested object directories. Make only this unique
        # disposable bind mount removable by the calling (non-root) QA user.
        subprocess.run(docker+['run','--rm','--user','0','--network','none','-v',str(data)+':/app/data','studio-worker-qa:local','python','-c',
            "import os; [os.chmod(path,0o777) for path,dirs,files in os.walk('/app/data')]"] ,capture_output=True)
