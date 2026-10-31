"""Bounded sitemap discovery, structured commerce facts and guarded rendering."""
import asyncio
import json
import re
import base64
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup
from sqlalchemy import select
from .db import now
from .models import Product

RENDER_TIMEOUT_SECONDS = 30
RENDER_SETTLE_MILLISECONDS = 1500


def origin(url):
    p = urlparse(url)
    return p.scheme, p.netloc


def sitemap_locations(body):
    # No DTD/entity expansion. Input also has the crawler's byte limit.
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('Sitemap entities are not supported')
    root = ET.fromstring(body)
    if root.tag.rsplit('}', 1)[-1] not in {'sitemapindex', 'urlset'}:
        return [], []
    links = [x.text.strip() for x in root.iter() if x.tag.rsplit('}', 1)[-1] == 'loc' and x.text]
    return ([], links) if root.tag.endswith('sitemapindex') else (links, [])


def product_objects(value):
    if isinstance(value, list):
        return [p for item in value for p in product_objects(item)]
    if not isinstance(value, dict):
        return []
    kind = value.get('@type', [])
    kind = [kind] if isinstance(kind, str) else kind
    output = [value] if any(x in kind for x in ['Product', 'ProductGroup']) else []
    for key in ['@graph', 'itemListElement', 'item', 'hasVariant', 'mainEntity']:
        output += product_objects(value.get(key))
    return output


def commerce_facts(page, page_url):
    from .knowledge import canonical_url
    facts = []
    for obj in [p for data in page['jsonld'] for p in product_objects(data)][:100]:
        if not obj.get('name'):
            continue
        url = canonical_url(urljoin(page_url, str(obj.get('url') or page_url)))
        if origin(url) != origin(page_url):
            continue
        offers = obj.get('offers', [])
        offers = offers if isinstance(offers, list) else [offers]
        if offers and isinstance(offers[0], dict) and offers[0].get('offers'):
            nested = offers[0]['offers']
            offers = nested if isinstance(nested, list) else [nested]
        variants = []
        for offer in offers[:100]:
            if not isinstance(offer, dict):
                continue
            price, currency = offer.get('price', offer.get('lowPrice')), offer.get('priceCurrency')
            try:
                number = Decimal(str(price))
                if not number.is_finite() or number < 0 or number > 1000000000 or not re.fullmatch('[A-Z]{3}', str(currency)):
                    continue
                variants.append({'name': str(offer.get('name', obj['name']))[:300], 'sku': str(offer.get('sku', obj.get('sku', '')))[:120],
                                 'price_minor': int((number * 100).quantize(Decimal('1'))), 'currency': currency,
                                 'availability': 'in_stock' if str(offer.get('availability', '')).endswith('/InStock') else 'out_of_stock' if str(offer.get('availability', '')).endswith('/OutOfStock') else 'unknown'})
            except (InvalidOperation, TypeError, ValueError):
                continue
        image = obj.get('image')
        if isinstance(image, list): image = image[0] if image else None
        if isinstance(image, dict): image = image.get('url') or image.get('contentUrl')
        image = urljoin(page_url, image) if isinstance(image, str) else None
        if image and urlparse(image).scheme != 'https': image = None
        properties = obj.get('additionalProperty', [])
        properties = properties if isinstance(properties, list) else [properties]
        facts.append({'title': str(obj['name'])[:300], 'canonical_url': url,
                      'description': BeautifulSoup(str(obj.get('description', '')), 'html.parser').get_text(' ', strip=True)[:20000],
                      'image_url': image, 'variants': variants,
                      'specifications': [{'name': str(x.get('name', ''))[:200], 'value': str(x.get('value', ''))[:1000]} for x in properties[:50] if isinstance(x, dict)],
                      'sku': str(obj.get('sku', ''))[:120]})
    return facts


def save_products(db, ws, store_id, source_id, facts):
    for fact in facts:
        # Missing price is still retained in source evidence. Never invent a zero price.
        if not fact['variants']:
            continue
        row = db.scalar(select(Product).where(Product.workspace_id == ws, Product.store_id == store_id, Product.canonical_url == fact['canonical_url']))
        if row and row.provenance.get('manual_override'):
            continue
        if row is None:
            row = Product(workspace_id=ws, store_id=store_id, canonical_url=fact['canonical_url'])
            db.add(row)
        row.title, row.description, row.image_url = fact['title'], fact['description'], fact['image_url']
        variant = fact['variants'][0]
        row.price_minor, row.currency, row.availability = variant['price_minor'], variant['currency'], variant['availability']
        row.archived = False
        row.provenance = {'source': 'website-jsonld', 'source_id': source_id, 'fetched_at': now().isoformat(), **fact}


async def rendered_html(url, robot, delay):
    """Credential-free network-isolated browser; the parent alone authorizes fetches."""
    from . import isolation
    from . import knowledge as k
    fetched, last_request, budget, expanded = {}, 0.0, 0, 0
    async def fetch(request):
        nonlocal last_request, budget, expanded
        target=request.get('url','')
        if (request.get('method')!='GET' or origin(target)!=origin(url)
            or not robot.can_fetch(k.USER_AGENT,target)
            or request.get('resource_type') in {'image','media','font'}):
            return {'type':'denied'}
        if target not in fetched:
            budget+=1
            if budget>60:return {'type':'denied'}
            await asyncio.sleep(max(0,delay-(asyncio.get_running_loop().time()-last_request)))
            last_request=asyncio.get_running_loop().time()
            try:
                _,body,mime=await k.safe_fetch(target,same_origin=origin(url),
                    permit=lambda value:robot.can_fetch(k.USER_AGENT,value),redirect_delay=delay)
                expanded+=len(body)
                if len(body)>5_000_000 or expanded>40_000_000:return {'type':'denied'}
                fetched[target]=(body,mime)
            except Exception:return {'type':'denied'}
        body,mime=fetched[target]
        return {'type':'fetched','body':base64.b64encode(body).decode(),'mime':mime}
    result=await asyncio.wait_for(isolation.provider.run({'operation':'render','url':url,
        'user_agent':k.USER_AGENT,'settle_ms':RENDER_SETTLE_MILLISECONDS},fetch),RENDER_TIMEOUT_SECONDS)
    html=base64.b64decode(result['body'],validate=True)
    if len(html)>5_000_000:raise ValueError('Rendered HTML exceeds limit')
    return html
