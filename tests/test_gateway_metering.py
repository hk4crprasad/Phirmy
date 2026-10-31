"""GPT-compatible usage recognition is independent of optional request params."""
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from studio import llm, metering
from studio.db import session_scope
from studio.llm_requests import cache_supported, cache_usage_supported
from studio.models import BudgetAdmission, CallCostRecord, WorkspaceSubscription
from llm_test_helpers import completed, install_sdk, profile, usage


def gateway(**values):
    return profile(base_url='https://gateway.example.invalid/v1', model='gpt-6-luna', **values)


def test_gateway_cache_writes_use_documented_default_without_enabling_request_extensions():
    configured = gateway()
    assert cache_usage_supported(configured) and not cache_supported(configured)
    turn = llm.Turn(configured, 'Synthetic instructions', [])
    turn.capture_usage(usage(cache_write_tokens=20), 'responses')
    assert turn.usage_complete
    assert turn.usage['cache_write_30m_tokens'] == 20 and turn.usage['cache_write_12h_tokens'] == 0
    unknown = llm.Turn(profile(model='unrecognized-model'), 'Synthetic instructions', [])
    unknown.capture_usage(usage(cache_write_tokens=20), 'responses')
    assert not unknown.usage_complete


def test_gateway_explicit_lifetime_breakdown_remains_authoritative():
    turn = llm.Turn(gateway(), 'Synthetic instructions', [])
    turn.capture_usage(usage(cache_write_tokens=20, cache_write_tokens_details=NS(ttl_30m_tokens=5, ttl_12h_tokens=15)), 'responses')
    assert turn.usage_complete and turn.usage['cache_write_12h_tokens'] == 15
    turn.capture_usage(usage(cache_write_tokens=20, cache_write_tokens_details=NS(ttl_30m_tokens=1, ttl_12h_tokens=2)), 'responses')
    assert not turn.usage_complete


@pytest.mark.asyncio
async def test_gateway_stream_settles_reported_cache_usage_without_pausing_workspace(account, monkeypatch):
    _, ws, _ = account
    requests = install_sdk(monkeypatch, [completed(reported=usage(cache_write_tokens=20))])
    turn = llm.Turn(gateway(workspace_id=ws), 'Synthetic instructions', [{'role':'user','content':'Hello'}])
    async for _ in turn.stream(): pass
    assert 'prompt_cache_options' not in requests[0]
    with session_scope() as db:
        record = db.scalar(select(CallCostRecord).where(CallCostRecord.workspace_id == ws))
        assert record.source == 'provider_usage' and record.units['cache_write_30m_tokens'] == 20
        assert record.cost_micro_minor > 0
        hold = db.scalar(select(BudgetAdmission).where(BudgetAdmission.operation_key == record.operation_key))
        assert hold.state == 'completed' and hold.measured_micro_minor <= hold.reserved_micro_minor
        assert not db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id == ws)).operator_paused
