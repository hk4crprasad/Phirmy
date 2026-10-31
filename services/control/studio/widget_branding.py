"""Widget branding stays installation-scoped; published agent evidence is unchanged."""
import copy
import ipaddress
import re
from urllib.parse import urlparse,quote
from .db import as_dict

MANAGED_THEME_FIELDS={'publishable_key','logo_object_key','logo_content_type','logo_path','logo_remove'}
TONES={
    'professional':'Use a professional, clear and courteous tone. Avoid slang.',
    'friendly':'Use a friendly, approachable and helpful conversational tone.',
    'warm':'Use a warm, reassuring and patient tone without exaggerated claims.',
    'concise':'Use concise, direct replies. Prefer one or two short sentences unless more detail is needed.',
}


def validate_theme(value):
    if len(str(value))>8192:raise ValueError('Widget settings are too large')
    for key in ['accent_color','background_color','text_color','button_text_color','user_message_color','user_text_color','border_color']:
        if key in value and (not isinstance(value[key],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value[key])):
            raise ValueError('Use six-digit hex widget colors')
    choices={'position':{'left','right'},'preset':{'minimal','compact','panel','bubble','classic','glassmorphism','claymorphism','skeuomorphism','neobrutalism','bento','neumorphism','aurora','editorial','monochrome'},
             'color_mode':{'auto','light','dark'},'launcher_shape':{'pill','rounded','circle'},
             'launcher_icon':{'chat','sparkle','logo','none'},'font_family':{'system','serif','rounded'},'tone':{'agent',*TONES}}
    for key,options in choices.items():
        if key in value and (not isinstance(value[key],str) or value[key] not in options):raise ValueError('Choose a supported widget '+key.replace('_',' '))
    for key,low,high in [('corner_radius',0,28),('widget_width',280,480),('widget_height',360,720),('offset_x',8,64),('offset_y',8,64)]:
        if key in value and (isinstance(value[key],bool) or not isinstance(value[key],int) or not low<=value[key]<=high):raise ValueError('Widget '+key.replace('_',' ')+' is outside the supported range')
    for key,maximum in [('assistant_name',160),('welcome_message',500),('launcher_label',80),('input_placeholder',120),('send_button_label',40),('status_text',100),('logo_url',2048)]:
        if key in value and (not isinstance(value[key],str) or len(value[key])>maximum):raise ValueError('Widget text is too long')
    if value.get('logo_url'):
        parsed=urlparse(value['logo_url'])
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.hostname=='localhost':raise ValueError('Use a public HTTPS logo URL')
        try: address=ipaddress.ip_address(parsed.hostname)
        except ValueError:address=None
        if address and (not address.is_global or address.is_multicast):raise ValueError('Use a public HTTPS logo URL')
    for key in ['website_actions','voice_enabled','voice_input_enabled','collect_email','restrict_origins','logo_remove']:
        if key in value and not isinstance(value[key],bool):raise ValueError('Use a valid widget setting')
    return value


def public_theme(installation):
    theme=installation['theme'] if isinstance(installation,dict) else installation.theme
    public_id=installation['public_id'] if isinstance(installation,dict) else installation.public_id
    result={key:value for key,value in theme.items() if key not in {'logo_object_key','logo_content_type','logo_path','logo_remove'}}
    result.setdefault('collect_email',False)
    if theme.get('logo_object_key'):
        result['logo_path']='/v1/public/installations/'+quote(public_id,safe='')+'/logo?public_key='+quote(theme.get('publishable_key',''),safe='')
    return result


def installation_record(installation, db=None):
    from .origin_ownership import normalize_origin, verified_origins
    from .db import session_scope
    row = dict(installation) if isinstance(installation, dict) else as_dict(installation)
    def describe(owned_db):
        verified = verified_origins(owned_db, row['workspace_id'])
        allowed = [normalize_origin(origin) for origin in row['allowed_origins']]
        return {**row, 'theme':public_theme(installation),
                'verified_origins':[origin for origin in allowed if origin in verified],
                'unverified_origins':[origin for origin in allowed if origin not in verified],
                'ownership_required':any(origin not in verified for origin in allowed)}
    if db is not None:
        return describe(db)
    with session_scope() as owned_db:
        return describe(owned_db)


def widget_config(config,theme):
    result=copy.deepcopy(config)
    tone=TONES.get(theme.get('tone'))
    if tone:result['instructions']=result.get('instructions','')+'\nWidget communication style: '+tone+' Keep all factual, source, permission and confirmation rules unchanged.'
    if theme.get('welcome_message'):result['greeting']=theme['welcome_message']
    return result


def installation_allows_origin(installation, origin, db=None):
    from .origin_ownership import allows_origin
    return allows_origin(installation, origin, db)
