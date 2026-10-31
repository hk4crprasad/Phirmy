"""Website ingestion and widget actions use real app/DB paths with fixture sites only."""
import copy
import json
from datetime import timedelta
from unittest.mock import AsyncMock
import httpx
import pytest
from sqlalchemy import select, func
from studio import knowledge
from studio.config import settings
from studio.db import session_scope, now
from studio.models import Agent, AgentVersion, WebsiteAssistant, Source, Snapshot, Job, Product, Installation, Message
from studio.workers import execute_job
from studio.website_actions import execute, clean_page_url
from studio.website_extraction import sitemap_locations, commerce_facts

SITE = 'https://market.example'
PRODUCT = {'@context':'https://schema.org','@type':'Product','name':'Amber hand cream','description':'A fragrance-free cream with oat extract. Apply to dry hands.','image':SITE+'/cream.webp',
           'url':SITE+'/products/amber','offers':[{'price':'12.50','priceCurrency':'USD','availability':'https://schema.org/InStock','sku':'A-50'}, {'name':'100 ml','price':'19.00','priceCurrency':'USD','availability':'https://schema.org/OutOfStock','sku':'A-100'}],
           'additionalProperty':[{'name':'Volume','value':'50 ml'}]}


@pytest.fixture
def website(account, monkeypatch):
    client, ws, base = account
    from conftest import verify_test_origin
    verify_test_origin(client, base, SITE, monkeypatch)
    pages = {
        '/robots.txt':('User-agent: *\nDisallow: /private\nCrawl-delay: 1\nSitemap: '+SITE+'/sitemap-index.xml','text/plain'),
        '/sitemap-index.xml':('<sitemapindex><sitemap><loc>'+SITE+'/products-map.xml</loc></sitemap></sitemapindex>','text/xml'),
        '/products-map.xml':('<urlset><url><loc>'+SITE+'/products/amber</loc></url><url><loc>'+SITE+'/private</loc></url><url><loc>http://127.0.0.1/metadata</loc></url></urlset>','text/xml'),
        '/sitemap.xml':('<urlset/>','text/xml'),
        '/':('<title>Market</title><main>We make hand care for dry skin. Business contact hello@market.example. Our cream contains oat extract.</main><a href="/faq">Questions</a><a href="/duplicate">Alias</a>', 'text/html'),
        '/duplicate':('<title>Market</title><main>We make hand care for dry skin. Business contact hello@market.example. Our cream contains oat extract.</main>', 'text/html'),
        '/faq':('<title>Help</title><main><h2 id="delivery">Delivery</h2>Shipping takes four business days. Returns are accepted for unopened items within 14 days.</main>','text/html'),
        '/products/amber':('<title>Amber hand cream</title><main><h2 id="benefits">Benefits</h2>Oat extract helps moisturize dry hands. A fragrance-free daily hand cream.</main><script type="application/ld+json">'+json.dumps(PRODUCT)+'</script>','text/html'),
    }
    calls = []
    async def validate(url):
        assert url.startswith(SITE)
    async def fetch(url, *args, **kwargs):
        from urllib.parse import urlparse
        calls.append(url)
        assert url.startswith(SITE)
        path = urlparse(url).path or '/'
        if path not in pages:
            response = httpx.Response(404,request=httpx.Request('GET',url))
            raise httpx.HTTPStatusError('Missing',request=response.request,response=response)
        body,mime=pages[path]
        return url,body.encode(),mime
    monkeypatch.setattr(knowledge,'validate_public_url',validate)
    monkeypatch.setattr(knowledge,'safe_fetch',fetch)
    import studio.website_routes as website_routes
    monkeypatch.setattr(website_routes,'validate_public_url',validate)
    # Site crawl delays are tested separately; don't spend seconds per fixture page.
    import studio.website_crawler as crawler
    monkeypatch.setattr(crawler.asyncio,'sleep',AsyncMock())
    return client,ws,base,pages,calls


