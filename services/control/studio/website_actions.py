"""Closed website action vocabulary, scoped to this installation's indexed evidence."""
import hashlib
import json
import re
from urllib.parse import urlparse, urlunparse
from sqlalchemy import select
from .db import session_scope, as_dict
from .models import Source, Snapshot, Product, Installation
from .knowledge import canonical_url

DEFINITIONS = [
    {'type':'function', 'name':'website_search', 'description':'Search this assistant’s indexed website pages and products. Use for product/service discovery and detail questions. Returns verified facts, source URLs and product cards.',
     'parameters':{'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False}},
    {'type':'function', 'name':'website_open_page', 'description':'Navigate the visitor to an exact indexed website URL only when they explicitly ask to open, show or visit that page. Use website_search to find the URL first. No arbitrary URLs or scripts.',
     'parameters':{'type':'object','properties':{'url':{'type':'string'}},'required':['url'],'additionalProperties':False}},
    {'type':'function', 'name':'website_scroll', 'description':'Scroll the current website page to an indexed section ID when the visitor asks. No selectors or JavaScript; only returned section IDs.',
     'parameters':{'type':'object','properties':{'section_id':{'type':'string'}},'required':['section_id'],'additionalProperties':False}},
]


def clean_page_url(value, allowed_origins):
    try:
        p = urlparse(value or '')
        if p.scheme not in {'http','https'} or p.username or p.password or p.scheme + '://' + p.netloc not in allowed_origins: return None
        # Do not send private query parameters or fragments from the host page to the model.
        return canonical_url(urlunparse((p.scheme, p.netloc, p.path, '', '', '')))
    except (ValueError, TypeError): return None


def corpus(db, ws, snapshot_ids):
    snapshots = list(db.scalars(select(Snapshot).where(Snapshot.workspace_id == ws, Snapshot.id.in_(snapshot_ids), Snapshot.state == 'published')))
    source_ids = {x for s in snapshots for x in s.source_ids}
    sources = list(db.scalars(select(Source).where(Source.workspace_id == ws, Source.id.in_(source_ids))))
    origins = {urlparse(x.canonical_url).scheme + '://' + urlparse(x.canonical_url).netloc for x in sources}
    products = []
    # Structured facts live in immutable source revisions, so existing sessions do
    # not pick up a later crawl's price or stock from the mutable catalog table.
    for source in sources:
        try:
            raw = source.text_content.split('\nStructured website product evidence (untrusted data):\n',1)[1].split('\nIndexed website sections:\n',1)[0]
            facts = json.loads(raw)
        except (IndexError, ValueError): continue
        for fact in facts:
            if not fact.get('variants'): continue
            variant = fact['variants'][0]
            products.append({'id':hashlib.sha256((source.id + fact['canonical_url']).encode()).hexdigest()[:32],
                             **fact, **{key:variant[key] for key in ['price_minor','currency','availability']},
                             'customization_max_chars':None, 'source_id':source.id})
    products += [as_dict(x) for x in db.scalars(select(Product).where(Product.workspace_id == ws, Product.archived.is_(False)))
                 if not x.provenance.get('source_id') and urlparse(x.canonical_url).scheme + '://' + urlparse(x.canonical_url).netloc in origins]
    return sources, products


def ranked_products(products, query, page_url=None, history=None):
    stop = {'the','a','an','is','are','what','how','does','do','can','you','your','for','of','and','to','it','me','tell','about','product','products','price','cost','offer','have','show','this','that','one','please'}
    terms = set(re.findall(r'\w+', query.casefold())) - stop
    contextual = bool(re.search(r'\b(this|that|it|one|these|those|its)\b', query, re.I))
    if not terms and not contextual: return products[:6]
    if contextual and not terms:
        terms = set(re.findall(r'\w+', ' '.join(x.get('text','') for x in (history or [])[-4:]).casefold())) - stop
    scored = []
    for p in products:
        score = 4 * len(terms.intersection(re.findall(r'\w+', p['title'].casefold()))) + len(terms.intersection(re.findall(r'\w+', p['description'].casefold())))
        if contextual and page_url and canonical_url(p['canonical_url']) == page_url: score += 100
        if score: scored.append((score, p))
    return [p for _, p in sorted(scored, key=lambda x:x[0], reverse=True)][:6]


def sections(source):
    try: return json.loads(source.text_content.split('\nIndexed website sections:\n',1)[1])
    except (IndexError, ValueError): return []


def execute(name, args, context):
    ws = context['workspace_id']
    with session_scope() as db:
        installation = db.scalar(select(Installation).where(Installation.workspace_id == ws, Installation.id == context.get('installation_id'), Installation.enabled.is_(True)))
        if not installation or not installation.theme.get('website_actions'): return {'error':'Website actions are not enabled'}
        sources, products = corpus(db, ws, context.get('knowledge_snapshot_ids', []))
        page_url = clean_page_url(context.get('page_url'), installation.allowed_origins)
        if name == 'website_search':
            query = str(args.get('query',''))[:1000]
            matched = ranked_products(products, query, page_url, context.get('history'))
            terms = set(re.findall(r'\w+', query.casefold()))
            ranked = sorted(sources, key=lambda x:len(terms.intersection(re.findall(r'\w+', (x.title+' '+x.text_content[:5000]).casefold()))) + (100 if page_url == x.canonical_url else 0), reverse=True)
            return {'products': matched, 'pages':[{'url':s.canonical_url,'title':s.title,'text':s.text_content[:7000], 'sections':sections(s)} for s in ranked[:5]], 'untrusted_website_data':True}
        # The model cannot infer permission to navigate from crawled instructions.
        if not re.search(r'\b(open|show|take|go|navigate|visit|view|scroll|jump)\b', context.get('user_text',''), re.I):
            return {'error':'Ask the visitor before navigating or scrolling'}
        if name == 'website_open_page':
            try: url = canonical_url(str(args.get('url','')))
            except ValueError: return {'error':'Invalid website URL'}
            allowed = {s.canonical_url for s in sources} | {p['canonical_url'] for p in products}
            if url not in allowed or not clean_page_url(url, installation.allowed_origins): return {'error':'This page is outside the indexed, permitted website'}
            action = {'type':'navigate', 'url':url}
        elif name == 'website_scroll':
            source = next((s for s in sources if s.canonical_url == page_url), None)
            section_id = args.get('section_id','')
            if not source or not any(x['id'] == section_id for x in sections(source)): return {'error':'This section is not indexed on the current page'}
            action = {'type':'scroll', 'url':page_url, 'section_id':section_id}
        else: return {'error':'Website action is not supported'}
        action['id'] = hashlib.sha256((context['operation_id']+json.dumps(action,sort_keys=True)).encode()).hexdigest()[:32]
        return {'actions':[action], 'status':'requested', 'message':'The browser will attempt this permitted website action. Do not claim it has finished.'}
