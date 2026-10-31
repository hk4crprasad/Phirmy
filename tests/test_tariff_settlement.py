import json
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import select,func
import pytest

from studio import admission,llm,metering,plans
from studio.config import settings
from studio.db import session_scope,now
from studio.domain import settle_call
from studio.models import Call,CallCostRecord,Ledger,Reservation,TariffSnapshot,WorkspaceSubscription


def configure(monkeypatch,tmp_path,*,basis='included',approved=False):
    body=plans.catalog();body.pop('content_hash',None)
    body['plans']['free']['voice_billing']=basis
    body['status']='APPROVED' if approved else 'DRAFT'
    path=tmp_path/'tariffs.json';path.write_text(json.dumps(body))
    monkeypatch.setattr(settings,'plans_config_path',str(path))
    return body,path


def publish(client,base):
    agent=client.post(base+'/agents',json={'name':'Tariff assistant'}).json()
    response=client.post(base+'/agents/'+agent['id']+'/publish',json={'expected_draft_revision':1})
    assert response.status_code==201,response.text
    return agent['id']


def test_included_live_minutes_have_nonzero_frozen_rates_without_wallet_debit(account,monkeypatch,tmp_path):
    client,ws,base=account;configure(monkeypatch,tmp_path)
    monkeypatch.setattr(llm,'live_voice_ready',lambda *args:True)
    agent=publish(client,base)
    response=client.post(base+'/voice/sessions',json={'agent_id':agent,'mode':'live'})
    assert response.status_code==201,response.text
    call_id=response.json()['call_id']
    with session_scope(write=True) as db:
        call=db.get(Call,call_id);tariff=db.get(TariffSnapshot,call.metadata_data['tariff_id'])
        assert tariff.content['mode']=='production' and tariff.content['status']=='DRAFT'
        assert tariff.content['voice_retail_minor_per_minute']>0
        assert call.metadata_data['billing_basis']=='included' and call.metadata_data['rate_minor_per_minute']>0
        call.metadata_data={**call.metadata_data,'rate_minor_per_minute':999999999}
        settle_call(db,call,1000)
        assert db.scalar(select(Reservation).where(Reservation.call_id==call_id)).state=='released'
    assert client.get(base+'/wallet').json()['balance_minor']==10000
    assert client.get(base+'/billing/usage').json()['usage']['voice_ms']==1000


def test_wallet_call_requires_approved_catalog_and_activation_before_reserving(account,monkeypatch,tmp_path):
    client,_,base=account;configure(monkeypatch,tmp_path,basis='wallet',approved=True)
    monkeypatch.setattr(llm,'live_voice_ready',lambda *args:True)
    agent=publish(client,base)
    response=client.post(base+'/voice/sessions',json={'agent_id':agent,'mode':'live'})
    assert response.status_code==409 and 'approved prices' in response.text
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Call))==0
        assert db.scalar(select(func.count()).select_from(Reservation))==0


def test_wallet_settlement_uses_original_tariff_after_plan_and_flag_changes(account,monkeypatch,tmp_path):
    client,ws,base=account;body,path=configure(monkeypatch,tmp_path,basis='wallet',approved=True)
    monkeypatch.setattr(settings,'paid_activation_enabled',True)
    monkeypatch.setattr(llm,'live_voice_ready',lambda *args:True)
    agent=publish(client,base)
    response=client.post(base+'/voice/sessions',json={'agent_id':agent,'mode':'live'})
    assert response.status_code==201,response.text
    call_id=response.json()['call_id']
    assert client.get(base+'/wallet').json()['available_minor']==0
    body['plans']['free']['voice_retail_minor_per_minute']*=10;path.write_text(json.dumps(body))
    monkeypatch.setattr(settings,'paid_activation_enabled',False)
    with session_scope(write=True) as db:
        current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==ws))
        current.catalog_id=plans.catalog_snapshot(db).id
        call=db.get(Call,call_id);call.metadata_data={**call.metadata_data,'rate_minor_per_minute':1,'billing_basis':'included'}
        settle_call(db,call,1000);settle_call(db,call,1000)
        entries=list(db.scalars(select(Ledger).where(Ledger.call_id==call_id)))
        assert len(entries)==1 and entries[0].amount_minor==-34
    assert client.get(base+'/wallet').json()['balance_minor']==9966


def test_simulation_credit_and_real_provider_cost_are_separate_pinned_terms(account,monkeypatch,tmp_path):
    client,ws,base=account;body,_=configure(monkeypatch,tmp_path)
    agent=publish(client,base)
    response=client.post(base+'/calls/outbound',headers={'Idempotency-Key':'synthetic-tariff'},
        json={'agent_id':agent,'destination':'+12025550123','budget_minor':500,'mode':'simulation'})
    assert response.status_code==202,response.text
    with session_scope(write=True) as db:
        call=db.get(Call,response.json()['id']);tariff=db.get(TariffSnapshot,call.metadata_data['tariff_id'])
        assert tariff.content['mode']=='development' and call.metadata_data['billing_basis']=='synthetic_credit'
        assert tariff.content['provider_rates']['stt_minor_per_minute']>0
        settle_call(db,call,30000)
        assert db.scalar(select(Ledger).where(Ledger.call_id==call.id)).amount_minor==-300
        cost=db.scalar(select(CallCostRecord).where(CallCostRecord.call_id==call.id,CallCostRecord.stage=='carrier'))
        assert cost.source=='synthetic' and cost.cost_micro_minor==0