async def create_and_crawl(website, **extra):
    client,ws,base,_,_ = website
    response=client.post(base+'/website-assistants',json={'website_url':SITE,'name':'Market assistant','render_js':False, **extra})
    assert response.status_code == 202,response.text
    row=response.json()
    await execute_job(row['job']['id'])
    row=client.get(base+'/website-assistants').json()['items'][0]
    assert row['job']['state']=='completed',row['job']
    return row


def public_session(client,row,origin=SITE):
    response=client.post('/v1/public/sessions',headers={'Origin':origin},json={'visitor_email':'visitor@example.test','installation_public_id':row['installation']['public_id'],'public_key':row['installation']['theme']['publishable_key']})
    assert response.status_code==201,response.text
    return response.json()


def chat(client,session,text,page_url=SITE+'/products/amber',key='turn-1'):
    response=client.post('/v1/public/chat',headers={'Origin':SITE,'Authorization':'Bearer '+session['session_token']},json={'session_id':session['id'],'message':text,'client_message_id':key,'page_url':page_url})
    assert response.status_code==200,response.text
    return [json.loads(p.split('data: ',1)[1]) for p in response.text.split('\n\n') if p.startswith('event: chat.completed')][0]


@pytest.mark.asyncio
async def test_full_url_pipeline_sitemaps_products_permissions_and_dedup(website):
    client,ws,base,_,calls=website
    row=await create_and_crawl(website)
    assert row['knowledge']['pages_indexed']==3
    assert row['job']['result']['duplicates']==1
    assert SITE+'/products/amber' in calls and SITE+'/private' not in calls
    assert all(u.startswith(SITE) for u in calls)
    assert row['job']['result']['failures'][0]['reason'].startswith('robots')
    with session_scope() as db:
        agent=db.get(Agent,row['agent_id']); version=db.get(AgentVersion,agent.published_version_id)
        assert version.config['knowledge_snapshot_ids']==[row['knowledge']['active_snapshot_id']]
        product=db.scalar(select(Product).where(Product.workspace_id==ws))
        assert product.price_minor==1250 and product.availability=='in_stock'
        assert product.provenance['variants'][1]['price_minor']==1900
        assert db.get(Source,product.provenance['source_id']).canonical_url==PRODUCT['url']
    same=client.post(base+'/website-assistants',json={'website_url':SITE,'name':'Repeated'}).json()
    assert same['id']==row['id']
    assert len(client.get(base+'/agents').json()['items'])==1
    q=client.post(base+'/knowledge/'+row['kb_id']+'/query',json={'query':'What helps moisturize dry hands?'}).json()
    assert q['answerable'] and any(p['url']==PRODUCT['url'] for p in q['passages'])


@pytest.mark.asyncio
async def test_page_context_navigation_history_resume_and_rotation(website):
    client,ws,base,_,_=website;row=await create_and_crawl(website)
    installation=row['installation'];public_id=installation['public_id']
    with session_scope(write=True) as db:
        item=db.get(Installation,installation['id']);item.theme={**item.theme,'restrict_origins':True}
    assert client.post('/v1/public/sessions',headers={'Origin':SITE},json={'visitor_email':'visitor@example.test','installation_public_id':public_id}).status_code==403
    assert client.post('/v1/public/sessions',headers={'Origin':'https://other.example'},json={'visitor_email':'visitor@example.test','installation_public_id':public_id,'public_key':installation['theme']['publishable_key']}).status_code==403
    state=public_session(client,row)
    answer=chat(client,state,'What are the benefits of this product?')
    assert 'oat' in answer['text'].lower() and answer['products'][0]['title']=='Amber hand cream'
    opened=chat(client,state,'Open this product page',key='turn-2')
    assert opened['actions'][0]['url']==PRODUCT['url']
    resumed=client.post('/v1/public/sessions/resume',headers={'Origin':SITE,'Authorization':'Bearer '+state['resume_token']}).json()
    assert resumed['id']==state['id'] and len(resumed['history'])==4
    assert resumed['history'][-1]['actions'][0]['id']==opened['actions'][0]['id']
    wrong=client.post('/v1/public/sessions/resume',headers={'Origin':'https://other.example','Authorization':'Bearer '+state['resume_token']})
    assert wrong.status_code==403
    rotated=client.post(base+'/website-assistants/'+row['id']+'/rotate-key').json()
    assert rotated['installation']['theme']['publishable_key']!=installation['theme']['publishable_key']
    assert client.post('/v1/public/sessions/resume',headers={'Origin':SITE,'Authorization':'Bearer '+state['resume_token']}).status_code==403
    assert client.post('/v1/public/chat',headers={'Origin':SITE,'Authorization':'Bearer '+state['session_token']},json={'session_id':state['id'],'message':'Hi','client_message_id':'rotated'}).status_code==403


