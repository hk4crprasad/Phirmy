import copy
import json

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from studio import admission, metering, plans
from studio.config import settings
from studio.db import session_scope
from studio.models import BudgetAdmission, MeterEvent, TariffSnapshot, WorkspaceSubscription


def legacy_tariff(db, workspace_id, operation):
    base = metering.snapshot(db,workspace_id,'base:'+operation)
    content = copy.deepcopy(base.content)
    content['schema_version'] = 2
    for rates in [content['provider_rates'],*content.get('model_rates',{}).values()]:
        rates.pop('llm_cache_write_30m_minor_per_million_tokens',None)
        rates.pop('llm_cache_write_12h_minor_per_million_tokens',None)
    row = TariffSnapshot(workspace_id=workspace_id,catalog_id=base.catalog_id,
        operation_key=metering.operation('cost:'+operation),content=content)
    db.add(row)
    db.flush()
    return row


def test_cache_reads_and_both_write_lifetimes_are_disjoint_cost_buckets():
    rates = {'llm_input_minor_per_million_tokens':1_000_000,'llm_cached_input_minor_per_million_tokens':100_000,
        'llm_cache_write_30m_minor_per_million_tokens':1_250_000,'llm_cache_write_12h_minor_per_million_tokens':2_500_000,
        'llm_output_minor_per_million_tokens':5_000_000}
    # Official guide's 12k-input example: 1k ordinary,4k read,3k30m,4k12h.
    units = {'input_tokens':12000,'cached_input_tokens':4000,'cache_write_tokens':7000,
        'cache_write_30m_tokens':3000,'cache_write_12h_tokens':4000}
    assert metering.cost_micro(rates,'openai',units)==15_150_000_000
    with pytest.raises(ValueError,match='Inconsistent cache'):
        metering.cost_micro(rates,'openai',{**units,'cache_write_tokens':7001})


def test_cache_admission_reserves_highest_input_rate_before_provider_use(account):
    _, workspace_id, _ = account
    result = admission.provider_hold({'workspace_id':workspace_id,'model':'gpt-5.6-luna'},
        'cache-priced-bound','openai',{'input_tokens':1000,'output_tokens':10},cache_mode='responses_30m')
    assert result['cache_writes_priced']
    with session_scope() as db:
        row = db.get(BudgetAdmission,result['id'])
        assert row.reserved_micro_minor==130_000_000


def test_legacy_tariff_disables_writes_and_refuses_uncontrollable_chat_cache(account):
    _, workspace_id, _ = account
    with session_scope(write=True) as db:
        legacy = legacy_tariff(db,workspace_id,'legacy-response')
        original = copy.deepcopy(legacy.content)
        identity = legacy.id
        legacy_tariff(db,workspace_id,'legacy-chat')
    result = admission.provider_hold({'workspace_id':workspace_id,'model':'gpt-5.6-luna'},
        'legacy-response','openai',{'input_tokens':1000},cache_mode='responses_30m')
    assert not result['cache_writes_priced']
    with pytest.raises(HTTPException,match='Use Responses'):
        admission.provider_hold({'workspace_id':workspace_id,'model':'gpt-5.6-luna'},
            'legacy-chat','openai',{'input_tokens':1000},cache_mode='chat_30m')
    with session_scope() as db:
        assert db.get(TariffSnapshot,identity).content==original
        assert db.scalar(select(BudgetAdmission.id).where(BudgetAdmission.operation_key==metering.operation('legacy-chat'))) is None


def test_unpriced_reported_writes_keep_facts_hold_and_operator_pause(account):
    _, workspace_id, _ = account
    with session_scope(write=True) as db:
        legacy = legacy_tariff(db,workspace_id,'unpriced-write')
        tariff_id = legacy.id
    admission.provider_hold({'workspace_id':workspace_id,'model':'gpt-5.6-luna'},
        'unpriced-write','openai',{'input_tokens':1000},cache_mode='responses_30m')
    units = {'input_tokens':100,'cached_input_tokens':10,'cache_write_tokens':20,'cache_write_30m_tokens':20,'output_tokens':5}
    with session_scope(write=True) as db:
        record = metering.record_cost(db,workspace_id,'unpriced-write','openai','llm',units,
            tariff_id=tariff_id,model='gpt-5.6-luna',source='provider_usage')
        assert record.source=='unreported' and record.units==units
        hold = db.scalar(select(BudgetAdmission).where(BudgetAdmission.operation_key==metering.operation('unpriced-write')))
        assert hold.state=='unknown' and hold.measured_micro_minor==0
        assert db.scalar(select(WorkspaceSubscription)).operator_paused
        assert metering.usage_summary(db,workspace_id)['held_cost_micro_minor']==hold.reserved_micro_minor


def test_cache_write_meter_records_are_separate_from_total_input(account):
    _, workspace_id, _ = account
    with session_scope(write=True) as db:
        record = metering.record_cost(db,workspace_id,'cache-facts','openai','llm',
            {'input_tokens':100,'cached_input_tokens':10,'cache_write_tokens':30,'cache_write_30m_tokens':20,'cache_write_12h_tokens':10},
            source='provider_usage',model='gpt-5.6-luna')
        assert record.cost_micro_minor==11_250_000
        events = {row.resource:row.quantity for row in db.scalars(select(MeterEvent))}
        assert events['llm_input_tokens']==100
        assert events['llm_cache_write_30m_tokens']==20 and events['llm_cache_write_12h_tokens']==10


def test_new_provider_rates_do_not_reprice_retail_contract_or_existing_tariff(account,monkeypatch,tmp_path):
    _, workspace_id, _ = account
    with session_scope(write=True) as db:
        first = metering.snapshot(db,workspace_id,'before-provider-update')
        first_id, frozen = first.id, copy.deepcopy(first.content)
        subscription_catalog_id = plans.subscription(db,workspace_id).catalog_id
    updated = plans.catalog()
    updated.pop('content_hash')
    updated['provider_rates']['llm_input_minor_per_million_tokens'] *= 2
    updated['plans']['free']['voice_retail_minor_per_minute'] += 100
    path = tmp_path/'new-provider-prices.json'
    path.write_text(json.dumps(updated))
    monkeypatch.setattr(settings,'plans_config_path',str(path))
    with session_scope(write=True) as db:
        second = metering.snapshot(db,workspace_id,'after-provider-update')
        assert plans.subscription(db,workspace_id).catalog_id==subscription_catalog_id
        assert second.content['voice_retail_minor_per_minute']==frozen['voice_retail_minor_per_minute']
        assert second.content['provider_rates']['llm_input_minor_per_million_tokens']==2*frozen['provider_rates']['llm_input_minor_per_million_tokens']
        assert second.content['provider_catalog_hash']!=frozen['provider_catalog_hash']
        assert db.get(TariffSnapshot,first_id).content==frozen
