"""Verified accounts, Google OIDC, profiles and personal session controls."""
from datetime import timedelta
import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy import select, delete, update
from .config import settings
from .db import now
from .models import User, AuthSession, SessionInfo, AccountToken, OAuthIdentity, OAuthAttempt, Connection, ConnectorCredential
from .schemas import Input, Signup
from .security import active_user, check_origin, db_dependency, digest, limiter, new_session
from .sessions import profile_for, public_user
from .secrets import encrypt, decrypt
from .account_routes import send_account_email

router = APIRouter(prefix='/v1/auth')
GOOGLE_TOKEN = 'https://oauth2.googleapis.com/token'
GOOGLE_CERTS = 'https://www.googleapis.com/oauth2/v3/certs'


class Verification(Input):
    token: str = Field(min_length=20, max_length=256)


class ProfileWrite(Input):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default='Asia/Kolkata', max_length=80)
    avatar_color: str = Field(default='sage', pattern='^(sage|forest|clay|sand|lavender)$')
    notifications_enabled: bool = True


def send_verification(db, user):
    for previous in db.scalars(select(AccountToken).where(AccountToken.user_id == user.id,
                               AccountToken.purpose == 'verify_email', AccountToken.consumed_at.is_(None))):
        previous.consumed_at = now()
    token = secrets.token_urlsafe(32)
    db.add(AccountToken(user_id=user.id, purpose='verify_email', token_hash=digest(token),
                        expires_at=now() + timedelta(hours=24)))
    send_account_email(user.email, 'Verify your Phirmy email', settings.app_origin + '/verify-email?token=' + token, db=db)


@router.get('/providers')
def providers():
    from .account_policy import verification_required
    return {'google': bool(settings.google_client_id and settings.google_client_secret),
            'email_verification': verification_required()}


@router.post('/verify-email')
def verify_email(body: Verification, request: Request, response: Response, db=Depends(db_dependency, scope='function')):
    check_origin(request)
    limiter.check('verify-email:' + (request.client.host if request.client else 'unknown'), 15, 3600)
    token = db.scalar(select(AccountToken).where(AccountToken.token_hash == digest(body.token),
                       AccountToken.purpose == 'verify_email', AccountToken.consumed_at.is_(None),
                       AccountToken.expires_at > now()).with_for_update())
    if not token:
        raise HTTPException(400, 'This verification link is invalid, expired or already used')
    profile_for(db, token.user_id).email_verified_at = now()
    user = db.get(User, token.user_id)
    from .account_policy import complete_registration
    complete_registration(db, user)
    for other in db.scalars(select(AccountToken).where(AccountToken.user_id == token.user_id,
                           AccountToken.purpose == 'verify_email', AccountToken.consumed_at.is_(None))):
        other.consumed_at = now()
    new_session(db, user, response, request)
    return {'message': 'Email verified. Your workspace is ready.'}


@router.post('/verification-email', status_code=202)
def resend_email(request: Request, db=Depends(db_dependency, scope='function')):
    user = active_user(request, db)
    limiter.check('verification-resend:' + user.id, 3, 3600)
    if profile_for(db, user.id).email_verified_at:
        return {'message': 'Your email is already verified.'}
    send_verification(db, user)
    return {'message': 'A new verification link has been sent.'}


@router.patch('/profile')
def update_profile(body: ProfileWrite, request: Request, db=Depends(db_dependency, scope='function')):
    user = active_user(request, db)
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, 'Choose a valid timezone')
    user.name = body.name
    profile = profile_for(db, user.id)
    profile.timezone, profile.avatar_color = body.timezone, body.avatar_color
    profile.notifications_enabled = body.notifications_enabled
    return {'user': public_user(db, user)}


@router.get('/sessions')
def sessions(request: Request, db=Depends(db_dependency, scope='function')):
    user = active_user(request, db)
    rows = list(db.scalars(select(AuthSession).where(AuthSession.user_id == user.id,
                          AuthSession.expires_at > now()).order_by(AuthSession.created_at.desc())))
    details = {x.session_id: x for x in db.scalars(select(SessionInfo).where(SessionInfo.session_id.in_([r.id for r in rows])))}
    return {'items': [{'id': r.id, 'created_at': r.created_at, 'expires_at': r.expires_at,
                       'current': r.id == request.state.auth_session_id,
                       'user_agent': details[r.id].user_agent if r.id in details else '',
                       'last_seen_at': details[r.id].last_seen_at if r.id in details else r.created_at} for r in rows]}