@pytest.mark.asyncio
async def test_refresh_preserves_human_draft_and_old_live_snapshot(website):
    client,ws,base,pages,_=website;row=await create_and_crawl(website)
    original=row['knowledge']['active_snapshot_id']
    with session_scope(write=True) as db:
        agent=db.get(Agent,row['agent_id']);agent.draft_config={**agent.draft_config,'instructions':'Unpublished custom instructions'};agent.draft_revision+=1
    newproduct={**PRODUCT,'offers':{'price':'13.75','priceCurrency':'USD'}}
    pages['/products/amber']=(pages['/products/amber'][0].replace(json.dumps(PRODUCT),json.dumps(newproduct)),'text/html')
    job=client.post(base+'/website-assistants/'+row['id']+'/recrawl').json();await execute_job(job['id'])
    latest=client.get(base+'/website-assistants').json()['items'][0]
    assert latest['knowledge']['active_snapshot_id']!=original
    with session_scope() as db:
        agent=db.get(Agent,row['agent_id']);version=db.get(AgentVersion,agent.published_version_id)
        assert agent.draft_config['instructions']=='Unpublished custom instructions'
        assert version.config['instructions']!='Unpublished custom instructions'
        assert db.get(Snapshot,original).state=='published'
        assert db.scalar(select(Product.price_minor).where(Product.workspace_id==ws))==1375
    options={**row['options'],'excluded_urls':[PRODUCT['url']]}
    assert client.put(base+'/website-assistants/'+row['id']+'/options',json=options).status_code==200
    job=client.post(base+'/website-assistants/'+row['id']+'/recrawl').json();await execute_job(job['id'])
    latest=client.get(base+'/website-assistants').json()['items'][0]
    with session_scope() as db:
        snapshot=db.get(Snapshot,latest['knowledge']['active_snapshot_id'])
        assert all(db.get(Source,s).canonical_url!=PRODUCT['url'] for s in snapshot.source_ids)
    assert not chat(client,public_session(client,latest),'What is the amber cream price?',key='excluded')['products']


@pytest.mark.asyncio
async def test_closed_actions_and_tenant_corpus(website):
    client,ws,base,_,_=website;row=await create_and_crawl(website)
    context={'workspace_id':ws,'installation_id':row['installation_id'],'knowledge_snapshot_ids':[row['knowledge']['active_snapshot_id']],'page_url':SITE+'/faq','user_text':'Open the delivery section','operation_id':'test'}
    assert execute('website_scroll',{'section_id':'delivery'},context)['actions'][0]['type']=='scroll'
    for url in ['javascript:alert(1)','https://evil.example/','http://127.0.0.1/','https://market.example/private','https://market.example@evil.example/']:
        assert 'error' in execute('website_open_page',{'url':url},context)
    assert 'error' in execute('website_scroll',{'section_id':'body;script'},context)
    assert 'error' in execute('website_open_page',{'url':PRODUCT['url']},{**context,'user_text':'What are the benefits?'})
    assert not execute('website_search',{'query':'Amber'},{**context,'knowledge_snapshot_ids':[]})['products']
    assert 'error' in execute('website_search',{'query':'Amber'},{**context,'workspace_id':'another-workspace'})
    assert clean_page_url(SITE+'/products/amber?email=private@example.test#secret',[SITE])==PRODUCT['url']
    assert clean_page_url('https://evil.example/products/amber',[SITE]) is None


