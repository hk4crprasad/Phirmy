"""Versioned legal evidence. Signup never accepts terms for an existing account."""
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import now
from .models import LegalAcceptance, LegalPolicySnapshot
from .schemas import Input
from .security import active_user, capability, check_origin, db_dependency, limiter, verify_capability

router = APIRouter()
DOCUMENTS = {'terms', 'privacy', 'cookies', 'acceptable-use', 'dpa'}


class Section(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class Document(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    sections: list[Section] = Field(min_length=1, max_length=30)


class Policy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str = Field(min_length=1, max_length=80)
    status: Literal['DRAFT', 'APPROVED']
    notice: str = Field(min_length=1, max_length=2000)
    documents: dict[str, Document]


def current():
    try:
        body = Policy.model_validate_json(Path(settings.legal_config_path).read_text()).model_dump()
        if set(body['documents']) != DOCUMENTS:
            raise ValueError()
        if body['status'] == 'APPROVED' and ('DRAFT' in json.dumps(body) or body['version'].startswith('DRAFT')):
            raise ValueError()
    except (OSError, ValueError):
        raise HTTPException(503, 'Legal documents require configuration review') from None
    encoded = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
    return {**body, 'content_hash': hashlib.sha256(encoded).hexdigest()}


def validate(accepted, version):
    body = current()
    if accepted is not True or version != body['version']:
        raise HTTPException(422, {'code': 'legal_acceptance_required',
                                'message': 'Review and accept the current Terms and Privacy notice before creating an account.',
                                'version': body['version']})
    return body


def evidence(request, body):
    peer = request.client.host if request.client else 'unknown'
    return {'policy_hash': body['content_hash'], 'version': body['version'],
            'accepted_at': now().isoformat(),
            'ip_hash': hmac.new(settings.app_secret.encode(), ('legal:' + peer).encode(), hashlib.sha256).hexdigest()}


def record(db, user_id, proof, *, source):
    body = current()
    if proof.get('policy_hash') != body['content_hash'] or proof.get('version') != body['version']:
        raise HTTPException(422, 'Legal documents changed; review and accept the current version')
    snapshot = db.scalar(select(LegalPolicySnapshot).where(LegalPolicySnapshot.content_hash == body['content_hash']))
    if not snapshot:
        try:
            with db.begin_nested():
                snapshot = LegalPolicySnapshot(content_hash=body['content_hash'], version=body['version'],
                                               status=body['status'], content=body)
                db.add(snapshot)
                db.flush()
        except IntegrityError:
            snapshot = db.scalar(select(LegalPolicySnapshot).where(LegalPolicySnapshot.content_hash == body['content_hash']))
    row = LegalAcceptance(user_id=user_id, policy_id=snapshot.id,
                          accepted_at=datetime.fromisoformat(proof['accepted_at']),
                          ip_hash=proof['ip_hash'], source=source)
    db.add(row)
    db.flush()
    return row


@router.get('/v1/public/legal')
def documents():
    return current()


@router.get('/v1/public/legal/{content_hash}')
def historical_document(content_hash: str, db=Depends(db_dependency, scope='function')):
    if len(content_hash) != 64 or any(char not in '0123456789abcdef' for char in content_hash):
        raise HTTPException(404, 'Legal document version not found')
    row = db.scalar(select(LegalPolicySnapshot).where(LegalPolicySnapshot.content_hash == content_hash))
    if not row:
        raise HTTPException(404, 'Legal document version not found')
    return row.content


@router.get('/v1/auth/legal-acceptances')
def acceptances(request: Request, db=Depends(db_dependency, scope='function')):
    user = active_user(request, db)
    rows = db.execute(select(LegalAcceptance, LegalPolicySnapshot).join(
        LegalPolicySnapshot, LegalPolicySnapshot.id == LegalAcceptance.policy_id
    ).where(LegalAcceptance.user_id == user.id).order_by(LegalAcceptance.accepted_at.desc()))
    return {'items': [{'version': policy.version, 'status': policy.status, 'content_hash': policy.content_hash,
                       'accepted_at': acceptance.accepted_at.isoformat(), 'source': acceptance.source}
                      for acceptance, policy in rows]}


class Accept(Input):
    legal_accepted: bool = Field(strict=True)
    legal_version: str = Field(min_length=1, max_length=80)


@router.post('/v1/auth/signup-intent', status_code=202)
def signup_intent(body: Accept, request: Request, response: Response):
    check_origin(request)
    limiter.check('legal-signup-intent:' + (request.client.host if request.client else 'unknown'), 20, 300)
    policy = validate(body.legal_accepted, body.legal_version)
    response.set_cookie('studio_signup_consent', capability({'aud': 'legal_signup', **evidence(request, policy)}, 600),
                        httponly=True, secure=settings.session_secure, samesite='lax', path='/', max_age=600)
    return {'status': 'recorded_for_signup', 'version': policy['version']}


def oauth_proof(request):
    token = request.cookies.get('studio_signup_consent')
    if not token:
        return None
    try:
        return verify_capability(token, 'legal_signup')
    except HTTPException:
        return None
