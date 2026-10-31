"""Tenant-owned scheduling authorization and one-shot rotating-token refresh.

This connects a provider to an existing signed-in workspace. It never creates
an application login, changes a user's identity or retries a booking POST.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode, quote
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from .config import settings
from .db import session_scope, now, uid
from .models import OAuthAttempt, Workspace, Connection, ConnectorCredential
from .security import principal, db_dependency, digest, audit, limiter
from .secrets import encrypt, decrypt
from . import scheduling_providers as remote

router = APIRouter()
PROVIDERS = {
    'calcom': {'authorize':'https://app.cal.com/auth/oauth2/authorize', 'token':'https://api.cal.com/v2/auth/oauth2/token',
               'scopes':['PROFILE_READ','EVENT_TYPE_READ','BOOKING_READ']},
    'calendly': {'authorize':'https://auth.calendly.com/oauth/authorize', 'token':'https://auth.calendly.com/oauth/token',
                 'scopes':['users:read','event_types:read','availability:read','scheduled_events:read','scheduled_events:write']},
}


def client_config(provider):
    if provider not in PROVIDERS: raise ValueError('Choose Cal.com or Calendly')
    identifier = getattr(settings, provider + '_client_id')
    secret = getattr(settings, provider + '_client_secret')
    public = provider == 'calcom' and settings.calcom_oauth_mode == 'public'
    if not identifier or (not public and not secret): raise ValueError('OAuth is not configured for this provider. Google Calendar or an API-key connection is available separately.')
    return identifier, secret, public


def configured(provider):
    try: client_config(provider); return True
    except ValueError: return False


def callback_url(provider):
    return settings.app_origin + '/backend/v1/auth/scheduling/' + provider + '/callback'


def revision(data, encrypted_data):
    oauth = data.get('_oauth')
    if not oauth: return digest(encrypted_data)
    return digest(json.dumps({'binding':oauth['binding_id'], 'subject':oauth['subject'], 'event_type_id':data.get('event_type_id')},sort_keys=True))


def existing_revision(db, ws, provider):
    secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == ws, ConnectorCredential.provider == provider))
    return revision(json.loads(decrypt(secret.encrypted_data)), secret.encrypted_data) if secret else None


async def token_request(provider, form):
    identifier, secret, public = client_config(provider)
    payload = {**form, 'client_id':identifier}
    kwargs = {'data':payload}
    if provider == 'calendly': kwargs['auth'] = httpx.BasicAuth(identifier,secret)
    elif not public: payload['client_secret'] = secret
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(PROVIDERS[provider]['token'], **kwargs)
        if response.status_code != 200: raise ValueError('Scheduling authorization was rejected. Reconnect and check app approval, credentials and scopes.')
        result = response.json()
        if not isinstance(result,dict): raise ValueError()
        return result
    except (httpx.HTTPError, ValueError) as exc:
        # Token/error bodies may contain credentials; never expose or log them.
        raise ValueError('Scheduling authorization could not be completed. Reconnect the account and check provider app settings.') from None


def token_data(provider, response, previous=None):
    access, refresh, expires = response.get('access_token'), response.get('refresh_token'), response.get('expires_in')
    if not isinstance(access,str) or not 1 <= len(access) <= 20000 or not isinstance(refresh,str) or not 1 <= len(refresh) <= 20000:
        raise ValueError('The provider did not return usable access and refresh tokens. Reconnect the account.')
    if isinstance(expires,bool) or not isinstance(expires,int) or not 60 <= expires <= 2592000 or str(response.get('token_type','bearer')).lower() != 'bearer':
        raise ValueError('The provider returned an unsupported token lifetime or type.')
    granted = response.get('scope')
    if granted is not None:
        granted = granted.replace(',',' ').split() if isinstance(granted,str) else granted
        if not isinstance(granted,list) or not all(isinstance(x,str) for x in granted) or not set(PROVIDERS[provider]['scopes']).issubset(granted):
            raise ValueError('The provider did not grant the required scheduling scopes. Update the OAuth app and reconnect.')
    oauth = {**(previous or {}), 'expires_at':(now()+timedelta(seconds=expires)).isoformat(), 'status':'ready', 'refresh_operation':None,
             'granted_scopes':granted if granted is not None else (previous or {}).get('granted_scopes'), 'requested_scopes':PROVIDERS[provider]['scopes']}
    return {('api_key' if provider == 'calcom' else 'access_token'):access, 'refresh_token':refresh, '_oauth':oauth}


async def identity(provider, credentials):
    if provider == 'calcom':
        response = await remote.request('GET',remote.CAL+'/me',headers=remote.headers(provider,credentials))
        raw = response.get('data',{})
        if response.get('status') != 'success' or not isinstance(raw.get('id'),(int,str)) or isinstance(raw.get('id'),bool): raise ValueError('The Cal.com account could not be verified.')
        subject = str(raw['id']); username = raw.get('username')
        url = 'https://cal.com/'+quote(username,safe='') if isinstance(username,str) and username else ''
    else:
        response = await remote.request('GET',remote.CALENDLY+'/users/me',headers=remote.headers(provider,credentials))
        raw = response.get('resource',{})
        subject = remote.calendly_uri(raw.get('uri'),'users')
        url = remote.public_url(raw.get('scheduling_url'),'calendly.com') or ''
    if not subject or len(subject)>200: raise ValueError('The scheduling account identity is invalid.')
    return subject, url


@router.post('/v1/workspaces/{workspace_id}/connections/{provider}/oauth/start')
def start(workspace_id: str, provider: str, request: Request, actor=Depends(principal), db=Depends(db_dependency,scope='function')):
    actor.require('settings:write')
    if not actor.user_id or actor.key_scopes is not None: raise HTTPException(403,'Connect scheduling accounts from your signed-in dashboard')
    try: identifier, secret, public = client_config(provider)
    except ValueError as exc: raise HTTPException(503,str(exc)) from None
    limiter.check('scheduling-oauth:'+actor.user_id,12,300)
    state, browser, verifier = [secrets.token_urlsafe(40) for _ in range(3)]
    data = {'kind':'scheduling','provider':provider,'workspace_id':workspace_id,'user_id':actor.user_id,
            'session_id':request.state.auth_session_id,'browser_hash':digest(browser),'verifier':verifier,
            'revision':existing_revision(db,workspace_id,provider),'client_id':identifier,'public':public}
    db.add(OAuthAttempt(state_hash=digest(state),encrypted_data=encrypt(json.dumps(data)),expires_at=now()+timedelta(minutes=10)))
    query = {'client_id':identifier,'redirect_uri':callback_url(provider),'response_type':'code','state':state,'scope':' '.join(PROVIDERS[provider]['scopes'])}
    if provider == 'calendly' or public:
        query.update(code_challenge_method='S256',code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode())
    from fastapi.responses import JSONResponse
    response = JSONResponse({'authorization_url':PROVIDERS[provider]['authorize']+'?'+urlencode(query)})
    response.set_cookie('studio_scheduling_'+provider,browser,httponly=True,secure=settings.session_secure,samesite='lax',path='/',max_age=600)
    return response


def consume_attempt(request, provider, state):
    with session_scope(write=True) as db:
        attempt = db.scalar(select(OAuthAttempt).where(OAuthAttempt.state_hash == digest(state)))
        if not attempt or attempt.consumed_at or attempt.expires_at <= now(): raise ValueError('expired')
        data = json.loads(decrypt(attempt.encrypted_data))
        if data.get('kind') != 'scheduling' or data.get('provider') != provider or not hmac.compare_digest(data['browser_hash'],digest(request.cookies.get('studio_scheduling_'+provider,''))): raise ValueError('state')
        actor = principal(request,data['workspace_id'],db); actor.require('settings:write')
        if actor.user_id != data['user_id'] or request.state.auth_session_id != data['session_id']: raise ValueError('session')
        claimed = db.execute(update(OAuthAttempt).where(OAuthAttempt.id == attempt.id,OAuthAttempt.consumed_at.is_(None)).values(consumed_at=now()))
        if claimed.rowcount != 1: raise ValueError('expired')
        return data


@router.get('/v1/auth/scheduling/{provider}/callback')
async def callback(provider: str, request: Request, state: str='', code: str='', error: str=''):
    if provider not in PROVIDERS: raise HTTPException(404,'Provider not found')
    outcome = 'failed'
    try:
        if not state or len(state)>200 or len(code)>4000: raise ValueError('state')
        data = await asyncio.to_thread(consume_attempt,request,provider,state)
        if error or not code: raise ValueError('denied')
        identifier, _, public = client_config(provider)
        if identifier != data['client_id'] or public != data['public']: raise ValueError('configuration changed')
        form = {'grant_type':'authorization_code','code':code,'redirect_uri':callback_url(provider)}
        if provider == 'calendly' or public: form['code_verifier'] = data['verifier']
        credentials = token_data(provider,await token_request(provider,form))
        subject, url = await identity(provider,credentials)
        credentials['booking_url'] = url
        credentials['_oauth'].update(binding_id=uid(),subject=subject,client_id=identifier,public=public)
        def save():
            with session_scope(write=True) as db:
                db.scalar(select(Workspace).where(Workspace.id == data['workspace_id']).with_for_update())
                actor = principal(request,data['workspace_id'],db); actor.require('settings:write')
                if actor.user_id != data['user_id'] or request.state.auth_session_id != data['session_id']: raise ValueError('session changed')
                if existing_revision(db,data['workspace_id'],provider) != data['revision']: raise ValueError('connection changed')
                connection = db.scalar(select(Connection).where(Connection.workspace_id == data['workspace_id'],Connection.provider == provider))
                if not connection:
                    connection = Connection(workspace_id=data['workspace_id'],provider=provider,name='Cal.com' if provider=='calcom' else 'Calendly');db.add(connection)
                connection.state='connected';connection.scopes=PROVIDERS[provider]['scopes']+['oauth:connected']
                secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == data['workspace_id'],ConnectorCredential.provider == provider))
                if not secret: secret = ConnectorCredential(workspace_id=data['workspace_id'],provider=provider);db.add(secret)
                secret.encrypted_data=encrypt(json.dumps(credentials))
                db.flush()
                audit(db,actor,'scheduling.oauth_connected',connection.id,{'provider':provider})
        await asyncio.to_thread(save)
        outcome = 'connected'
    except (ValueError,KeyError,TypeError,HTTPException,remote.ProviderError):
        pass
    response = RedirectResponse(settings.app_origin+'/app/integrations?'+urlencode({'scheduling_oauth':outcome,'provider':provider}),status_code=303)
    response.delete_cookie('studio_scheduling_'+provider,path='/',secure=settings.session_secure,httponly=True,samesite='lax')
    return response


def claim_refresh(ws, provider):
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id == ws).with_for_update())
        connection=db.scalar(select(Connection).where(Connection.workspace_id == ws,Connection.provider == provider))
        secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == ws,ConnectorCredential.provider == provider))
        if not connection or connection.state != 'connected' or not secret: raise ValueError('Connect the scheduling account first.')
        data=json.loads(decrypt(secret.encrypted_data));oauth=data.get('_oauth')
        if not oauth:return None
        identifier, _, public = client_config(provider)
        if identifier != oauth['client_id'] or public != oauth['public']: raise ValueError('The OAuth app configuration changed. Reconnect the account.')
        if oauth['status'] == 'refreshing':
            if remote.timestamp(oauth['refresh_started']) < now()-timedelta(seconds=90):
                oauth['status']='refresh_unknown';connection.state='needs_reconnect';secret.encrypted_data=encrypt(json.dumps(data));return {'failed':True}
            return {'busy':True}
        if oauth['status'] != 'ready': raise ValueError('Reconnect the scheduling account; the previous refresh was not confirmed.')
        if remote.timestamp(oauth['expires_at']) > now()+timedelta(seconds=90):return None
        operation=uid();oauth.update(status='refreshing',refresh_operation=operation,refresh_started=now().isoformat())
        secret.encrypted_data=encrypt(json.dumps(data))
        return {'credentials':data,'operation':operation}


def finish_refresh(ws,provider,claim,fresh):
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id == ws).with_for_update())
        secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==ws,ConnectorCredential.provider==provider))
        connection=db.scalar(select(Connection).where(Connection.workspace_id==ws,Connection.provider==provider))
        if not secret or not connection or connection.state!='connected':return False
        current=json.loads(decrypt(secret.encrypted_data))
        if current.get('_oauth',{}).get('refresh_operation') != claim['operation']:return False
        if fresh:
            current.update(fresh)
        else:
            current['_oauth']['status']='refresh_unknown';connection.state='needs_reconnect'
        secret.encrypted_data=encrypt(json.dumps(current));return bool(fresh)


async def ensure_access(ws, provider):
    if provider not in PROVIDERS:raise ValueError('Choose Cal.com or Calendly')
    for _ in range(40):
        claim=await asyncio.to_thread(claim_refresh,ws,provider)
        if not claim:return
        if claim.get('failed'):raise ValueError('Reconnect the scheduling account; token refresh could not be confirmed.')
        if claim.get('busy'):
            await asyncio.sleep(.05);continue
        try:
            fresh=token_data(provider,await token_request(provider,{'grant_type':'refresh_token','refresh_token':claim['credentials']['refresh_token']}),claim['credentials']['_oauth'])
        except asyncio.CancelledError:
            # Persisted intent survives cancellation; it must never blindly replay.
            await asyncio.shield(asyncio.to_thread(finish_refresh,ws,provider,claim,None));raise
        except Exception:
            await asyncio.to_thread(finish_refresh,ws,provider,claim,None)
            raise ValueError('Reconnect the scheduling account; token refresh could not be confirmed.') from None
        if not await asyncio.to_thread(finish_refresh,ws,provider,claim,fresh): raise ValueError('The scheduling connection changed while refreshing. Reconnect if needed.')
        return
    raise ValueError('Scheduling authorization is refreshing. Try checking availability again shortly.')


def note_auth_failure(ws,provider,used_credentials,exc):
    """A revoked access token requires reconnect; never retry a business POST."""
    if not isinstance(exc,remote.ProviderError) or exc.status != 401 or not used_credentials.get('_oauth'):return
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id==ws).with_for_update())
        secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==ws,ConnectorCredential.provider==provider))
        connection=db.scalar(select(Connection).where(Connection.workspace_id==ws,Connection.provider==provider))
        if not secret or not connection:return
        current=json.loads(decrypt(secret.encrypted_data));key='api_key' if provider=='calcom' else 'access_token'
        if current.get('_oauth',{}).get('binding_id') != used_credentials['_oauth']['binding_id'] or current.get(key) != used_credentials.get(key):return
        current['_oauth']['status']='reconnect_required';connection.state='needs_reconnect'
        secret.encrypted_data=encrypt(json.dumps(current))
