"""Real OAuth routes/HTTP serialization/DB state; synthetic provider network only."""
import asyncio
import base64
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlparse,parse_qs
from unittest.mock import AsyncMock
import httpx
import pytest
from sqlalchemy import select,func
from studio import scheduling_oauth as oauth, scheduling, scheduling_providers as remote
from studio.config import settings
from studio.db import session_scope,now
from studio.models import ConnectorCredential,Connection,OAuthAttempt,Membership,AuthSession,Appointment
from studio.secrets import decrypt,encrypt


@pytest.fixture(params=['calcom-confidential','calcom-public','calendly'])
def flow(account,monkeypatch,request):
    client,ws,base=account
    provider='calcom' if request.param.startswith('calcom') else 'calendly'
    mode='public' if request.param.endswith('public') else 'confidential'
    monkeypatch.setattr(settings,'calcom_oauth_mode',mode)
    monkeypatch.setattr(settings,provider+'_client_id','synthetic-client')
    monkeypatch.setattr(settings,provider+'_client_secret','synthetic-client-secret')
    state={'posts':[],'refreshes':0,'tokens':0,'failure':False,'scopes':None,'expires':1800,'delay':0}
    async def handler(req):
        if req.method=='POST':
            assert str(req.url)==oauth.PROVIDERS[provider]['token']
            form={k:v[0] for k,v in parse_qs(req.content.decode()).items()};state['posts'].append(form)
            assert form['client_id']=='synthetic-client'
            if provider=='calendly':assert req.headers['Authorization']=='Basic '+base64.b64encode(b'synthetic-client:synthetic-client-secret').decode()
            elif mode=='confidential':assert form['client_secret']=='synthetic-client-secret'
            else:assert 'client_secret' not in form
            if form['grant_type']=='authorization_code':
                assert form['redirect_uri']==oauth.callback_url(provider)
                if provider=='calendly' or mode=='public':assert len(form['code_verifier'])>=43
            else:
                state['refreshes']+=1
                if state['delay']:await asyncio.sleep(state['delay'])
            if state['failure']:raise httpx.ReadTimeout('Synthetic provider timeout')
            state['tokens']+=1
            return httpx.Response(200,json={'access_token':'access-'+str(state['tokens']),'refresh_token':'refresh-'+str(state['tokens']),'expires_in':state['expires'],'token_type':'bearer','scope':state['scopes'] if state['scopes'] is not None else ' '.join(oauth.PROVIDERS[provider]['scopes'])})
        assert req.headers['Authorization'].startswith('Bearer access-')
        if provider=='calcom':
            assert str(req.url)==remote.CAL+'/me';return httpx.Response(200,json={'status':'success','data':{'id':123,'username':'fixture-user'}})
        assert str(req.url)==remote.CALENDLY+'/users/me'
        return httpx.Response(200,json={'resource':{'uri':remote.CALENDLY+'/users/fixture-user','scheduling_url':'https://calendly.com/fixture-user'}})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(*a,**{**kw,'transport':httpx.MockTransport(handler)}))
    return SimpleNamespace(client=client,ws=ws,base=base,provider=provider,mode=mode,state=state)


def start(s):
    response=s.client.post(s.base+'/connections/'+s.provider+'/oauth/start',json={})
    assert response.status_code==200,response.text
    return parse_qs(urlparse(response.json()['authorization_url']).query)


def finish(s,query,**kwargs):
    return s.client.get('/v1/auth/scheduling/'+s.provider+'/callback',params={'state':query['state'][0],'code':'synthetic-code',**kwargs},follow_redirects=False)


def credentials(s):
    with session_scope() as db:
        secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==s.ws,ConnectorCredential.provider==s.provider))
        return json.loads(decrypt(secret.encrypted_data)) if secret else None


def expire(s):
    with session_scope(write=True) as db:
        secret=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==s.ws,ConnectorCredential.provider==s.provider))
        data=json.loads(decrypt(secret.encrypted_data));data['_oauth']['expires_at']=(now()-timedelta(minutes=1)).isoformat();secret.encrypted_data=encrypt(json.dumps(data))