@router.post('/sessions/revoke-others')
def revoke_others(request: Request, db=Depends(db_dependency, scope='function')):
    user = active_user(request, db)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.id != request.state.auth_session_id))
    return {'message': 'Other devices have been signed out.'}


@router.delete('/sessions/{session_id}')
def revoke_session(session_id: str, request: Request, db=Depends(db_dependency, scope='function')):
    user = active_user(request, db)
    row = db.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user.id))
    if not row:
        raise HTTPException(404, 'Session not found')
    current = row.id == request.state.auth_session_id
    db.delete(row)
    return {'status': 'revoked', 'current': current}


@router.get('/google/start')
def google_start(request: Request, return_to: str = '/app', purpose: str = 'signin', workspace_id: str = '', db=Depends(db_dependency, scope='function')):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(503, 'Google sign-in is temporarily unavailable')
    limiter.check('google-start:' + (request.client.host if request.client else 'unknown'), 20, 300)
    if return_to not in ('/app', '/app/profile', '/app?savePreview=1'):
        raise HTTPException(422, 'Invalid return location')
    if purpose not in {'signin', 'calendar'}:
        raise HTTPException(422, 'Invalid sign-in request')
    from .legal import oauth_proof
    state, nonce, verifier = [secrets.token_urlsafe(40) for _ in range(3)]
    link_user_id = None
    if return_to == '/app/profile':
        link_user_id = active_user(request, db, csrf=False).id
    if purpose == 'calendar':
        from .security import principal
        actor = principal(request, workspace_id, db)
        actor.require('settings:write')
        link_user_id = actor.user_id
    db.add(OAuthAttempt(state_hash=digest(state), expires_at=now() + timedelta(minutes=10),
                       encrypted_data=encrypt(json.dumps({'nonce': nonce, 'verifier': verifier,
                                                          'return_to': return_to, 'link_user_id': link_user_id,
                                                          'purpose': purpose, 'workspace_id': workspace_id,
                                                          'legal_proof': oauth_proof(request)}))))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    query = {'client_id': settings.google_client_id, 'redirect_uri': settings.app_origin + '/backend/v1/auth/google/callback',
             'response_type': 'code', 'scope': 'openid email profile', 'state': state, 'nonce': nonce,
             'code_challenge': challenge, 'code_challenge_method': 'S256', 'prompt': 'select_account'}
    if purpose == 'calendar':
        query.update({'scope': query['scope'] + ' https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly',
                      'access_type': 'offline', 'prompt': 'consent'})
    response = RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(query), status_code=303)
    response.delete_cookie('studio_signup_consent', path='/')
    response.set_cookie('studio_oauth_state', state, httponly=True, secure=settings.session_secure,
                        samesite='lax', path='/', max_age=600)
    return response


async def google_claims(code, data):
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        result = await client.post(GOOGLE_TOKEN, data={'code': code, 'client_id': settings.google_client_id,
                            'client_secret': settings.google_client_secret,
                            'redirect_uri': settings.app_origin + '/backend/v1/auth/google/callback',
                            'grant_type': 'authorization_code', 'code_verifier': data['verifier']})
        result.raise_for_status()
        token_data = result.json()
        id_token = token_data['id_token']
        header = jwt.get_unverified_header(id_token)
        if header.get('alg') != 'RS256':
            raise ValueError('Unexpected identity signature')
        certificates = await client.get(GOOGLE_CERTS)
        certificates.raise_for_status()
        key_data = next(k for k in certificates.json()['keys'] if k['kid'] == header.get('kid'))
        claims = jwt.decode(id_token, jwt.PyJWK.from_dict(key_data).key, algorithms=['RS256'],
                            audience=settings.google_client_id,
                            issuer=['https://accounts.google.com', 'accounts.google.com'],
                            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'nonce', 'email']})
        if not hmac.compare_digest(claims['nonce'], data['nonce']) or claims.get('email_verified') is not True:
            raise ValueError('Unverified identity')
        if len(claims['sub']) > 255:
            raise ValueError('Invalid identity')
        claims['email'] = Signup.email_valid(claims['email'])
        if data.get('purpose') == 'calendar':
            claims['_refresh_token'] = token_data.get('refresh_token')
        return claims


