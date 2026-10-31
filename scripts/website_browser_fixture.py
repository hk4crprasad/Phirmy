"""QA-only live HTTP website. Production crawler/DB/worker/routes are unchanged.

Only the public-network guard/transport is replaced for this exact loopback site.
No real provider, customer URL, credential, email or booking is used.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
import httpx
import uvicorn
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from studio import knowledge, website_routes
from studio.main import create_app
from studio.config import settings
SITE=os.environ['QA_WEBSITE_ORIGIN']; WEB=settings.app_origin
installed={}
slow_fetch=False
original=knowledge.safe_fetch
async def validate(url):
    if urlparse(url).scheme+'://'+urlparse(url).netloc != SITE: raise ValueError('QA only permits its exact fixture origin')
async def fetch(url,*args,**kwargs):
    await validate(url)
    if slow_fetch and '/fixture-site' in url: await asyncio.sleep(30)
    if not (urlparse(url).path.startswith('/fixture-site') or urlparse(url).path in ['/robots.txt','/sitemap.xml']): raise ValueError('QA request outside fixture website')
    async with httpx.AsyncClient(trust_env=False) as client:
        response=await client.get(url);response.raise_for_status()
        return url,response.content,response.headers['content-type']
knowledge.validate_public_url=website_routes.validate_public_url=validate
knowledge.safe_fetch=fetch
app=create_app(start_worker=True)

@app.post('/qa-slow')
def slow(body:dict):
    global slow_fetch
    slow_fetch=body['enabled'];return {'enabled':slow_fetch}

@app.post('/qa-install')
def install(body:dict):
    installed.update(body);return {'status':'fixture-only'}

@app.get('/robots.txt')
def robots():return PlainTextResponse('User-agent: *\nAllow: /fixture-site\nDisallow: /v1\nDisallow: /qa-install\nSitemap: '+SITE+'/sitemap.xml')

@app.get('/sitemap.xml')
def sitemap():return Response('<urlset><url><loc>'+SITE+'/fixture-site/products/amber</loc></url><url><loc>'+SITE+'/fixture-site/help</loc></url></urlset>',media_type='application/xml')

@app.get('/fixture-site')
@app.get('/fixture-site/{path:path}')
def website(path:str=''):
    product={'@context':'https://schema.org','@type':'Product','name':'Amber hand cream','description':'A fragrance-free hand cream with oat extract for dry hands. Use a small amount after washing your hands.','url':SITE+'/fixture-site/products/amber','offers':{'price':'12.50','priceCurrency':'USD','availability':'https://schema.org/InStock'}}
    if path.startswith('products/'):
        content='<h1>Amber hand cream</h1><h2 id="benefits">Benefits</h2><p>Fragrance-free daily care with oat extract for dry hands. A 50 ml tube costs USD 12.50.</p><script type="application/ld+json">'+json.dumps(product)+'</script>'
    elif path=='help':content='<h1>Help & delivery</h1><h2 id="delivery">Delivery</h2><p>Shipping takes four business days. Returns are accepted within 14 days for unopened items.</p>'
    else:content='<h1>Market Studio</h1><p>Thoughtful hand care for everyday life. We offer fragrance-free creams made with oat extract. Our team can help with product questions, delivery and returns.</p><a href="/fixture-site/help">Help</a>'
    # Enough static text to keep this acceptance focused on normal website ingestion.
    content+='<p>Choose the right care for your hands. Our product pages include ingredients, usage instructions, current pricing and availability. Ask our assistant for help finding a product or reading our delivery policy.</p>'
    script=''
    if installed:script='<script defer src="'+WEB+'/widget.js" data-widget-id="'+installed['id']+'" data-public-key="'+installed['key']+'"></script>'
    return HTMLResponse('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Market Studio</title><style>body{margin:0;background:#faf9f7;color:#282622;font:16px system-ui}header{padding:25px 6%;border-bottom:1px solid #e8e4dd}main{max-width:850px;margin:70px auto;padding:25px}h1{font-size:42px}p{max-width:620px;line-height:1.8}a{color:inherit}</style></head><body><header>MARKET STUDIO</header><main>'+content+'</main>'+script+'</body></html>')

uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