def test_oauth_callback_binds_user_workspace_and_provider_and_encrypts_tokens(flow):
    s=flow;query=start(s)
    assert query['redirect_uri']==[oauth.callback_url(s.provider)]
    assert set(query['scope'][0].split())==set(oauth.PROVIDERS[s.provider]['scopes'])
    if s.provider=='calendly' or s.mode=='public':
        assert query['code_challenge_method']==['S256']
        with session_scope() as db:data=json.loads(decrypt(db.scalar(select(OAuthAttempt)).encrypted_data))
        assert query['code_challenge'][0]==base64.urlsafe_b64encode(hashlib.sha256(data['verifier'].encode()).digest()).rstrip(b'=').decode()
    else:assert 'code_challenge' not in query
    response=finish(s,query)
    assert response.status_code==303 and 'scheduling_oauth=connected' in response.headers['location']
    assert 'access-' not in response.text+response.headers['location']
    secret=credentials(s);assert secret['_oauth']['status']=='ready'
    assert 'api_key' in secret if s.provider=='calcom' else 'access_token' in secret
    with session_scope() as db:
        stored=db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id==s.ws))
        assert 'access-1' not in stored.encrypted_data
    assert 'scheduling_oauth=failed' in finish(s,query).headers['location']
    assert len(s.state['posts'])==1
    # Only non-secret metadata appears in ordinary workspace bootstrap.
    listing=s.client.get(s.base+'/connections').text
    assert 'access-1' not in listing and 'refresh-1' not in listing and 'client-secret' not in listing


@pytest.mark.parametrize('invalid',['cookie','provider','expired','role','session','denied','state'])
def test_oauth_failure_never_connects_or_exchanges_code(flow,invalid):
    s=flow;query=start(s)
    if invalid=='cookie':s.client.cookies.delete('studio_scheduling_'+s.provider)
    if invalid=='state':query['state']=['unrelated-state']
    if invalid=='provider':
        other='calendly' if s.provider=='calcom' else 'calcom'
        response=s.client.get('/v1/auth/scheduling/'+other+'/callback',params={'state':query['state'][0],'code':'synthetic-code'},follow_redirects=False)
    else:
        with session_scope(write=True) as db:
            if invalid=='expired':db.scalar(select(OAuthAttempt)).expires_at=now()-timedelta(seconds=1)
            if invalid=='role':db.scalar(select(Membership).where(Membership.workspace_id==s.ws)).role='builder'
            if invalid=='session':db.delete(db.scalar(select(AuthSession)))
        response=finish(s,query,**({'error':'access_denied'} if invalid=='denied' else {}))
    assert 'scheduling_oauth=failed' in response.headers['location']
    assert not credentials(s) and not s.state['posts']


@pytest.mark.asyncio
async def test_oauth_refresh_rotates_once_and_preserves_binding_under_concurrency(flow):
    s=flow;assert 'connected' in finish(s,start(s)).headers['location']
    with session_scope() as db:before=scheduling.credentials(db,s.ws,s.provider)[1]
    expire(s);s.state['delay']=.15
    await asyncio.gather(oauth.ensure_access(s.ws,s.provider),oauth.ensure_access(s.ws,s.provider))
    assert s.state['refreshes']==1 and credentials(s)['refresh_token']=='refresh-2'
    with session_scope() as db:assert scheduling.credentials(db,s.ws,s.provider)[1]==before


@pytest.mark.asyncio
async def test_ambiguous_refresh_is_not_replayed_and_requires_reauthorization(flow):
    s=flow;finish(s,start(s));expire(s);s.state['failure']=True
    for _ in range(2):
        with pytest.raises(ValueError):await oauth.ensure_access(s.ws,s.provider)
    assert s.state['refreshes']==1
    with session_scope() as db:assert db.scalar(select(Connection).where(Connection.workspace_id==s.ws,Connection.provider==s.provider)).state=='needs_reconnect'
    assert credentials(s)['_oauth']['status']=='refresh_unknown'


def test_incomplete_scope_or_failed_exchange_never_claims_connected(flow):
    s=flow;query=start(s);s.state['scopes']='users:read'
    assert 'scheduling_oauth=failed' in finish(s,query).headers['location']
    assert not credentials(s)
    s.state['failure']=True;query=start(s)
    assert 'scheduling_oauth=failed' in finish(s,query).headers['location']
    assert not credentials(s)


def test_changed_connection_during_authorization_is_preserved(flow):
    s=flow;query=start(s)
    with session_scope(write=True) as db:db.add(ConnectorCredential(workspace_id=s.ws,provider=s.provider,encrypted_data=encrypt(json.dumps({'manual':'replacement'}))))
    assert 'scheduling_oauth=failed' in finish(s,query).headers['location']
    assert credentials(s)=={'manual':'replacement'}


