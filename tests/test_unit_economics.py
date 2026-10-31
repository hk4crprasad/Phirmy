from studio import plans, unit_economics
from studio.config import settings
from studio.db import now, session_scope
from studio.sessions import profile_for


def test_economics_separates_channels_and_flags_unfunded_allowances():
    report = unit_economics.report()
    assert report['status'] == report['assumptions']['status'] == 'DRAFT'
    assert report['catalog_hash'] == plans.catalog()['content_hash']
    for model in report['models']:
        units = model['unit_cost_micro_minor']
        assert 0 < units['chat_turn'] < units['browser_voice_minute'] < units['phone_voice_minute']
        assert units['phone_voice_minute']-units['browser_voice_minute'] == model['voice_components_micro_minor']['carrier']
        for plan in model['plans']:
            scenarios = {row['channel']:row for row in plan['scenarios']}
            assert scenarios['chat']['allowance_cost_micro_minor'] == units['chat_turn']*plan['included']['chat_turns']
            assert scenarios['chat_and_phone_voice']['allowance_cost_micro_minor'] == (
                scenarios['chat']['allowance_cost_micro_minor']+scenarios['phone_voice']['allowance_cost_micro_minor']+
                plan['knowledge_storage_cost_micro_minor'])
            for row in scenarios.values():
                assert row['cost_exceeds_price'] == (row['allowance_cost_micro_minor'] > plan['monthly_price_minor']*1_000_000)
            assert plan['loss_flag']  # Current DRAFT numbers need revision; do not hide the exposure behind caps.


def test_economics_requires_the_same_verified_operator_browser_policy(account, monkeypatch):
    client, _, base = account
    path = '/v1/operator/billing/unit-economics'
    assert client.get(path).status_code == 403
    user = client.get('/v1/auth/me').json()['user']
    monkeypatch.setattr(settings,'billing_operator_emails',user['email'])
    assert client.get(path).status_code == 403
    with session_scope(write=True) as db:
        profile_for(db,user['id']).email_verified_at = now()
    response = client.get(path)
    assert response.status_code == 200 and response.json()['status'] == 'DRAFT'
    key = client.post(base+'/keys',json={'name':'Billing integration','scopes':['billing:read']}).json()['secret']
    assert client.get(path,headers={'X-API-Key':key}).status_code == 403


def test_economics_includes_cache_write_exposure_without_assuming_read_savings():
    report=unit_economics.report()
    body=plans.catalog()
    assumptions=report['assumptions']
    assert assumptions['cache_write_input_bps']==10000
    query=assumptions['embedding_query_tokens_per_turn']*body['provider_rates']['embedding_minor_per_million_tokens']
    for model in report['models']:
        rates=body['model_rates'][model['id']]
        assert model['unit_cost_micro_minor']['chat_turn']==(
            query+assumptions['chat_input_tokens_per_turn']*max(rates['llm_input_minor_per_million_tokens'],
                rates['llm_cache_write_30m_minor_per_million_tokens'] or 0)+
            assumptions['chat_output_tokens_per_turn']*rates['llm_output_minor_per_million_tokens'])
