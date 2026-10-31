"""Selective bootstrap keeps tenant/scope boundaries and SQL-derived statistics."""
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event
from studio import core_routes
from studio.db import engine, session_scope
from studio.main import create_app
from studio.models import Call, Workspace


@pytest.mark.parametrize('view', list(core_routes.BOOTSTRAP_VIEWS))
def test_page_bootstrap_only_returns_its_resources(sample, view):
    client, ws, base, fixture = sample
    response = client.get(base+'/bootstrap', params={'view':view})
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result['data']) == set(core_routes.BOOTSTRAP_VIEWS[view])
    assert bool(result['summary']) == (view == 'summary')
    assert not result['denied']
    assert 'secret_hash' not in response.text and 'encrypted_data' not in response.text


def test_unknown_page_rejected_and_scope_checks_still_apply(sample):
    client, ws, base, fixture = sample
    assert client.get(base+'/bootstrap?view=arbitrary-table').status_code == 422
    secret = client.post(base+'/keys', json={'name':'Knowledge only','scopes':['kb:read']}).json()['secret']
    with TestClient(create_app(start_worker=False)) as scoped:
        scoped.headers['X-API-Key'] = secret
        result = scoped.get(base+'/bootstrap?view=agents').json()
        assert set(result['data']) == {'knowledge','jobs'}
        assert set(result['denied']) == {'agents','models','tools','connections'}
        assert scoped.get(base+'/bootstrap?view=summary').json() == {'summary':{},'data':{},'denied':['summary']}


def test_light_page_does_not_execute_other_resource_queries(sample):
    client, ws, base, fixture = sample
    statements = []
    def capture(connection, cursor, statement, params, context, many): statements.append(statement.lower())
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = client.get(base+'/bootstrap?view=knowledge')
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert result.status_code == 200
    assert not any(('from '+table) in sql for sql in statements for table in ['calls','products','ledger_entries','connector_credentials','api_keys','http_tool_executions'])


def test_summary_aggregates_calls_without_hydrating_history(account, monkeypatch):
    client, ws, base = account
    fixed = datetime(2026, 10, 24, 0, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(core_routes,'now',lambda:fixed)
    with session_scope(write=True) as db:
        other = Workspace(name='Unrelated workspace');db.add(other);db.flush()
        for days, milliseconds in [(0,1900),(1,2200),(13,500),(14,700)]:
            db.add(Call(workspace_id=ws,mode='simulation',transport='browser',state='completed',created_at=fixed-timedelta(days=days),connected_ms=milliseconds))
        db.add(Call(workspace_id=other.id,mode='simulation',transport='browser',state='completed',connected_ms=999999))
    result = client.get(base+'/bootstrap?view=summary').json()['summary']
    assert result['calls'] == 4 and result['connected_seconds'] == 5
    dates = {x['date']:x['count'] for x in result['daily_calls']}
    assert len(dates)==14 and sum(dates.values())==3
    assert dates['2026-10-24']==1 and dates['2026-10-23']==1 and dates['2026-10-11']==1
