"""Synthetic API fixture for verify_scheduling_browser.py; never a deployment entrypoint.

All scheduling and model requests are replaced in this process. The ordinary
app, database, auth, agent publication and WebSocket conversation path run.
"""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import AsyncMock
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))
from studio import connectors, scheduling_providers as remote, llm, scheduling_oauth
from studio.db import now, session_scope
from studio.models import SchedulingBooking
from studio.main import create_app

START = (now() + timedelta(days=2)).replace(hour=13, minute=0, second=0, microsecond=0)
END = START + timedelta(minutes=30)
CALENDLY_EVENT = 'https://api.calendly.com/event_types/browser-event'
records = {}
posts = []
connectors.test_connection = AsyncMock()


async def provider(method, url, **kwargs):
    calcom = urlparse(url).hostname == 'api.cal.com'
    assert calcom or urlparse(url).hostname == 'api.calendly.com'
    event = {'id': 123, 'title': 'Cal.com consultation', 'lengthInMinutes': 30, 'price': 0,
             'recurrence': None, 'bookingFields': []} if calcom else {
        'uri': CALENDLY_EVENT, 'name': 'Calendly consultation', 'duration': 30, 'active': True, 'is_paid': False,
        'custom_questions': [], 'locations': [{'kind': 'google_conference'}], 'pooling_type': None,
        'profile': {'owner': 'https://api.calendly.com/users/browser-owner'}}
    if url.endswith('/me') and calcom:
        return {'status':'success','data':{'id':123,'username':'fixture'}}
    if url.endswith('/users/me'):
        return {'resource': {'uri': 'https://api.calendly.com/users/browser-owner','scheduling_url':'https://calendly.com/fixture/meeting'}}
    if '/event-types' in url or '/event_types' in url:
        listing = url.endswith('/event-types') or url.endswith('/event_types')
        return {'status': 'success', 'data': [event] if listing else event} if calcom else ({'collection': [event]} if listing else {'resource': event})
    if url.endswith('/slots'):
        return {'status': 'success', 'data': {'date': [{'start': remote.utc(START), 'end': remote.utc(END)}]}}
    if url.endswith('/event_type_available_times'):
        return {'collection': [{'start_time': remote.utc(START), 'status': 'available', 'invitees_remaining': 1}]}
    if method == 'POST':
        data = kwargs['json']; posts.append('calcom' if calcom else 'calendly')
        key = data['metadata']['cynerzaBookingId'] if calcom else data['tracking']['utm_content']
        row = {'uid': key, 'eventTypeId': 123, 'start': data['start'], 'end': remote.utc(END), 'status': 'accepted',
               'attendees': [{'email': data['attendee']['email']}], 'metadata': data['metadata']} if calcom else {
            'uri': 'https://api.calendly.com/scheduled_events/' + key + '/invitees/' + key,
            'event': 'https://api.calendly.com/scheduled_events/' + key, 'email': data['invitee']['email'],
            'status': 'active', 'tracking': data['tracking'], 'reschedule_url': 'https://calendly.com/reschedulings/' + key}
        records[key] = row
        return {'status': 'success', 'data': row} if calcom else {'resource': row}
    key = url.rsplit('/', 1)[-1]
    if calcom and key in records:
        return {'status': 'success', 'data': records[key]}
    if not calcom and key in records:
        return {'resource': {'uri': url, 'event_type': CALENDLY_EVENT, 'start_time': remote.utc(START),
                             'end_time': remote.utc(END), 'status': 'active'}}
    raise RuntimeError('Unrecognized synthetic provider request')


class ModelTurn:
    def __init__(self, profile, instructions, messages, **kwargs):
        self.messages, self.calls = messages, []

    async def stream(self):
        last = self.messages[-1]
        if last.get('role') == 'tool':
            offer = json.loads(last['content'])
            name = 'prepare_scheduling_booking'
            args = {'availability_id': offer['availability_id'], 'start': remote.utc(START),
                    'name': 'Jane Doe', 'email': 'jane@example.test'}
        elif last['content'].lower().startswith('yes'):
            with session_scope() as db:
                row = db.scalar(select(SchedulingBooking).where(SchedulingBooking.state == 'prepared').order_by(SchedulingBooking.created_at.desc()))
                assert row
                identifier = row.id
            name, args = 'confirm_scheduling_booking', {'booking_id': identifier}
        else:
            name = 'check_scheduling_availability'
            args = {'provider': 'calendly' if 'Calendly' in last['content'] else 'calcom',
                    'start': remote.utc(START), 'end': remote.utc(END), 'timezone': 'Asia/Kolkata'}
        self.calls = [{'name': name, 'arguments': json.dumps(args), 'call_id': 'synthetic-tool-call'}]
        if False:
            yield ''

    def append_results(self, result):
        self.messages.append({'role': 'tool', 'content': json.dumps(result[0])})


if os.environ.get('QA_SCHEDULING_OAUTH') == '1':
    async def fixture_token(provider, form):
        assert form['grant_type']=='authorization_code'
        if provider=='calendly':assert form.get('code_verifier')
        return {'access_token':'synthetic-oauth-access','refresh_token':'synthetic-oauth-refresh','expires_in':1800,'token_type':'bearer','scope':' '.join(scheduling_oauth.PROVIDERS[provider]['scopes'])}
    scheduling_oauth.token_request = fixture_token

remote.request = provider
llm.resolve = lambda *args: {'api_key': 'synthetic-model-token'}
llm.Turn = ModelTurn
app = create_app(start_worker=False)


@app.get('/qa-booking-count')
def count():
    return {'simulated_posts': posts, 'external_provider_requests': 0}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
