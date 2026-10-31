import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from studio import identity_routes, legal
from studio.config import settings
from studio.db import engine, now, session_scope
from studio.models import LegalAcceptance, LegalPolicySnapshot, User


def body():
    return {'name':'Legal QA','email':'legal@example.test','password':'Long-Synthetic-Password',
            'workspace_name':'Legal QA','legal_accepted':True,'legal_version':legal.current()['version']}


def test_signup_requires_explicit_current_acceptance_and_records_no_user_when_missing(client):
    for changes in [{'legal_accepted':False}, {'legal_version':'outdated'}, {'legal_accepted':'true'}]:
        response=client.post('/v1/auth/signup',json={**body(),**changes})
        assert response.status_code==422
    missing=body();missing.pop('legal_accepted');missing.pop('legal_version')
    assert client.post('/v1/auth/signup',json=missing).status_code==422
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(User))==0


def test_acceptance_is_timestamped_versioned_hashed_and_not_mutated_by_repeat_signup(client):
    before=now()
    first=client.post('/v1/auth/signup',json=body())
    second=client.post('/v1/auth/signup',json={**body(),'password':'Different-Synthetic-Password'})
    assert first.status_code==second.status_code==202 and first.json()==second.json()
    with session_scope() as db:
        acceptance=db.scalar(select(LegalAcceptance));policy=db.scalar(select(LegalPolicySnapshot))
        assert db.scalar(select(func.count()).select_from(LegalAcceptance))==1
        assert before<=acceptance.accepted_at<=now() and acceptance.source=='password_signup'
        assert len(acceptance.ip_hash)==64 and 'testclient' not in acceptance.ip_hash
        assert policy.version==legal.current()['version'] and policy.status=='DRAFT'
        assert policy.content_hash==legal.current()['content_hash']
        identity=policy.content_hash
    assert client.get('/v1/public/legal/'+identity).json()['documents']['dpa']['title']=='Data Processing Addendum'
    assert client.get('/v1/public/legal/not-a-hash').status_code==404


def test_existing_account_signup_cannot_accept_new_policy_on_the_users_behalf(account,monkeypatch,tmp_path):
    client,_,_=account
    changed={key:value for key,value in legal.current().items() if key!='content_hash'}
    changed['version']='DRAFT-new-version'
    path=tmp_path/'legal.json';path.write_text(json.dumps(changed));monkeypatch.setattr(settings,'legal_config_path',str(path))
    response=client.post('/v1/auth/signup',json={**body(),'email':'qa@example.test','legal_version':changed['version']})
    assert response.status_code==202
    records=client.get('/v1/auth/legal-acceptances').json()['items']
    assert len(records)==1 and records[0]['version']!='DRAFT-new-version'
    assert 'ip_hash' not in json.dumps(records)


def test_policy_and_acceptance_evidence_are_append_only(client):
    assert client.post('/v1/auth/signup',json=body()).status_code==202
    for model in [LegalAcceptance,LegalPolicySnapshot]:
        statement=update(model).values(source='forged') if model is LegalAcceptance else update(model).values(status='APPROVED')
        for mutation in [statement,delete(model)]:
            with pytest.raises(DBAPIError):
                with engine.begin() as db:db.execute(mutation)


def test_checked_in_legal_pages_are_complete_draft_placeholders_and_approval_is_not_a_label_flip(monkeypatch,tmp_path):
    policy=legal.current()
    assert set(policy['documents'])==legal.DOCUMENTS and policy['status']=='DRAFT'
    assert 'LAWYER REVIEW' in policy['notice']
    for document in policy['documents'].values():
        assert all(section['body'].startswith('DRAFT:') for section in document['sections'])
    policy.pop('content_hash');policy['status']='APPROVED'
    path=tmp_path/'legal.json';path.write_text(json.dumps(policy));monkeypatch.setattr(settings,'legal_config_path',str(path))
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='configuration'):legal.current()


def google(client):
    result=client.get('/v1/auth/google/start',follow_redirects=False)
    assert result.status_code==303
    return parse_qs(urlparse(result.headers['location']).query)['state'][0]


def test_new_google_account_requires_origin_checked_browser_consent_bound_into_oauth_state(client,monkeypatch):
    monkeypatch.setattr(settings,'google_client_id','synthetic-client')
    monkeypatch.setattr(settings,'google_client_secret','synthetic-secret')
    monkeypatch.setattr(identity_routes,'google_claims',AsyncMock(return_value={'sub':'synthetic-sub','email':'google-legal@example.test','name':'Legal Google QA'}))
    state=google(client)
    result=client.get('/v1/auth/google/callback?state='+state+'&code=synthetic',follow_redirects=False)
    assert 'auth_error=legal_acceptance_required' in result.headers['location']
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(User))==0
    intent={'legal_accepted':True,'legal_version':legal.current()['version']}
    assert client.post('/v1/auth/signup-intent',json=intent,headers={'Origin':'https://attacker.example'}).status_code==403
    result=client.post('/v1/auth/signup-intent',json=intent)
    assert result.status_code==202 and 'HttpOnly' in result.headers['set-cookie']
    state=google(client)
    assert not client.cookies.get('studio_signup_consent')
    result=client.get('/v1/auth/google/callback?state='+state+'&code=synthetic',follow_redirects=False)
    assert result.status_code==303 and result.headers['location'].endswith('/app')
    with session_scope() as db:
        assert db.scalar(select(LegalAcceptance)).source=='google_signup'
        assert db.scalar(select(func.count()).select_from(User))==1


def test_oauth_signup_rejects_a_policy_changed_after_the_browser_accepted(client,monkeypatch,tmp_path):
    monkeypatch.setattr(settings,'google_client_id','synthetic-client')
    monkeypatch.setattr(settings,'google_client_secret','synthetic-secret')
    monkeypatch.setattr(identity_routes,'google_claims',AsyncMock(return_value={'sub':'stale-sub','email':'stale@example.test','name':'Stale QA'}))
    client.post('/v1/auth/signup-intent',json={'legal_accepted':True,'legal_version':legal.current()['version']})
    state=google(client)
    policy=legal.current();policy.pop('content_hash');policy['version']='DRAFT-changed'
    path=tmp_path/'legal.json';path.write_text(json.dumps(policy));monkeypatch.setattr(settings,'legal_config_path',str(path))
    result=client.get('/v1/auth/google/callback?state='+state+'&code=synthetic',follow_redirects=False)
    assert 'auth_error=legal_acceptance_required' in result.headers['location']
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(User))==0
