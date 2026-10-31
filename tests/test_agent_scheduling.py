"""Call-agent booking contracts using simulated Cal.com/Calendly HTTP responses."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from studio import connectors, scheduling, scheduling_providers as remote
from studio.db import session_scope, now
from studio.models import SchedulingBooking, SchedulingAvailability, Appointment, Call, Membership


@pytest.fixture(params=['calcom', 'calendly'])
def scheduler(account, monkeypatch, request):
    client, ws, base = account
    provider = request.param
    monkeypatch.setattr(connectors, 'test_connection', AsyncMock())
    private = {'api_key': 'synthetic-cal-token', 'booking_url': 'https://cal.com/fixture/meeting'} if provider == 'calcom' else {
        'access_token': 'synthetic-calendly-token', 'booking_url': 'https://calendly.com/fixture/meeting'}
    assert client.put(base + '/connections/' + provider, json={'credentials': private}).status_code == 200
    start = (now() + timedelta(days=2)).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=30)
    event_id = '123' if provider == 'calcom' else 'https://api.calendly.com/event_types/fixture-event'
    event = {'id': 123, 'title': 'Consultation', 'lengthInMinutes': 30, 'price': 0, 'recurrence': None, 'bookingFields': []} if provider == 'calcom' else {
        'uri': event_id, 'name': 'Consultation', 'duration': 30, 'active': True, 'is_paid': False,
        'custom_questions': [], 'locations': [{'kind': 'google_conference'}], 'pooling_type': None,
        'profile': {'owner': 'https://api.calendly.com/users/fixture-user'}, 'scheduling_url': private['booking_url']}
    state = {'posts': [], 'requests': [], 'available': True, 'remote': None, 'failure': None, 'pending': False}
    def remote_event():
        return {'resource': {'uri': 'https://api.calendly.com/scheduled_events/fixture-event', 'event_type': event_id,
                            'start_time': remote.utc(start), 'end_time': remote.utc(end), 'status': 'active'}}
    async def http(method, url, **kwargs):
        state['requests'].append((method, url, deepcopy(kwargs)))
        assert kwargs['headers']['Authorization'] == 'Bearer ' + private.get('api_key', private.get('access_token'))
        if provider == 'calcom':
            if '/event-types' in url:
                assert kwargs['headers']['cal-api-version'] == '2024-06-14'
                return {'status': 'success', 'data': [event] if url.endswith('/event-types') else event}
            if url.endswith('/slots'):
                assert kwargs['headers']['cal-api-version'] == '2024-09-04'
                return {'status': 'success', 'data': {'fixture-day': [{'start': remote.utc(start), 'end': remote.utc(end)}] if state['available'] else []}}
            assert kwargs['headers']['cal-api-version'] == '2024-08-13'
        else:
            if url.endswith('/users/me'):
                return {'resource': {'uri': 'https://api.calendly.com/users/fixture-user'}}
            if '/event_types/' in url:
                return {'resource': event}
            if url.endswith('/event_types'):
                return {'collection': [event]}
            if url.endswith('/event_type_available_times'):
                return {'collection': [{'status': 'available', 'invitees_remaining': 1, 'start_time': remote.utc(start)}] if state['available'] else []}
        if method == 'POST':
            state['posts'].append(deepcopy(kwargs['json']))
            if state['failure'] in ('403', '409', '422'):
                raise remote.ProviderError(int(state['failure']))
            if state['failure'] == 'before':
                raise remote.ProviderError()
            if state['failure'] == 'cancel':
                raise asyncio.CancelledError()
            if provider == 'calcom':
                payload = kwargs['json']
                state['remote'] = {'uid': 'fixture-booking-uid', 'eventTypeId': 123, 'start': payload['start'],
                    'end': remote.utc(end), 'attendees': [{'email': payload['attendee']['email']}],
                    'status': 'pending' if state['pending'] else 'accepted', 'metadata': payload['metadata']}
            else:
                payload = kwargs['json']
                state['remote'] = {'uri': 'https://api.calendly.com/scheduled_events/fixture-event/invitees/fixture-invitee',
                    'event': 'https://api.calendly.com/scheduled_events/fixture-event', 'email': payload['invitee']['email'],
                    'status': 'active', 'tracking': payload['tracking'], 'reschedule_url': 'https://calendly.com/reschedulings/fixture'}
            if state['failure'] == 'after':
                raise remote.ProviderError()
            return {'status': 'success', 'data': state['remote']} if provider == 'calcom' else {'resource': state['remote']}
        if provider == 'calcom':
            return {'status': 'success', 'data': [state['remote']] if url.endswith('/bookings') and state['remote'] else state['remote'] or []}
        if url.endswith('/scheduled_events'):
            return {'collection': [remote_event()['resource']] if state['remote'] else []}
        if url.endswith('/invitees'):
            return {'collection': [state['remote']] if state['remote'] else []}
        if '/invitees/' in url:
            return {'resource': state['remote']}
        return remote_event()
    monkeypatch.setattr(remote, 'request', http)
    response = client.put(base + '/connections/' + provider + '/booking-settings', json={'event_type_id': event_id})
    assert response.status_code == 200, response.text
    with session_scope(write=True) as db:
        call = Call(workspace_id=ws, mode='simulation', transport='pstn', state='connected')
        db.add(call); db.flush(); call_id = call.id
    context = {'workspace_id': ws, 'call_id': call_id, 'operation_id': call_id + ':1',
        'user_text': 'My name is Jane Doe and my email is jane@example.test. Please book a consultation.',
        'user_history': [], 'last_assistant_text': ''}
    return SimpleNamespace(client=client, ws=ws, base=base, provider=provider, start=start, end=end,
                           event_id=event_id, event=event, state=state, context=context, private=private)


async def prepare(scheduler, **overrides):
    s = scheduler
    available = await scheduling.agent_action('check_scheduling_availability', {'provider': s.provider,
        'start': s.start.isoformat(), 'end': (s.start + timedelta(hours=1)).isoformat(), 'timezone': 'Asia/Kolkata'}, s.context)
    assert 'availability_id' in available, available
    result = await scheduling.agent_action('prepare_scheduling_booking', {'availability_id': available['availability_id'],
        'start': s.start.isoformat(), 'name': 'Jane Doe', 'email': 'jane@example.test', **overrides}, s.context)
    return available, result


def confirmed_context(s, proposal, **overrides):
    return {**s.context, 'operation_id': s.context['call_id'] + ':2', 'user_text': 'Yes, please book it',
            'user_history': [s.context['user_text']], 'last_assistant_text': proposal['confirmation_text'], **overrides}


@pytest.mark.asyncio
async def test_call_booking_readback_confirmation_and_provider_payload(scheduler):
    s = scheduler
    available, proposal = await prepare(s)
    assert proposal['state'] == 'prepared' and not proposal['booking_confirmed'] and not s.state['posts']
    assert 'Asia/Kolkata' in proposal['confirmation_text'] and 'jane@example.test' in proposal['confirmation_text']
    assert '30 minutes' in proposal['confirmation_text']
    args = {'booking_id': proposal['booking_id']}
    result = await scheduling.agent_action('confirm_scheduling_booking', args, confirmed_context(s, proposal))
    assert result['booking_confirmed'] and result['state'] == 'confirmed', result
    assert (await scheduling.agent_action('confirm_scheduling_booking', args, confirmed_context(s, proposal))) == result
    assert len(s.state['posts']) == 1
    payload = s.state['posts'][0]
    if s.provider == 'calcom':
        assert payload['eventTypeId'] == 123 and payload['attendee']['timeZone'] == 'Asia/Kolkata'
        assert payload['metadata']['cynerzaBookingId'] == proposal['booking_id']
    else:
        assert payload['event_type'] == s.event_id and payload['invitee']['email'] == 'jane@example.test'
        assert payload['location'] == {'kind': 'google_conference'}
        assert payload['tracking']['utm_content'] == proposal['booking_id']
    assert 'synthetic' not in json.dumps(result)
    appointments = s.client.get(s.base + '/appointments').json()['items']
    assert len(appointments) == 1 and appointments[0]['state'] == 'confirmed'
    assert s.client.post(s.base + '/appointments/' + appointments[0]['id'] + '/cancel').status_code == 409
    assert s.client.post(s.base + '/scheduling-bookings/' + proposal['booking_id'] + '/refresh', json={}).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['same_turn', 'no', 'unrelated_yes', 'changed_time', 'qualified_yes', 'expired', 'other_call'])
async def test_booking_requires_actual_uninterrupted_readback_and_later_agreement(scheduler, change):
    s = scheduler
    _, proposal = await prepare(s)
    ctx = confirmed_context(s, proposal)
    if change == 'same_turn': ctx['operation_id'] = s.context['operation_id']
    elif change == 'no': ctx['user_text'] = 'No, wait, please change the time'
    elif change == 'unrelated_yes': ctx['last_assistant_text'] = 'Would you like a support ticket?'
    elif change == 'other_call': ctx['call_id'] = 'another-call'
    elif change == 'changed_time': ctx['user_text'] = 'Yes but a different time please'
    elif change == 'qualified_yes': ctx['user_text'] = 'Yes, but at 11 AM please'
    elif change == 'expired':
        with session_scope(write=True) as db: db.get(SchedulingBooking, proposal['booking_id']).expires_at = now() - timedelta(seconds=1)
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, ctx)
    assert not result.get('booking_confirmed') and 'error' in result
    assert not s.state['posts']


@pytest.mark.asyncio
async def test_rechecks_availability_before_posting(scheduler):
    s = scheduler
    _, proposal = await prepare(s)
    s.state['available'] = False
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert 'no longer available' in result['error'] and not s.state['posts']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['before', 'after', '403', '409', '422'])
async def test_uncertain_or_rejected_submission_never_posts_twice(scheduler, failure):
    s = scheduler
    _, proposal = await prepare(s)
    s.state['failure'] = failure
    ctx = confirmed_context(s, proposal)
    args = {'booking_id': proposal['booking_id']}
    result = await scheduling.agent_action('confirm_scheduling_booking', args, ctx)
    expected = 'confirmed' if failure == 'after' else 'unknown' if failure == 'before' else 'failed'
    assert result['state'] == expected, result
    await scheduling.agent_action('confirm_scheduling_booking', args, ctx)
    await scheduling.agent_action('get_scheduling_booking', args, ctx)
    assert len(s.state['posts']) == 1
    if failure != 'after': assert not result['booking_confirmed']
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Appointment)) == (1 if failure == 'after' else 0)


@pytest.mark.asyncio
async def test_interruption_during_provider_post_preserves_uncertainty(scheduler):
    s = scheduler
    _, proposal = await prepare(s)
    s.state['failure'] = 'cancel'
    with pytest.raises(asyncio.CancelledError):
        await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    with session_scope() as db:
        assert db.get(SchedulingBooking, proposal['booking_id']).state == 'unknown'
    await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert len(s.state['posts']) == 1


@pytest.mark.asyncio
async def test_changed_or_disconnected_connection_does_not_submit(scheduler):
    s = scheduler
    _, proposal = await prepare(s)
    assert s.client.delete(s.base + '/connections/' + s.provider).status_code == 200
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert 'error' in result and not s.state['posts']


@pytest.mark.asyncio
async def test_caller_details_and_exact_offered_slot_are_required(scheduler):
    s = scheduler
    _, proposal = await prepare(s, email='invented@example.test')
    assert 'error' in proposal and not s.state['posts']
    _, proposal = await prepare(s, start=(s.start + timedelta(minutes=1)).isoformat())
    assert 'error' in proposal
    _, proposal = await prepare(s, name='Invented Person')
    assert 'error' in proposal
    _, proposal = await prepare(s, answers={'arbitrary': 'invented'})
    assert 'error' in proposal


@pytest.mark.asyncio
async def test_custom_required_answers_are_collected_and_read_back(scheduler):
    s = scheduler
    if s.provider == 'calcom':
        s.event['bookingFields'] = [{'slug': 'company', 'label': 'Company', 'type': 'text', 'required': True}]
        key = 'company'
    else:
        s.event['custom_questions'] = [{'position': 0, 'name': 'Company', 'required': True, 'enabled': True}]
        key = '0'
    _, denied = await prepare(s)
    assert 'Company' in denied['error']
    s.context['user_text'] += ' My company is Example Business.'
    _, proposal = await prepare(s, answers={key: 'Example Business'})
    assert 'Company: Example Business' in proposal['confirmation_text']
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert result['booking_confirmed']
    if s.provider == 'calcom': assert s.state['posts'][0]['bookingFieldsResponses'] == {'company': 'Example Business'}
    else: assert s.state['posts'][0]['questions_and_answers'] == [{'question': 'Company', 'position': 0, 'answer': 'Example Business'}]


@pytest.mark.asyncio
async def test_pending_host_approval_is_never_spoken_as_confirmed(scheduler):
    s = scheduler
    if s.provider != 'calcom': pytest.skip('Cal.com host-approval behavior')
    _, proposal = await prepare(s)
    s.state['pending'] = True
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert result['state'] == 'pending_approval' and not result['booking_confirmed']
    assert 'not confirmed' in scheduling.spoken_result(result)
    s.state['remote']['status'] = 'accepted'
    result = await scheduling.agent_action('get_scheduling_booking', {'booking_id': proposal['booking_id']}, s.context)
    assert result['booking_confirmed'] and len(s.state['posts']) == 1


@pytest.mark.asyncio
async def test_concurrent_confirmations_share_one_durable_post(scheduler, monkeypatch):
    s = scheduler
    _, proposal = await prepare(s)
    original = remote.request
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(method, url, **kwargs):
        if method == 'POST':
            entered.set()
            await release.wait()
        return await original(method, url, **kwargs)
    monkeypatch.setattr(remote, 'request', delayed)
    args, ctx = {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal)
    first = asyncio.create_task(scheduling.agent_action('confirm_scheduling_booking', args, ctx))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        second = await scheduling.agent_action('confirm_scheduling_booking', args, ctx)
        assert second['state'] == 'submitting' and not second['booking_confirmed']
    finally:
        release.set()
    result = await first
    assert result['booking_confirmed'] and len(s.state['posts']) == 1


@pytest.mark.asyncio
async def test_successful_post_followed_by_forbidden_verification_remains_unknown(scheduler, monkeypatch):
    s = scheduler
    if s.provider != 'calendly': pytest.skip('Calendly requires a follow-up event read')
    _, proposal = await prepare(s)
    original = remote.request
    async def forbidden_read(method, url, **kwargs):
        if method == 'GET' and url.endswith('/scheduled_events/fixture-event'):
            raise remote.ProviderError(403)
        return await original(method, url, **kwargs)
    monkeypatch.setattr(remote, 'request', forbidden_read)
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert result['state'] == 'unknown' and not result['booking_confirmed']
    assert len(s.state['posts']) == 1 and s.state['remote']


@pytest.mark.asyncio
async def test_event_changes_and_unlisted_event_arguments_are_rejected(scheduler):
    s = scheduler
    _, proposal = await prepare(s)
    if s.provider == 'calcom': s.event['title'] = 'A different meeting'
    else: s.event['name'] = 'A different meeting'
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert 'settings changed' in result['error'] and not s.state['posts']
    result = await scheduling.agent_action('check_scheduling_availability', {'provider': s.provider,
        'start': s.start.isoformat(), 'end': s.end.isoformat(), 'timezone': 'Asia/Kolkata', 'event_type_id': 'another-event'}, s.context)
    assert 'error' in result


@pytest.mark.asyncio
async def test_read_only_reconciliation_requires_exact_booking_marker(scheduler):
    s = scheduler
    _, proposal = await prepare(s)
    s.state['failure'] = 'before'
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']}, confirmed_context(s, proposal))
    assert result['state'] == 'unknown'
    if s.provider == 'calcom':
        s.state['remote'] = {'uid': 'unrelated-remote', 'eventTypeId': 123, 'start': remote.utc(s.start), 'end': remote.utc(s.end),
                             'attendees': [{'email': 'jane@example.test'}], 'status': 'accepted', 'metadata': {'cynerzaBookingId': 'another-order'}}
    else:
        s.state['remote'] = {'uri': 'https://api.calendly.com/scheduled_events/fixture-event/invitees/fixture-invitee',
            'event': 'https://api.calendly.com/scheduled_events/fixture-event', 'email': 'jane@example.test',
            'status': 'active', 'tracking': {'utm_content': 'another-order'}}
    result = await scheduling.agent_action('get_scheduling_booking', {'booking_id': proposal['booking_id']}, s.context)
    assert result['state'] == 'unknown' and not result['booking_confirmed']
    assert len(s.state['posts']) == 1


@pytest.mark.asyncio
async def test_configuration_lists_event_types_and_rejects_payment_events(scheduler):
    s = scheduler
    result = s.client.get(s.base + '/connections/' + s.provider + '/event-types')
    assert result.status_code == 200 and result.json()['items'][0]['id'] == s.event_id
    if s.provider == 'calcom': s.event['price'] = 1000
    else: s.event['is_paid'] = True
    result = s.client.put(s.base + '/connections/' + s.provider + '/booking-settings', json={'event_type_id': s.event_id})
    assert result.status_code == 422
    assert not s.state['posts']


@pytest.mark.asyncio
async def test_workspace_and_call_isolation(scheduler):
    s = scheduler
    _, proposal = await prepare(s)
    result = await scheduling.agent_action('confirm_scheduling_booking', {'booking_id': proposal['booking_id']},
        {**confirmed_context(s, proposal), 'workspace_id': 'another-workspace'})
    assert 'error' in result and not s.state['posts']
    assert s.client.get('/v1/workspaces/another-workspace/scheduling-bookings').status_code == 404
    with session_scope(write=True) as db:
        db.scalar(select(Membership).where(Membership.workspace_id == s.ws)).role = 'builder'
    assert s.client.put(s.base + '/connections/' + s.provider + '/booking-settings', json={'event_type_id': s.event_id}).status_code == 403


@pytest.mark.asyncio
async def test_actual_voice_session_speaks_readback_then_books_on_yes(scheduler, monkeypatch):
    from studio import llm, media, providers
    from studio.domain import default_agent
    s = scheduler
    plan = []
    results = {}
    class ModelTurn:
        def __init__(self, *args, **kwargs): self.calls = []
        async def stream(self):
            name, arguments = plan.pop(0)
            self.calls = [{'name': name, 'arguments': json.dumps(arguments), 'call_id': 'fixture-tool-call'}]
            if False: yield ''
        def append_results(self, values):
            results.update(values[0])
            if 'availability_id' in values[0]:
                plan.insert(0, ('prepare_scheduling_booking', {'availability_id': values[0]['availability_id'],
                    'start': s.start.isoformat(), 'name': 'Jane Doe', 'email': 'jane@example.test'}))
    monkeypatch.setattr(llm, 'resolve', lambda *args: {'api_key': 'synthetic-model-token', 'model': 'synthetic-model'})
    monkeypatch.setattr(llm, 'Turn', ModelTurn)
    monkeypatch.setattr(media, 'retrieve', AsyncMock(return_value={'answerable': False, 'passages': []}))
    socket = SimpleNamespace(send_json=AsyncMock())
    config = default_agent()
    config['tools'] = [{'name': name} for name in scheduling.TOOL_NAMES]
    session = media.VoiceSession(socket, s.ws, s.context['call_id'], config, 'simulation')
    plan.append(('check_scheduling_availability', {'provider': s.provider, 'start': s.start.isoformat(),
        'end': (s.start + timedelta(hours=1)).isoformat(), 'timezone': 'Asia/Kolkata'}))
    await session.user_text(s.context['user_text'])
    await session.task
    preview = session.history[-1]['text']
    assert preview.startswith('Please confirm:') and not s.state['posts']
    with session_scope() as db:
        booking_id = db.scalar(select(SchedulingBooking.id))
    plan.append(('confirm_scheduling_booking', {'booking_id': booking_id}))
    await session.user_text('Yes, please book it')
    await session.task
    assert session.history[-1]['text'].startswith('Your booking is confirmed'), session.history
    assert len(s.state['posts']) == 1 and not plan


def test_provider_urls_reject_user_controlled_hosts_and_redirects():
    for value in ['http://api.calendly.com/event_types/fixture-event', 'https://evil.example/event_types/fixture-event',
                  'https://api.calendly.com@evil.example/event_types/fixture-event', 'https://api.calendly.com/event_types/../users/fixture']:
        with pytest.raises(ValueError): remote.event_id('calendly', value)
    assert remote.public_url('https://calendly.com.evil.example/booking', 'calendly.com') is None


@pytest.mark.asyncio
async def test_agent_platform_selection_is_enforced_in_schema_and_runtime(scheduler):
    from studio.agent_tools import tool_definitions
    s = scheduler
    other = 'calendly' if s.provider == 'calcom' else 'calcom'
    config = {'tools': [{'name': 'check_scheduling_availability', 'scheduling_provider': s.provider}]}
    schema = tool_definitions(config)[0]['parameters']
    assert schema['properties']['provider']['enum'] == [s.provider]
    result = await scheduling.agent_action('check_scheduling_availability', {'provider': other, 'start': s.start.isoformat(),
        'end': s.end.isoformat(), 'timezone': 'Asia/Kolkata'}, {**s.context, 'scheduling_provider': s.provider})
    assert 'configured for this agent' in result['error']
    assert not s.state['posts']


@pytest.mark.asyncio
@pytest.mark.parametrize('confirm_with_voice', [False, True])
async def test_widget_uses_same_booking_engine_and_resumes_before_confirmation(scheduler, monkeypatch, confirm_with_voice):
    """Public chat uses provider availability/read-back/confirmation, never a fake booking."""
    from studio import llm, chat_routes
    from studio.config import settings
    from studio.domain import default_agent
    s=scheduler; plan=[]
    class ModelTurn:
        def __init__(self,*args,**kwargs):self.calls=[]
        async def stream(self):
            name,args=plan.pop(0)
            self.calls=[{'name':name,'arguments':json.dumps(args),'call_id':'widget-tool'}]
            if False:yield ''
        def append_results(self,values):
            if 'availability_id' in values[0]:
                plan.insert(0,('prepare_scheduling_booking',{'availability_id':values[0]['availability_id'],'start':s.start.isoformat(),'name':'Jane Doe','email':'jane@example.test'}))
    monkeypatch.setattr(llm,'resolve',lambda *args:{'api_key':'synthetic-model','model':'synthetic-model'})
    monkeypatch.setattr(chat_routes,'resolve',lambda *args:{'api_key':'synthetic-model','model':'synthetic-model'})
    monkeypatch.setattr(llm,'Turn',ModelTurn)
    config=default_agent('Booking website')
    config['tools']=[{'name':name,'schema_revision':'1','timeout_ms':10000,'side_effecting':name=='confirm_scheduling_booking',**({'scheduling_provider':s.provider} if name=='check_scheduling_availability' else {})} for name in scheduling.TOOL_NAMES]
    agent=s.client.post(s.base+'/agents',json={'name':config['name'],'config':config}).json()
    assert s.client.post(s.base+'/agents/'+agent['id']+'/publish',json={'expected_draft_revision':1}).status_code==201
    widget=s.client.post(s.base+'/installations',json={'agent_id':agent['id'],'name':'Booking','allowed_origins':[settings.app_origin]}).json()
    state=s.client.post('/v1/public/sessions',headers={'Origin':settings.app_origin},json={'visitor_email':'visitor@example.test','installation_public_id':widget['public_id'],'public_key':widget['theme']['publishable_key']}).json()
    def send(message,identity):
        response=s.client.post('/v1/public/chat',headers={'Origin':settings.app_origin,'Authorization':'Bearer '+state['session_token']},json={'session_id':state['id'],'message':message,'client_message_id':identity})
        assert response.status_code==200
        completed=[json.loads(p.split('data: ',1)[1]) for p in response.text.split('\n\n') if p.startswith('event: chat.completed')]
        assert completed,response.text
        return completed[0]
    plan.append(('check_scheduling_availability',{'provider':s.provider,'start':s.start.isoformat(),'end':(s.start+timedelta(hours=1)).isoformat(),'timezone':'Asia/Kolkata'}))
    readback=send(s.context['user_text'],'details')
    assert readback['text'].startswith('Please confirm:') and not s.state['posts']
    resumed=s.client.post('/v1/public/sessions/resume',headers={'Origin':settings.app_origin,'Authorization':'Bearer '+state['resume_token']}).json()
    assert resumed['history'][-1]['text']==readback['text']
    with session_scope() as db:booking_id=db.scalar(select(SchedulingBooking.id).where(SchedulingBooking.context_key=='conversation:'+state['id']))
    assert booking_id
    plan.append(('confirm_scheduling_booking',{'booking_id':booking_id}))
    if confirm_with_voice:
        from studio import media
        with session_scope(write=True) as db:
            active=Call(workspace_id=s.ws,agent_version_id=agent['published_version_id'] if agent.get('published_version_id') else db.get(__import__('studio.models',fromlist=['Agent']).Agent,agent['id']).published_version_id,mode='simulation',transport='browser',state='connected',metadata_data={'widget_installation_id':widget['id'],'conversation_id':state['id']})
            db.add(active);db.flush();call_id=active.id
        socket=SimpleNamespace(send_json=AsyncMock())
        voice=media.VoiceSession(socket,s.ws,call_id,config,'simulation')
        assert voice.history[-1]['text']==readback['text']
        await voice.user_text('Yes, please book it');await voice.task
        assert voice.history[-1]['text'].startswith('Your booking is confirmed') and len(s.state['posts'])==1
        resumed=s.client.post('/v1/public/sessions/resume',headers={'Origin':settings.app_origin,'Authorization':'Bearer '+state['resume_token']}).json()
        assert resumed['history'][-1]['text']==voice.history[-1]['text']
    else:
        confirmed=send('Yes, please book it','confirm')
        assert confirmed['text'].startswith('Your booking is confirmed') and len(s.state['posts'])==1
        assert send('Yes, please book it','confirm')['text']==confirmed['text'] and len(s.state['posts'])==1