def test_model_specific_rates_are_pinned_with_the_call_and_model_is_recorded(account,monkeypatch,tmp_path):
    client,ws,base=account;body,path=configure(monkeypatch,tmp_path)
    agent=publish(client,base)
    response=client.post(base+'/voice/sessions',json={'agent_id':agent,'mode':'simulation'})
    call_id=response.json()['call_id'];values={'workspace_id':ws,'call_id':call_id,'model':'gpt-5.6-sol'}
    original=body['model_rates']['gpt-5.6-sol']['llm_output_minor_per_million_tokens']
    body['model_rates']['gpt-5.6-sol']['llm_output_minor_per_million_tokens']*=10;path.write_text(json.dumps(body))
    with session_scope(write=True) as db:
        current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==ws))
        current.catalog_id=plans.catalog_snapshot(db).id
    admission.provider_hold(values,'model-pinned','openai',{'output_tokens':1})
    metering.append_cost(values,'openai','llm',{'output_tokens':1},'model-pinned','provider_usage')
    with session_scope() as db:
        cost=db.scalar(select(CallCostRecord).where(CallCostRecord.operation_key==metering.operation('model-pinned')))
        assert cost.model=='gpt-5.6-sol' and cost.cost_micro_minor==original


@pytest.mark.asyncio
async def test_production_unpriced_model_is_blocked_before_provider_io(account,monkeypatch):
    import openai
    _,ws,_=account;monkeypatch.setattr(settings,'app_env','production')
    client=Mock();monkeypatch.setattr(openai,'AsyncOpenAI',client)
    profile={**llm.environment_profile(),'workspace_id':ws,'api_key':'synthetic','model':'unmapped-model'}
    with pytest.raises(HTTPException,match='provider tariff'):
        async for _ in llm.Turn(profile,'Stable instructions',[]).stream():pass
    client.assert_not_called()


def test_wallet_liquidity_bounds_admitted_voice_duration(account,monkeypatch,tmp_path):
    from studio.models import Wallet
    client,ws,base=account;configure(monkeypatch,tmp_path,basis='wallet',approved=True)
    monkeypatch.setattr(settings,'paid_activation_enabled',True)
    monkeypatch.setattr(llm,'live_voice_ready',lambda *args:True)
    with session_scope(write=True) as db:db.scalar(select(Wallet).where(Wallet.workspace_id==ws)).balance_minor=100
    agent=publish(client,base)
    response=client.post(base+'/voice/sessions',json={'agent_id':agent,'mode':'live'})
    assert response.status_code==201,response.text
    with session_scope() as db:
        call=db.get(Call,response.json()['call_id'])
        assert call.metadata_data['admitted_max_seconds']==3
        assert call.metadata_data['retail_reservation_minor']==100


def test_read_only_tariff_quote_discloses_draft_basis_without_writes(account):
    client,_,base=account
    quote=client.get(base+'/billing/tariff')
    assert quote.status_code==200
    assert quote.json()['status']=='DRAFT' and quote.json()['voice_billing']=='included'
    assert quote.json()['voice_retail_minor_per_minute']>0 and not quote.json()['paid_activation_enabled']
    assert 'provider_rates' not in quote.json()
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(WorkspaceSubscription))==0


@pytest.mark.parametrize('original_rate',[0,600])
def test_legacy_call_keeps_original_terms_when_re_admitted_after_upgrade(account,monkeypatch,original_rate):
    client,ws,base=account;agent=publish(client,base)
    version=client.get(base+'/agents/'+agent).json()['published_version_id']
    with session_scope(write=True) as db:
        call=Call(workspace_id=ws,agent_version_id=version,mode='live',transport='browser',
                  metadata_data={'rate_minor_per_minute':original_rate})
        db.add(call);db.flush()
        catalog=plans.catalog_snapshot(db)
        legacy={'provider_rates':catalog.content['provider_rates'],'voice_retail_minor_per_minute':2000,'status':'DRAFT','mode':'production'}
        tariff=TariffSnapshot(workspace_id=ws,catalog_id=catalog.id,operation_key=metering.operation('call:'+call.id),call_id=call.id,content=legacy)
        db.add(tariff);db.add(Reservation(workspace_id=ws,call_id=call.id,amount_minor=500 if original_rate else 0));db.flush()
        from studio.domain import default_agent
        admission.admit_voice(db,call,default_agent('Legacy'))
        assert call.metadata_data['billing_basis']=='legacy' and tariff.content==legacy
        settle_call(db,call,1000)
    assert client.get(base+'/wallet').json()['balance_minor']==10000-(original_rate+59)//60


def test_wallet_admission_rejects_currency_mismatch_before_any_call_reservation(account,monkeypatch,tmp_path):
    from studio.models import Wallet,Workspace
    client,ws,base=account;configure(monkeypatch,tmp_path,basis='wallet',approved=True)
    monkeypatch.setattr(settings,'paid_activation_enabled',True)
    monkeypatch.setattr(llm,'live_voice_ready',lambda *args:True)
    agent=publish(client,base)
    with session_scope(write=True) as db:
        db.get(Workspace,ws).currency='USD'
        db.scalar(select(Wallet).where(Wallet.workspace_id==ws)).currency='USD'
    response=client.post(base+'/voice/sessions',json={'agent_id':agent,'mode':'live'})
    assert response.status_code==409 and 'currency' in response.text
    with session_scope() as db:assert db.scalar(select(func.count()).select_from(Reservation))==0
