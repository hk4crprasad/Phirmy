"""Origin control proofs; no origin claim is inferred from public website content."""
import asyncio
from datetime import timedelta
import hmac
from itertools import islice
import secrets
from typing import Literal, Protocol
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import dns.resolver
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from .config import settings
from .db import now, session_scope
from .domain import owned
from .knowledge import safe_fetch, validate_public_url
from .models import OriginVerification, Workspace
from .schemas import Input
from .secrets import decrypt, encrypt
from .security import audit, db_dependency, limiter, principal

router = APIRouter(prefix='/v1/workspaces/{workspace_id}/origins')
PREFIX = 'voice-studio-verification='


def normalize_origin(value):
    try:
        if any(character in value for character in '\r\n\t'):
            raise ValueError()
        parsed = urlsplit(value)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        if parsed.path not in {'','/'} or parsed.query or parsed.fragment:
            raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii').lower()
        if any(character in host for character in " ;'\"<>\\\r\n\t*"):
            raise ValueError()
        if ':' in host:
            host = '['+host+']'
        port = parsed.port
        if port not in {None, 80 if parsed.scheme == 'http' else 443}:
            host += ':'+str(port)
        return parsed.scheme+'://'+host
    except (ValueError, UnicodeError):
        raise HTTPException(422, 'Use a complete HTTP/HTTPS origin without credentials, path or wildcard')


def platform_origins():
    origins = {normalize_origin(settings.app_origin)}
    if settings.app_env != 'production':
        origins.add(normalize_origin(settings.app_origin.replace('localhost','127.0.0.1')))
    return origins


def verified_origins(db, workspace_id):
    cache_key = ('verified-origins', workspace_id)
    if cache_key not in db.info:
        db.info[cache_key] = set(db.scalars(select(OriginVerification.origin).where(
            OriginVerification.workspace_id == workspace_id, OriginVerification.verified_at.is_not(None),
            OriginVerification.verified_until > now())))
    return db.info[cache_key] | platform_origins()


def allows_origin(installation, origin, db=None):
    if not origin or origin == 'null':
        return False
    try:
        normalized = normalize_origin(origin)
        configured = {normalize_origin(value) for value in installation.allowed_origins}
    except HTTPException:
        return False
    if normalized not in configured:
        return False
    if db is not None:
        return normalized in verified_origins(db, installation.workspace_id)
    with session_scope() as owned_db:
        return normalized in verified_origins(owned_db, installation.workspace_id)


class OwnershipProvider(Protocol):
    async def verify(self, origin: str, method: str, token: str) -> bool: ...


class PublicOwnershipProvider:
    async def verify(self, origin, method, token):
        await validate_public_url(origin)
        parsed = urlsplit(origin)
        if method == 'dns':
            answer = await asyncio.to_thread(dns.resolver.resolve,
                '_voice-studio-challenge.'+parsed.hostname, 'TXT', lifetime=3, search=False)
            expected = PREFIX+token
            return any(hmac.compare_digest(b''.join(row.strings).decode('utf-8'), expected)
                       for row in islice(answer, 20))
        path = '/.well-known/voice-studio-verification.txt' if method == 'file' else '/'
        _, body, _ = await asyncio.wait_for(safe_fetch(origin+path, max_bytes=128_000,
                          same_origin=(parsed.scheme,parsed.netloc)), timeout=5)
        if method == 'file':
            return hmac.compare_digest(body.decode('utf-8').strip(), PREFIX+token)
        document = BeautifulSoup(body, 'html.parser')
        return any(hmac.compare_digest(str(tag.get('content','')).strip(), token)
                   for tag in document.find_all('meta') if str(tag.get('name','')).lower() == 'voice-studio-verification')


provider: OwnershipProvider = PublicOwnershipProvider()


class OriginWrite(Input):
    origin: str = Field(min_length=8, max_length=512)


class VerifyOrigin(Input):
    method: Literal['dns','meta','file']


def describe(row):
    token = decrypt(row.encrypted_token)
    return {'id':row.id,'origin':row.origin,
            'state':'verified' if row.verified_at and row.verified_until and row.verified_until > now() else 'pending',
            'verified_until':row.verified_until, 'challenge_expires_at':row.expires_at,
            'dns':{'name':'_voice-studio-challenge.'+urlsplit(row.origin).hostname,'type':'TXT','value':PREFIX+token},
            'meta_tag':'<meta name="voice-studio-verification" content="'+token+'">',
            'file':{'url':row.origin+'/.well-known/voice-studio-verification.txt','content':PREFIX+token}}