@router.get('/google/callback')
async def google_callback(request: Request, code: str = '', state: str = '', db=Depends(db_dependency, scope='function')):
    def failure(reason):
        response = RedirectResponse(settings.app_origin + '/signin?auth_error=' + reason, status_code=303)
        response.delete_cookie('studio_oauth_state', path='/')
        return response
    if not state or not hmac.compare_digest(state, request.cookies.get('studio_oauth_state', '')):
        return failure('google_state')
    attempt = db.scalar(select(OAuthAttempt).where(OAuthAttempt.state_hash == digest(state)))
    if not attempt or attempt.expires_at <= now() or not code or not settings.google_client_secret:
        return failure('google_expired')
    claimed = db.execute(update(OAuthAttempt).where(OAuthAttempt.id == attempt.id, OAuthAttempt.consumed_at.is_(None))
                          .values(consumed_at=now()))
    if claimed.rowcount != 1:
        return failure('google_expired')
    data = json.loads(decrypt(attempt.encrypted_data))
    db.commit()
    try:
        claims = await google_claims(code, data)
    except Exception:
        return failure('google_unavailable')
    if data.get('purpose') == 'calendar':
        try:
            from .security import principal
            actor = principal(request, data['workspace_id'], db)
            actor.require('settings:write')
            if actor.user_id != data['link_user_id'] or not claims.get('_refresh_token'):
                return failure('google_account_mismatch')
            from .connectors import test_connection
            credentials = {'client_id': settings.google_client_id, 'client_secret': settings.google_client_secret,
                           'refresh_token': claims['_refresh_token'], 'calendar_id': 'primary'}
            await test_connection('google_calendar', credentials)
            connection = db.scalar(select(Connection).where(Connection.workspace_id == actor.workspace_id, Connection.provider == 'google_calendar'))
            if not connection:
                connection = Connection(workspace_id=actor.workspace_id, provider='google_calendar', name='Google Calendar')
                db.add(connection)
            secret = db.scalar(select(ConnectorCredential).where(ConnectorCredential.workspace_id == actor.workspace_id, ConnectorCredential.provider == 'google_calendar'))
            if not secret:
                secret = ConnectorCredential(workspace_id=actor.workspace_id, provider='google_calendar')
                db.add(secret)
            secret.encrypted_data = encrypt(json.dumps(credentials))
            connection.state, connection.scopes = 'connected', ['calendar.events', 'calendar.readonly']
        except HTTPException:
            return failure('google_unavailable')
        response = RedirectResponse(settings.app_origin + '/app/integrations?connected=google_calendar', status_code=303)
        response.delete_cookie('studio_oauth_state', path='/')
        return response
    identity = db.scalar(select(OAuthIdentity).where(OAuthIdentity.provider == 'google', OAuthIdentity.subject == claims['sub']))
    if identity:
        user = db.get(User, identity.user_id)
        if data.get('link_user_id') and identity.user_id != data['link_user_id']:
            return failure('google_account_mismatch')
    else:
        user = db.scalar(select(User).where(User.email == claims['email']))
        if user:
            # A provider email never silently links a password account.
            if data.get('link_user_id') != user.id:
                return failure('google_link_required')
            try:
                if active_user(request, db, csrf=False).id != user.id:
                    return failure('google_account_mismatch')
            except HTTPException:
                return failure('google_link_required')
            if db.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id, OAuthIdentity.provider == 'google')):
                return failure('google_account_mismatch')
        elif data.get('link_user_id'):
            return failure('google_account_mismatch')
        else:
            from .auth_routes import create_workspace
            from . import legal
            proof=data.get('legal_proof')
            if not proof or proof.get('policy_hash')!=legal.current()['content_hash']:
                return failure('legal_acceptance_required')
            name = str(claims.get('name') or claims['email'].split('@')[0])[:120]
            user = User(name=name, email=claims['email'], password_hash='')
            db.add(user)
            db.flush()
            legal.record(db,user.id,proof,source='google_signup')
            profile_for(db, user.id).email_verified_at = now()
            create_workspace(db, user, name + "'s workspace")
        db.add(OAuthIdentity(user_id=user.id, provider='google', subject=claims['sub']))
    if user.email == claims['email']:
        profile_for(db, user.id).email_verified_at = now()
    response = RedirectResponse(settings.app_origin + data['return_to'], status_code=303)
    response.delete_cookie('studio_oauth_state', path='/')
    new_session(db, user, response, request)
    return response