def test_sitemap_entities_and_product_invalid_prices():
    with pytest.raises(ValueError): sitemap_locations(b'<!DOCTYPE x [<!ENTITY e "expansion">]><urlset/>')
    assert commerce_facts({'jsonld':[{**PRODUCT,'offers':{'price':'NaN','priceCurrency':'USD'}}]},PRODUCT['url'])[0]['variants']==[]
    assert commerce_facts({'jsonld':[{**PRODUCT,'url':'https://evil.example/'}]},PRODUCT['url'])==[]


@pytest.mark.asyncio
async def test_agent_create_with_url_and_automatic_update_queue(website):
    client,ws,base,_,_=website
    response=client.post(base+'/agents',json={'name':'From agent create','website_url':SITE})
    assert response.status_code==201,response.text
    row=response.json()['website_assistant']
    await execute_job(row['job']['id'])
    from studio.website_routes import schedule_updates
    with session_scope(write=True) as db:
        db.get(WebsiteAssistant,row['id']).next_crawl_at=now()-timedelta(minutes=1)
        schedule_updates(db);schedule_updates(db)
        queued=[j for j in db.scalars(select(Job).where(Job.workspace_id==ws,Job.state=='queued'))]
        assert len(queued)==1


@pytest.mark.asyncio
async def test_redirect_and_permission_checks_precede_network(monkeypatch):
    monkeypatch.setattr(knowledge,'validate_public_url',AsyncMock())
    requests=[]
    def handler(request):
        requests.append(str(request.url));return httpx.Response(302,headers={'Location':'http://127.0.0.1/metadata'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError,match='Cross-origin'):
            await knowledge.safe_fetch(SITE,client=client,same_origin=('https','market.example'))
    assert requests==[SITE]


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_renderer_executes_same_origin_js_but_blocks_external_and_post(monkeypatch):
    import asyncio
    from urllib.robotparser import RobotFileParser
    from studio.website_extraction import rendered_html
    requests=[]
    async def fetch(url, *args, **kwargs):
        requests.append(url)
        if url == SITE+'/dynamic':
            return url, b'''<html><main id="result"></main><script src="/app.js"></script><script src="https://external.example/tracker.js"></script></html>''','text/html'
        assert url==SITE+'/app.js'
        return url, b'''document.getElementById('result').textContent='Rendered service consultation costs USD 35.'; fetch('http://127.0.0.1/metadata'); fetch('/mutate', {method:'POST',body:'no'}); new WebSocket('wss://external.example/socket');''','application/javascript'
    monkeypatch.setattr(knowledge,'safe_fetch',fetch)
    robot=RobotFileParser();robot.parse(['User-agent: *','Allow: /'])
    html=await rendered_html(SITE+'/dynamic',robot,0)
    assert b'Rendered service consultation costs USD 35.' in html
    assert requests==[SITE+'/dynamic',SITE+'/app.js']


@pytest.mark.asyncio
async def test_crawl_model_search_and_navigation_share_real_tool_runtime(website, monkeypatch):
    client,ws,base,_,_=website;row=await create_and_crawl(website)
    from studio import llm, chat_routes
    rounds=[]; outputs=[]
    class ModelTurn:
        def __init__(self, *args, **kwargs):
            self.calls=[]
            assert {x['name'] for x in kwargs['tools']} >= {'website_search','website_open_page','capture_lead'}
        async def stream(self):
            step=len(rounds);rounds.append(step)
            if step==0:self.calls=[{'name':'website_search','arguments':json.dumps({'query':'Amber hand cream'}),'call_id':'search'}]
            elif step==1:self.calls=[{'name':'website_open_page','arguments':json.dumps({'url':PRODUCT['url']}),'call_id':'open'}]
            else:yield 'This cream contains oat extract. Opening its page.'
        def append_results(self, results): outputs.extend(results)
    monkeypatch.setattr(llm,'resolve',lambda *args:{'api_key':'synthetic-model','model':'synthetic-model'})
    monkeypatch.setattr(chat_routes,'resolve',lambda *args:{'api_key':'synthetic-model','model':'synthetic-model'})
    monkeypatch.setattr(llm,'Turn',ModelTurn)
    response=chat(client,public_session(client,row),'Show me the Amber hand cream')
    assert response['actions'][0]['url']==PRODUCT['url'] and response['products'][0]['price_minor']==1250
    assert outputs[0]['products'][0]['description'].startswith('A fragrance-free')
    assert outputs[1]['status']=='requested' and len(rounds)==3


@pytest.mark.asyncio
async def test_failed_update_and_exclusions_never_leak_partial_products(website):
    client,ws,base,pages,_=website;row=await create_and_crawl(website)
    state=public_session(client,row)
    original=row['knowledge']['active_snapshot_id']
    pages['/products/amber']=(pages['/products/amber'][0].replace('12.50','77.00'),'text/html')
    import studio.website_crawler as crawler
    original_index=knowledge.index_snapshot
    async def failing_index(*args): raise RuntimeError('Synthetic index failure')
    knowledge.index_snapshot=failing_index
    try:
        job=client.post(base+'/website-assistants/'+row['id']+'/recrawl').json();await execute_job(job['id'])
    finally: knowledge.index_snapshot=original_index
    latest=client.get(base+'/website-assistants').json()['items'][0]
    assert latest['knowledge']['active_snapshot_id']==original and latest['job']['state']=='failed'
    answer=chat(client,state,'What is the cream price?')
    assert answer['products'][0]['price_minor']==1250 and '77' not in answer['text']


@pytest.mark.asyncio
async def test_unchanged_recrawl_reuses_sources_blobs_snapshot_and_agent(website, monkeypatch):
    client, ws, base, pages, _ = website
    row = await create_and_crawl(website)
    original = row['knowledge']['active_snapshot_id']
    with session_scope() as db:
        version = db.get(Agent, row['agent_id']).published_version_id
        snapshots = db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.kb_id == row['kb_id']))
    # A changing HTML nonce should not upload a blob when extracted facts match.
    pages['/'] = (pages['/'][0] + '<script>const nonce="changed"</script>', 'text/html')
    from studio.storage import get_store
    def unexpected(*args, **kwargs): raise AssertionError('Unchanged pages must not be uploaded or re-embedded')
    monkeypatch.setattr(get_store(), 'put', unexpected)
    monkeypatch.setattr(knowledge, 'index_snapshot', unexpected)
    job = client.post(base+'/website-assistants/'+row['id']+'/recrawl').json()
    await execute_job(job['id'])
    latest = client.get(base+'/website-assistants').json()['items'][0]
    assert latest['job']['state'] == 'completed', latest['job']
    assert latest['job']['result']['unchanged'] and latest['job']['result']['reused_pages'] >= 3
    assert latest['knowledge']['active_snapshot_id'] == original
    with session_scope() as db:
        assert db.get(Agent, row['agent_id']).published_version_id == version
        assert db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.kb_id == row['kb_id'])) == snapshots


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['fetch', 'render', 'index'])
async def test_stop_interrupts_inflight_work_without_publishing(website, monkeypatch, phase):
    import asyncio
    from studio import website_crawler as crawler
    from studio.models import Job
    client, ws, base, pages, _ = website
    row = await create_and_crawl(website)
    original = row['knowledge']['active_snapshot_id']
    pages['/'] = (pages['/'][0].replace('dry skin', 'sensitive skin'), 'text/html')
    entered = asyncio.Event()
    async def block(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    if phase == 'fetch':
        fetch = knowledge.safe_fetch
        async def slow(url, *args, **kwargs):
            if url == SITE+'/': return await block()
            return await fetch(url, *args, **kwargs)
        monkeypatch.setattr(knowledge, 'safe_fetch', slow)
    elif phase == 'render':
        options = {**row['options'], 'render_js': True}
        assert client.put(base+'/website-assistants/'+row['id']+'/options', json=options).status_code == 200
        monkeypatch.setattr(crawler, 'rendered_html', block)
    else:
        monkeypatch.setattr(knowledge, 'index_snapshot', block)
    job = client.post(base+'/website-assistants/'+row['id']+'/recrawl').json()
    task = asyncio.create_task(execute_job(job['id']))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        stopped = client.post(base+'/jobs/'+job['id']+'/cancel')
        assert stopped.status_code == 200
        assert stopped.json()['phase'] == 'stopping'
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    latest = client.get(base+'/website-assistants').json()['items'][0]
    assert latest['job']['state'] == 'canceled'
    assert latest['knowledge']['status'] == 'ready'
    assert latest['knowledge']['active_snapshot_id'] == original
    assert client.get(base+'/website-assistants/'+row['id']+'/pages').status_code == 200


def test_queued_stop_updates_knowledge_and_denies_other_tenant(website):
    client, ws, base, _, _ = website
    row = client.post(base+'/website-assistants', json={'website_url': SITE, 'name': 'Queued'}).json()
    job_id = row['job']['id']
    assert client.post('/v1/workspaces/foreign/jobs/'+job_id+'/cancel').status_code == 404
    assert client.post(base+'/jobs/'+job_id+'/cancel').json()['state'] == 'canceled'
    latest = client.get(base+'/website-assistants').json()['items'][0]
    assert latest['knowledge']['status'] == 'canceled'


@pytest.mark.asyncio
async def test_page_downloads_overlap_with_bounded_concurrency(website, monkeypatch):
    import asyncio
    client, ws, base, _, _ = website
    from studio.config import settings
    monkeypatch.setattr(settings, 'crawl_concurrency', 2)
    fetch = knowledge.safe_fetch
    active = peak = 0
    overlapped = asyncio.Event()
    async def delayed(url, *args, **kwargs):
        nonlocal active, peak
        if url.endswith('.xml') or url.endswith('robots.txt'): return await fetch(url, *args, **kwargs)
        active += 1; peak = max(peak, active)
        if active == 2:
            overlapped.set()
        try:
            await asyncio.wait_for(overlapped.wait(), timeout=5)
            return await fetch(url, *args, **kwargs)
        finally: active -= 1
    monkeypatch.setattr(knowledge, 'safe_fetch', delayed)
    await create_and_crawl(website)
    assert peak == 2 and active == 0


@pytest.mark.asyncio
async def test_ready_pages_are_saved_while_first_page_is_still_fetching(website, monkeypatch):
    import asyncio
    from studio import website_crawler as crawler
    client,ws,base,_,_=website
    fetch=knowledge.safe_fetch;release=asyncio.Event();entered=asyncio.Event()
    async def delayed(url,*args,**kwargs):
        if url==SITE+'/':
            entered.set();await release.wait()
        return await fetch(url,*args,**kwargs)
    monkeypatch.setattr(knowledge,'safe_fetch',delayed)
    created=client.post(base+'/website-assistants',json={'website_url':SITE,'render_js':False,'refresh_hours':0}).json()
    task=asyncio.create_task(execute_job(created['job']['id']))
    try:
        await asyncio.wait_for(entered.wait(),2)
        async def saved():
            while True:
                with session_scope() as db:
                    if db.scalar(select(Source.id).where(Source.kb_id==created['kb_id'],Source.canonical_url==SITE+'/products/amber')):return
                await asyncio.to_thread(lambda:None)
        await asyncio.wait_for(saved(),2)
        assert not task.done()
    finally:
        release.set();await asyncio.wait_for(task,3)
    assert client.get(base+'/jobs/'+created['job']['id']).json()['state']=='completed'


@pytest.mark.asyncio
async def test_multiple_crawls_share_renderer_limit(website, monkeypatch):
    import asyncio
    from studio import website_crawler as crawler
    client,ws,base,pages,_=website
    monkeypatch.setattr(settings,'render_concurrency',2)
    active=peak=0
    overlapped=asyncio.Event()
    async def render(url,*args):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        if active==2:
            overlapped.set()
        try:
            # Wait for actual overlap rather than hoping both crawls reach this
            # point within 30ms on a busy CI runner.
            await asyncio.wait_for(overlapped.wait(),timeout=5)
            from urllib.parse import urlparse
            return pages[urlparse(url).path or '/'][0].encode()
        finally:active-=1
    monkeypatch.setattr(crawler,'rendered_html',render)
    rows=[client.post(base+'/website-assistants',json={'website_url':SITE,'name':'Renderer '+str(i),'render_js':True,'refresh_hours':0}).json() for i in range(2)]
    await asyncio.gather(*(execute_job(row['job']['id']) for row in rows))
    assert peak==2 and active==0
    assert all(client.get(base+'/jobs/'+row['job']['id']).json()['state']=='completed' for row in rows)


def test_website_listing_uses_constant_query_count(website):
    from sqlalchemy import event
    from studio.db import engine
    client, ws, base, _, _ = website
    for index in range(5):
        assert client.post(base+'/website-assistants', json={'website_url': SITE+'/site-'+str(index), 'name': str(index)}).status_code == 202
    statements = []
    def capture(conn, cursor, statement, *args): statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = client.get(base+'/website-assistants')
    finally: event.remove(engine, 'before_cursor_execute', capture)
    assert response.status_code == 200
    assert len(response.json()['items']) == 5
    # Includes current-session/user/membership authorization. Old code did 6 per assistant.
    assert len(statements) <= 14, len(statements)


@pytest.mark.asyncio
async def test_readable_next_page_does_not_start_browser(website, monkeypatch):
    from studio import website_crawler
    client, ws, base, pages, _ = website
    for path in ('/', '/faq', '/duplicate', '/products/amber'):
        html,mime=pages[path]
        pages[path]=(html.replace('</main>', '<p>'+('Readable server rendered evidence. '*30)+'</p></main>')+'<script id="__NEXT_DATA__">{}</script>',mime)
    async def unexpected(*args): raise AssertionError('Readable SSR pages must skip Chromium')
    monkeypatch.setattr(website_crawler,'rendered_html',unexpected)
    row=await create_and_crawl(website,render_js=True)
    assert row['job']['result']['rendered_pages']==0
    assert not any('Dynamic rendering failed' in failure['reason'] for failure in row['job']['result']['failures'])


@pytest.mark.asyncio
async def test_rate_limited_page_retries_bounded_read_only_fetch(website,monkeypatch):
    client, ws, base, _, _=website
    fetch=knowledge.safe_fetch
    attempts=0
    async def transient(url,*args,**kwargs):
        nonlocal attempts
        if url==SITE+'/':
            attempts+=1
            if attempts<3:
                response=httpx.Response(429,headers={'Retry-After':'1'},request=httpx.Request('GET',url))
                response.raise_for_status()
        return await fetch(url,*args,**kwargs)
    monkeypatch.setattr(knowledge,'safe_fetch',transient)
    row=await create_and_crawl(website)
    assert row['job']['state']=='completed' and attempts==3