@router.get('')
def origins(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('widget:read')
    return {'platform_origins':sorted(platform_origins()), 'items':[describe(row) for row in db.scalars(select(OriginVerification).where(
        OriginVerification.workspace_id == workspace_id).order_by(OriginVerification.created_at.desc()))]}


@router.post('', status_code=201)
def challenge(workspace_id: str, body: OriginWrite, request: Request,
                    actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('widget:write')
    if actor.user_id is None:
        raise HTTPException(403, 'Manage website ownership from your signed-in dashboard')
    limiter.check('origin-proof:'+workspace_id, 20, 3600)
    origin = normalize_origin(body.origin)
    if settings.app_env == 'production' and urlsplit(origin).scheme != 'https':
        raise HTTPException(422, 'Production websites require HTTPS origins')
    # No network fetch on challenge creation. Verification performs the public-IP check.
    db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    row = db.scalar(select(OriginVerification).where(OriginVerification.workspace_id == workspace_id,
                                                   OriginVerification.origin == origin))
    if row is None:
        row = OriginVerification(workspace_id=workspace_id,origin=origin,
                                  encrypted_token=encrypt(secrets.token_urlsafe(32)), expires_at=now()+timedelta(days=1))
        db.add(row);db.flush()
    elif row.expires_at <= now() and (row.verified_until is None or row.verified_until <= now()):
        row.encrypted_token, row.expires_at = encrypt(secrets.token_urlsafe(32)), now()+timedelta(days=1)
        row.verified_at, row.verified_until = None, None
    audit(db, actor, 'origin.challenge_created', row.id)
    return describe(row)


@router.post('/{verification_id}/verify')
async def verify(workspace_id: str, verification_id: str, body: VerifyOrigin, request: Request,
                 actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('widget:write')
    if actor.user_id is None:
        raise HTTPException(403, 'Verify website ownership from your signed-in dashboard')
    limiter.check('origin-check:'+workspace_id, 20, 3600)
    row = owned(db, OriginVerification, workspace_id, verification_id)
    if row.expires_at <= now():
        raise HTTPException(410, 'Create a fresh ownership challenge')
    origin, encrypted = row.origin, row.encrypted_token
    db.commit()  # Never retain a writer/ownership lock during DNS/HTTP I/O.
    try:
        valid = await provider.verify(origin, body.method, decrypt(encrypted))
    except Exception:
        raise HTTPException(503, 'Ownership proof could not be checked; retry after checking the DNS record or page')
    if valid is not True:
        raise HTTPException(400, 'Ownership proof did not match')
    # expire_on_commit=False otherwise retains stale challenge/role objects across network I/O.
    db.expire_all()
    actor = principal(request, workspace_id, db)
    actor.require('widget:write')
    row = db.scalar(select(OriginVerification).where(OriginVerification.id == verification_id,
        OriginVerification.workspace_id == workspace_id).with_for_update())
    if row is None or row.encrypted_token != encrypted or row.expires_at <= now():
        raise HTTPException(409, 'Ownership challenge changed; retry with the current challenge')
    row.verified_at, row.verified_until, row.method = now(), now()+timedelta(days=90), body.method
    db.info.pop(('verified-origins',workspace_id), None)
    audit(db, actor, 'origin.verified', row.id)
    return describe(row)


@router.delete('/{verification_id}')
def revoke(workspace_id: str, verification_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('widget:write')
    if actor.user_id is None:
        raise HTTPException(403, 'Manage website ownership from your signed-in dashboard')
    row = owned(db, OriginVerification, workspace_id, verification_id)
    row.verified_at, row.verified_until = None, None
    # Rotation makes any previous DNS/file/meta value unusable after revocation.
    row.encrypted_token, row.expires_at = encrypt(secrets.token_urlsafe(32)), now()+timedelta(days=1)
    db.info.pop(('verified-origins',workspace_id), None)
    audit(db, actor, 'origin.revoked', row.id)
    return {'state':'revoked'}
