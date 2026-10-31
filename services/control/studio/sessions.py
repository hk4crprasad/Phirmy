"""Short-lived JWT cookies backed by revocable, rotating server sessions."""
from datetime import timedelta
import hashlib
import hmac
import secrets
import jwt
from fastapi import HTTPException
from sqlalchemy import select, delete
from .config import settings
from .db import now, uid
from .models import AuthSession, SessionInfo, SessionRefresh, UserProfile, OAuthIdentity
from .security import digest, check_origin

AUDIENCE = 'voice-studio-dashboard'


def profile_for(db, user_id):
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile


def public_user(db, user):
    from .account_policy import verification_required
    profile = profile_for(db, user.id)
    providers = list(db.scalars(select(OAuthIdentity.provider).where(OAuthIdentity.user_id == user.id)))
    return {'id': user.id, 'name': user.name, 'email': user.email,
            'email_verified': profile.email_verified_at is not None,
            'verification_required': verification_required() and profile.email_verified_at is None,
            'timezone': profile.timezone, 'avatar_color': profile.avatar_color,
            'notifications_enabled': profile.notifications_enabled,
            'has_password': bool(user.password_hash), 'providers': providers}


def signing_key():
    return hmac.new(settings.app_secret.encode(), b'dashboard-access-jwt-v1', hashlib.sha256).digest()


def set_cookies(response, session, refresh, csrf):
    issued = now()
    access = jwt.encode({'iss': settings.app_origin, 'aud': AUDIENCE, 'sub': session.user_id,
                         'sid': session.id, 'jti': uid(), 'iat': issued, 'nbf': issued,
                         'exp': issued + timedelta(seconds=settings.access_token_seconds)}, signing_key(), algorithm='HS256')
    options = {'secure': settings.session_secure, 'samesite': 'lax', 'path': '/'}
    remaining = max(0, int((session.expires_at - issued).total_seconds()))
    response.set_cookie('studio_session', access, httponly=True, max_age=settings.access_token_seconds, **options)
    response.set_cookie('studio_refresh', refresh, httponly=True, max_age=remaining, **options)
    response.set_cookie('studio_csrf', csrf, httponly=False, max_age=remaining, **options)


def clear_cookies(response):
    for name in ('studio_session', 'studio_refresh', 'studio_csrf'):
        response.delete_cookie(name, path='/', secure=settings.session_secure, httponly=name != 'studio_csrf', samesite='lax')


def create_session(db, user, response, request=None):
    # Account session limits also bound the number of active refresh families.
    active = list(db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)
                             .order_by(AuthSession.created_at.desc())))
    for old in active[max(0, settings.max_account_sessions - 1):]:
        db.delete(old)
    refresh, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    session = AuthSession(user_id=user.id, token_hash=digest(refresh), csrf_hash=digest(csrf),
                          expires_at=now() + timedelta(days=settings.session_days))
    db.add(session)
    db.flush()
    db.add(SessionRefresh(session_id=session.id, token_hash=digest(refresh), csrf_hash=session.csrf_hash))
    db.add(SessionInfo(session_id=session.id, user_agent=(request.headers.get('user-agent', '')[:300] if request else '')))
    set_cookies(response, session, refresh, csrf)
    return session


def session_for_request(request, db):
    token = request.cookies.get('studio_session', '')
    if token.count('.') == 2:
        try:
            claims = jwt.decode(token, signing_key(), algorithms=['HS256'], audience=AUDIENCE,
                                issuer=settings.app_origin, leeway=5,
                                options={'require': ['exp', 'iat', 'nbf', 'sub', 'sid', 'jti', 'iss', 'aud']})
        except jwt.PyJWTError:
            raise HTTPException(401, 'Your session needs to be refreshed')
        session = db.scalar(select(AuthSession).where(AuthSession.id == claims['sid'],
                            AuthSession.user_id == claims['sub'], AuthSession.expires_at > now()))
    else:
        # Existing opaque cookies can expire naturally during the rollout.
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest(token), AuthSession.expires_at > now()))
        if session and db.scalar(select(SessionRefresh.id).where(SessionRefresh.session_id == session.id).limit(1)):
            session = None
    if session is None:
        raise HTTPException(401, 'Sign in to continue')
    request.state.auth_session_id = session.id
    info = db.scalar(select(SessionInfo).where(SessionInfo.session_id == session.id))
    if info and info.last_seen_at < now() - timedelta(minutes=5):
        info.last_seen_at = now()
    return session


def refresh_session(request, response, db):
    check_origin(request)
    raw = request.cookies.get('studio_refresh', '')
    token_hash = digest(raw)
    grant = db.scalar(select(SessionRefresh).where(SessionRefresh.token_hash == token_hash).with_for_update())
    if grant is None:
        raise HTTPException(401, 'Sign in to continue')
    session = db.scalar(select(AuthSession).where(AuthSession.id == grant.session_id).with_for_update())
    if not session or session.expires_at <= now():
        raise HTTPException(401, 'Your session has expired')
    csrf = request.headers.get('x-csrf-token', '')
    if not csrf or not hmac.compare_digest(digest(csrf), grant.csrf_hash):
        raise HTTPException(403, 'Missing or invalid CSRF token')
    if grant.consumed_at is not None or not hmac.compare_digest(token_hash, session.token_hash):
        # Commit revocation before raising; exception rollback must not resurrect it.
        db.delete(session)
        db.commit()
        raise HTTPException(401, 'This refresh token was already used. Sign in again.')
    grant.consumed_at = now()
    refresh, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    session.token_hash, session.csrf_hash = digest(refresh), digest(csrf)
    db.add(SessionRefresh(session_id=session.id, token_hash=session.token_hash, csrf_hash=session.csrf_hash))
    set_cookies(response, session, refresh, csrf)
    return {'status': 'refreshed', 'expires_in': settings.access_token_seconds}
