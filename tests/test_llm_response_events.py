from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from studio import llm, media, metering
from studio.db import session_scope
from studio.llm_events import ModelIncompleteError, ToolCallStarted, ToolStreamState
from studio.models import BudgetAdmission, CallCostRecord, VoiceTimingRecord
from test_voice_latency import voice
from llm_test_helpers import completed, install_sdk, profile, usage


def tool_item(**overrides):
    return NS(**{'type':'function_call','id':'item-one','call_id':'call-one','name':'allowed_tool','arguments':'',**overrides})


def tool_events():
    item=tool_item()
    return [NS(type='response.output_item.added',item=item),
        NS(type='response.function_call_arguments.delta',item_id=item.id,delta='{"x":'),
        NS(type='response.function_call_arguments.delta',item_id=item.id,delta='1}'),
        NS(type='response.function_call_arguments.done',item_id=item.id,arguments='{"x":1}'),
        completed([NS(type='function_call',id=item.id,call_id=item.call_id,name=item.name,arguments='{"x":1}')])]


@pytest.mark.asyncio
@pytest.mark.parametrize('emit',[False,True])
async def test_tool_progress_is_optional_and_only_completed_output_authorizes_call(monkeypatch,emit):
    requests=install_sdk(monkeypatch,tool_events())
    turn=llm.Turn(profile(),'policy',[])
    turn.emit_tool_events=emit
    parts=[]
    async for part in turn.stream():
        assert turn.calls==[]
        parts.append(part)
    assert parts==([ToolCallStarted('item-one')] if emit else [])
    assert turn.calls==[{'id':'call-one','name':'allowed_tool','arguments':'{"x":1}'}]
    assert len(requests)==1


@pytest.mark.asyncio
async def test_incomplete_response_never_authorizes_partial_tools_or_replays_request(account,monkeypatch):
    _,workspace_id,_=account
    events=tool_events()[:2]+[NS(type='response.incomplete',response=NS(usage=usage(),
        incomplete_details=NS(reason='max_output_tokens')))]
    requests=install_sdk(monkeypatch,events)
    turn=llm.Turn(profile(workspace_id=workspace_id),'policy',[])
    with pytest.raises(ModelIncompleteError,match='max_output_tokens'):
        [part async for part in turn.stream()]
    assert turn.calls==[] and len(requests)==1
    with session_scope() as db:
        cost=db.scalar(select(CallCostRecord))
        assert cost.source=='provider_usage' and cost.units['input_tokens']==100
        assert db.scalar(select(BudgetAdmission)).state=='completed'


@pytest.mark.asyncio
async def test_voice_incomplete_marks_partial_history_and_failure_metrics(voice,monkeypatch):
    _,_,_,call_id,session,transport=voice
    async def partial(*args,**kwargs):
        yield 'An unfinished answer'
        raise ModelIncompleteError('max_output_tokens')
    monkeypatch.setattr(media,'answer_stream',partial)
    session.mode='simulation'
    await session.user_text('Synthetic incomplete answer',input_kind='stt_final')
    await session.task
    assert session.history[-1]['interrupted'] is True
    assert any(event.get('code')=='model_incomplete' and not event['retryable'] for event in transport.events)
    with session_scope() as db:
        assert db.scalar(select(VoiceTimingRecord).where(VoiceTimingRecord.call_id==call_id)).status=='incomplete'


@pytest.mark.parametrize('mutation', ['changed','omitted','duplicate','unfinished','oversize'])
def test_tool_stream_rejects_ambiguous_or_unbounded_completed_calls(mutation):
    state=ToolStreamState()
    item=tool_item()
    state.added(item)
    state.arguments(NS(item_id=item.id,delta='{}'))
    if mutation!='unfinished':state.arguments(NS(item_id=item.id,arguments='{}'),done=True)
    output=[NS(type='function_call',id=item.id,call_id=item.call_id,name=item.name,arguments='{}')]
    if mutation=='changed':output[0].arguments='{"changed":true}'
    elif mutation=='omitted':output=[]
    elif mutation=='duplicate':output*=2
    elif mutation=='oversize':output[0].arguments='x'*65537
    with pytest.raises(RuntimeError):state.completed(output)


@pytest.mark.asyncio
async def test_empty_text_is_not_first_token_and_reused_turn_clears_previous_calls(monkeypatch):
    events=tool_events()
    install_sdk(monkeypatch,events)
    turn=llm.Turn(profile(),'policy',[])
    assert [part async for part in turn.stream()]==[] and turn.calls
    events[:]=[NS(type='response.output_text.delta',delta=''),completed()]
    assert [part async for part in turn.stream()]==[]
    assert turn.calls==[] and turn.text=='' and turn.first_token_ms is None


def test_argument_done_must_match_stream_and_item_id_is_single_use():
    state=ToolStreamState()
    item=tool_item()
    state.added(item)
    with pytest.raises(RuntimeError):state.added(item)
    state.arguments(NS(item_id=item.id,delta='{}'))
    with pytest.raises(RuntimeError):state.arguments(NS(item_id=item.id,arguments='[]'),done=True)
    with pytest.raises(RuntimeError):state.arguments(NS(item_id='unknown',delta='x'))


@pytest.mark.asyncio
async def test_stateless_tool_continuation_replays_encrypted_reasoning_items(monkeypatch):
    reasoning=NS(type='reasoning',id='reasoning-one',encrypted_content='synthetic-encrypted-reasoning',summary=[])
    events=tool_events()
    events[-1].response.output.insert(0,reasoning)
    requests=install_sdk(monkeypatch,events)
    turn=llm.Turn(profile(),'policy',[{'role':'user','content':'Synthetic tool question'}])
    assert [part async for part in turn.stream()]==[]
    turn.append_results([{'result':'Synthetic successful tool'}])
    events[:]=[completed()]
    assert [part async for part in turn.stream()]==[]
    assert reasoning in requests[-1]['input']
    assert requests[-1]['input'][-1]['call_id']=='call-one'
