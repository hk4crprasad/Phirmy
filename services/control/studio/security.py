from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
import hashlib
import hmac
import json
import secrets
import time
from fastapi import HTTPException, Request, Response, Depends
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from sqlalchemy import select
from .config import settings
from .db import session_scope, now, uid
from .models import AuthSession, User, Membership, APIKey, Audit
from .rate_limits import RateLimiter, limiter, cost_limits

hasher = PasswordHasher()
DUMMY_PASSWORD_HASH = hasher.hash('dummy-account-comparison-not-a-user-password')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password):
    if len(password) < 12 or len(password) > 256:
        raise HTTPException(422, "Password must contain 12–256 characters")
    return hasher.hash(password)


def password_matches(password, encoded):
    if not encoded:
        return False
    try:
        return hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def db_dependency(request: Request):
    with session_scope(write=request.method not in {"GET", "HEAD", "OPTIONS"}) as db:
        yield db


@dataclass
class Principal:
    user_id: str | None
    workspace_id: str
    role: str
    key_scopes: list[str] | None = None

    def require(self, scope):
        if self.key_scopes is not None and scope in {"developer:write", "team:write", "billing:write"}:
            raise HTTPException(403, "Use an authenticated dashboard session for keys, team and billing changes")
        if self.key_scopes is not None and scope not in self.key_scopes:
            raise HTTPException(403, "API key is not permitted to perform this action")
        action = scope.rsplit(":", 1)[-1]
        if action == "read":
            if self.role == "billing" and scope not in {"billing:read", "settings:read", "team:read", "dashboard:read"}:
                raise HTTPException(403, "Billing members do not have conversation-content access")
            return
        if self.role in {"owner", "admin"}:
            return
        allowed = {
            "builder": {"kb:write", "agents:write", "calls:write", "products:write", "widget:write"},
            "operator": {"calls:write", "campaigns:write", "inbox:write", "leads:write", "appointments:write"},
            "billing": {"billing:write"},
        }
        if scope not in allowed.get(self.role, set()):
            raise HTTPException(403, "Your workspace role cannot perform this action")


def check_origin(request):
    origin = request.headers.get("origin")
    allowed = {settings.app_origin, settings.app_origin.replace("localhost", "127.0.0.1")}
    if origin and origin not in allowed:
        raise HTTPException(403, "Request origin is not allowed")
    if settings.app_env == "production" and not origin:
        raise HTTPException(403, "Browser mutations require an Origin header")


def active_user(request, db, csrf=True):
    from .sessions import session_for_request
    session = session_for_request(request, db)
    if csrf and request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        value = request.headers.get("x-csrf-token", "")
        if not value or not hmac.compare_digest(digest(value), session.csrf_hash):
            raise HTTPException(403, "Missing or invalid CSRF token")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Session user no longer exists")
    return user


def principal(request: Request, workspace_id: str, db=Depends(db_dependency, scope="function")):
    key = request.headers.get("x-api-key")
    if key:
        record = db.scalar(select(APIKey).where(APIKey.secret_hash == digest(key), APIKey.revoked_at.is_(None), APIKey.workspace_id == workspace_id))
        if not record or (record.expires_at is not None and record.expires_at <= now()):
            raise HTTPException(401, "Invalid workspace API key")
        limiter.check("api-key:" + record.id, record.requests_per_minute, 60)
        cost_limits(request, workspace_id, "key:" + record.id)
        record.last_used_at = now()
        return Principal(None, workspace_id, "admin", record.scopes)
    user = active_user(request, db)
    from .sessions import profile_for
    from .account_policy import verification_required
    if verification_required() and profile_for(db, user.id).email_verified_at is None:
        raise HTTPException(403, {'code': 'email_verification_required', 'message': 'Verify your email to open your workspace'})
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == workspace_id))
    if not membership:
        raise HTTPException(404, "Workspace not found")
    cost_limits(request, workspace_id, "user:" + user.id)
    return Principal(user.id, workspace_id, membership.role)


def new_session(db, user, response, request=None):
    from .sessions import create_session
    return create_session(db, user, response, request)


def audit(db, actor, action, resource_id=None, data=None):
    db.add(Audit(workspace_id=actor.workspace_id, actor_id=actor.user_id, action=action, resource_id=resource_id, data=data or {}))
    if action == 'agent.published':
        from .models import Notification
        db.add(Notification(workspace_id=actor.workspace_id, kind=action, title='Your agent is published',
                            description='Test your agent, then connect it to your website.', href='/app/agents/' + str(resource_id)))


def capability(payload, ttl=120):
    import base64
    data = base64.urlsafe_b64encode(json.dumps({**payload, "exp": int(time.time()) + ttl}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.app_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return data + "." + signature


def verify_capability(token, audience):
    import base64
    try:
        data, signature = token.rsplit(".", 1)
        expected = hmac.new(settings.app_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))
        if payload["exp"] <= time.time() or payload["aud"] != audience:
            raise ValueError()
        return payload
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise HTTPException(401, "Invalid or expired session capability")
