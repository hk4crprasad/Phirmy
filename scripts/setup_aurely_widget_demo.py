"""Create a dedicated Aurely HTML-demo installation from existing published knowledge.

Run with the explicit provider-enabled local DB helper. Uses the app's existing
installation handler; never reads/prints private credentials or re-crawls Aurely.
"""
from pathlib import Path
import html
import json
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))
from sqlalchemy import select
from studio.db import session_scope,engine
from studio.models import WebsiteAssistant,KnowledgeBase,Agent,Installation
from studio.operations_routes import installation_create
from studio.schemas import InstallationWrite
from studio.security import Principal

ROOT=Path(__file__).resolve().parents[1]
WS='632f4e20-9134-4efa-8842-5e60144f2e8e'
NAME='Aurely demo HTML widget'
ORIGIN='http://127.0.0.1:3200'
APP='http://127.0.0.1:3100'

def configure():
    if engine.dialect.name!='sqlite':raise RuntimeError('Use the explicit local provider-enabled DB for this demo')
    with session_scope(write=True) as db:
        row=db.scalar(select(WebsiteAssistant).where(WebsiteAssistant.workspace_id==WS))
        if not row:raise RuntimeError('Complete the native Aurely crawl first')
        agent=db.get(Agent,row.agent_id);kb=db.get(KnowledgeBase,row.kb_id)
        if not agent.published_version_id or not kb.active_snapshot_id:raise RuntimeError('Aurely knowledge must be published first')
        installation=db.scalar(select(Installation).where(Installation.workspace_id==WS,Installation.name==NAME))
        if not installation:
            body=InstallationWrite(agent_id=agent.id,name=NAME,allowed_origins=[ORIGIN,'http://localhost:3200'],theme={
                'assistant_name':'Aurely guide','launcher_label':'Ask Aurely','welcome_message':'Hello! I’m your Aurely guide. Ask me about a piece, its price, materials, delivery or returns.',
                'preset':'minimal','position':'right','accent_color':'#66543c','background_color':'#fffdf9','website_actions':True})
            result=installation_create(WS,body,actor=Principal(None,WS,'owner'),db=db)
            installation=db.get(Installation,result['id'])
        if not installation.enabled or ORIGIN not in installation.allowed_origins:raise RuntimeError('Existing demo installation is disabled or has a different origin; inspect it before changing it')
        snippet='<script defer src="'+APP+'/widget.js" data-widget-id="'+html.escape(installation.public_id,quote=True)+'" data-public-key="'+html.escape(installation.theme['publishable_key'],quote=True)+'"></script>'
        public={'app_origin':APP,'demo_origin':ORIGIN,'installation_public_id':installation.public_id,'public_key':installation.theme['publishable_key'],'workspace_id':WS,'agent_id':agent.id}
    target=ROOT/'examples/aurely-widget-demo/index.html'
    text=target.read_text()
    marker='<!-- AURELY_WIDGET_EMBED -->'
    if marker not in text:raise RuntimeError('Demo embed marker is missing')
    text=re.sub(r'\n[ \t]*<script\b[^>]*\bsrc="[^"]+/widget\.js"[^>]*>\s*</script>', '',text, flags=re.S)
    target.write_text(text.replace(marker,marker+'\n  '+snippet))
    # These are deliberately public browser fields; no dashboard/session/provider key.
    (target.parent/'widget-config.json').write_text(json.dumps(public,indent=2)+'\n')
    print('Aurely demo installation prepared; published knowledge reused. No recrawl.')

if __name__=='__main__':configure()