@pytest.mark.asyncio
async def test_expiring_oauth_token_does_not_invalidate_prepared_confirmed_booking(flow,monkeypatch):
    s=flow;finish(s,start(s))
    identifier='123' if s.provider=='calcom' else remote.CALENDLY+'/event_types/fixture-event'
    event={'id':identifier,'title':'Consultation','duration_minutes':30,'supported':True,'unavailable_reason':None,'questions':[],'phone_required':False,'locations':[]}
    monkeypatch.setattr(remote,'event',AsyncMock(return_value=event))
    begin=(now()+timedelta(days=2)).replace(microsecond=0);end=begin+timedelta(minutes=30)
    monkeypatch.setattr(remote,'slots',AsyncMock(return_value=[{'start':remote.utc(begin),'end':remote.utc(end)}]))
    assert s.client.put(s.base+'/connections/'+s.provider+'/booking-settings',json={'event_type_id':identifier}).status_code==200
    context={'workspace_id':s.ws,'conversation_id':'synthetic-conversation','operation_id':'prepare','user_text':'My name is Jane Doe and my email is jane@example.test. Please book a call.','user_history':[]}
    offer=await scheduling.agent_action('check_scheduling_availability',{'provider':s.provider,'start':begin.isoformat(),'end':end.isoformat(),'timezone':'Asia/Kolkata'},context)
    prepared=await scheduling.agent_action('prepare_scheduling_booking',{'availability_id':offer['availability_id'],'start':begin.isoformat(),'name':'Jane Doe','email':'jane@example.test'},context)
    expire(s)
    create=AsyncMock(return_value={'state':'confirmed','remote_id':'provider-confirmed','manage_url':None})
    monkeypatch.setattr(remote,'create',create)
    confirmed=await scheduling.agent_action('confirm_scheduling_booking',{'booking_id':prepared['booking_id']},{**context,'operation_id':'confirm','user_text':'Yes please book it','user_history':[context['user_text']],'last_assistant_text':prepared['confirmation_text']})
    assert confirmed['booking_confirmed'],confirmed
    assert create.await_count==1 and s.state['refreshes']==1
    assert create.await_args.args[1].get('api_key' if s.provider=='calcom' else 'access_token')=='access-2'
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.workspace_id==s.ws))==1


def test_oauth_start_requires_dashboard_role_and_csrf(flow):
    s=flow;original=s.client.headers['X-CSRF-Token'];s.client.headers['X-CSRF-Token']='invalid'
    assert s.client.post(s.base+'/connections/'+s.provider+'/oauth/start',json={}).status_code==403
    s.client.headers['X-CSRF-Token']=original
    key=s.client.post(s.base+'/keys',json={'name':'OAuth is dashboard only','scopes':['settings:write']})
    assert key.status_code==201,key.text
    secret=key.json()['secret']
    assert secret,key.json().keys()
    s.client.headers['X-API-Key']=secret
    assert s.client.post(s.base+'/connections/'+s.provider+'/oauth/start',json={}).status_code==403
    del s.client.headers['X-API-Key']
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(OAuthAttempt))==0


def test_new_login_session_cannot_complete_earlier_session_authorization(flow):
    s=flow;query=start(s)
    assert s.client.post('/v1/auth/signin',json={'email':'qa@example.test','password':'Long-Local-Test-Password'}).status_code==200
    assert 'scheduling_oauth=failed' in finish(s,query).headers['location']
    assert not credentials(s) and not s.state['posts']


def test_missing_oauth_registration_does_not_fabricate_connection(flow,monkeypatch):
    s=flow;monkeypatch.setattr(settings,s.provider+'_client_id','')
    response=s.client.post(s.base+'/connections/'+s.provider+'/oauth/start',json={})
    assert response.status_code==503 and 'not configured' in response.json()['detail']
    assert not credentials(s) and not s.state['posts']


@pytest.mark.asyncio
async def test_provider_revocation_requires_reconnect_without_replaying_request(flow,monkeypatch):
    s=flow;finish(s,start(s))
    monkeypatch.setattr(remote,'event_types',AsyncMock(side_effect=remote.ProviderError(401)))
    response=s.client.get(s.base+'/connections/'+s.provider+'/event-types')
    assert response.status_code==502
    with session_scope() as db:assert db.scalar(select(Connection).where(Connection.workspace_id==s.ws,Connection.provider==s.provider)).state=='needs_reconnect'
    assert credentials(s)['_oauth']['status']=='reconnect_required' and not s.state['refreshes']
