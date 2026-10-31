"""Versioned Cal.com and Calendly adapters. URLs and actions are server-owned."""
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse

import httpx

CAL = 'https://api.cal.com/v2'
CALENDLY = 'https://api.calendly.com'
CAL_EVENT_VERSION = '2024-06-14'
CAL_SLOT_VERSION = '2024-09-04'
CAL_BOOKING_VERSION = '2024-08-13'


class ProviderError(Exception):
    def __init__(self, status=None):
        self.status = status
        super().__init__('Scheduling provider request could not be confirmed')

    @property
    def definitive_rejection(self):
        return self.status is not None and 400 <= self.status < 500 and self.status not in (408, 429)


async def request(method, url, **kwargs):
    # Never include tokens, caller details or provider response bodies in errors.
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.request(method, url, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ProviderError(response.status_code)
        data = response.json()
        if not isinstance(data, dict):
            raise ProviderError()
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError() from exc


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if not parsed.tzinfo:
        raise ValueError('Timezone-aware time required')
    return parsed.astimezone(timezone.utc)


def utc(value):
    return timestamp(value).isoformat().replace('+00:00', 'Z')


def calendly_uri(value, kind):
    # Return a canonical URL, never fetch an arbitrary URL from tool arguments.
    if not isinstance(value, str) or not re.fullmatch(
            r'https://api\.calendly\.com/' + kind + r'/[A-Za-z0-9-]{8,100}', value):
        raise ValueError('Use the canonical Calendly ' + kind + ' URI')
    return value


def event_id(provider, value):
    if provider == 'calcom' and re.fullmatch(r'[1-9]\d{0,12}', str(value)):
        return str(value)
    if provider == 'calendly':
        return calendly_uri(value, 'event_types')
    raise ValueError('Select a valid scheduling event type')


def headers(provider, credentials, version=None):
    key = 'api_key' if provider == 'calcom' else 'access_token'
    token = credentials.get(key)
    if not isinstance(token, str) or not token:
        raise ValueError('Connect the scheduling provider first')
    result = {'Authorization': 'Bearer ' + token}
    if provider == 'calcom':
        result['cal-api-version'] = version or CAL_EVENT_VERSION
    return result


def public_url(value, host):
    try:
        url = urlparse(value)
        if url.scheme == 'https' and url.hostname == host and not url.username and not url.password and url.port in (None, 443):
            return value
    except (ValueError, TypeError):
        pass
    return None


def descriptor(provider, raw):
    if provider == 'calcom':
        identifier = event_id(provider, raw['id'])
        length = raw['lengthInMinutes']
        reason = 'Use a non-recurring event without required payment.' if raw.get('recurrence') or raw.get('price', 0) else None
        questions = [{'key': f['slug'], 'label': str(f.get('label') or f['slug']), 'required': bool(f.get('required'))}
                     for f in raw.get('bookingFields', []) if f.get('slug') not in ('name', 'email', 'location', 'guests')
                     and not f.get('hidden') and f.get('type') in ('text', 'textarea', 'phone', 'number', 'select', 'radio')]
        unsupported = [f for f in raw.get('bookingFields', []) if f.get('required') and not f.get('hidden')
                       and f.get('slug') not in ('name', 'email', 'location')
                       and f.get('type') not in ('text', 'textarea', 'phone', 'number', 'select', 'radio')]
        if unsupported:
            reason = 'This event has required fields that need its hosted scheduling page.'
        result = {'id': identifier, 'title': str(raw.get('title', 'Appointment'))[:200], 'duration_minutes': length,
                  'questions': questions, 'phone_required': False}
    else:
        identifier = event_id(provider, raw['uri'])
        length = raw['duration']
        reason = None
        if not raw.get('active') or raw.get('deleted_at') or raw.get('is_paid'):
            reason = 'Use an active event without required payment.'
        questions = [{'key': str(q['position']), 'label': str(q['name']), 'required': bool(q.get('required'))}
                     for q in raw.get('custom_questions', []) if q.get('enabled')]
        result = {'id': identifier, 'title': str(raw.get('name', 'Appointment'))[:200], 'duration_minutes': length,
                  'questions': questions, 'owner_uri': raw.get('profile', {}).get('owner'),
                  'pooling_type': raw.get('pooling_type'), 'locations': raw.get('locations', []),
                  'phone_required': any(x.get('kind') == 'outbound_call' for x in raw.get('locations', [])),
                  'scheduling_url': public_url(raw.get('scheduling_url'), 'calendly.com')}
        if len(result['locations']) > 1 or any(x.get('kind') == 'ask_invitee' for x in result['locations']):
            reason = 'Choose an event with a single predefined meeting location.'
    if not isinstance(length, int) or isinstance(length, bool) or not 1 <= length <= 480:
        raise ValueError('A fixed event duration of 1–480 minutes is required')
    if len(questions) > 20 or any(len(question['label']) > 1000 for question in questions):
        reason = 'This event has a long booking form. Please use its hosted scheduling page.'
    result['supported'], result['unavailable_reason'] = not bool(reason), reason
    return result


async def event(provider, credentials, identifier=None):
    identifier = event_id(provider, identifier or credentials.get('event_type_id'))
    if provider == 'calcom':
        data = await request('GET', CAL + '/event-types/' + identifier, headers=headers(provider, credentials))
        if data.get('status') != 'success':
            raise ProviderError()
        result = descriptor(provider, data['data'])
    else:
        data = await request('GET', identifier, headers=headers(provider, credentials))
        result = descriptor(provider, data['resource'])
    if result['id'] != identifier:
        raise ProviderError()
    return result


async def event_types(provider, credentials):
    if provider == 'calcom':
        response = await request('GET', CAL + '/event-types', headers=headers(provider, credentials))
        if response.get('status') != 'success' or not isinstance(response.get('data'), list):
            raise ProviderError()
        rows = response['data'][:100]
    else:
        me = await request('GET', CALENDLY + '/users/me', headers=headers(provider, credentials))
        owner = calendly_uri(me['resource']['uri'], 'users')
        response = await request('GET', CALENDLY + '/event_types', headers=headers(provider, credentials),
                                 params={'user': owner, 'active': 'true', 'count': 100})
        rows = response['collection'][:100]
    return [descriptor(provider, row) for row in rows]


async def slots(provider, credentials, metadata, start, end, zone):
    if not metadata['supported']:
        raise ValueError(metadata['unavailable_reason'])
    if provider == 'calcom':
        response = await request('GET', CAL + '/slots', headers=headers(provider, credentials, CAL_SLOT_VERSION),
            params={'eventTypeId': metadata['id'], 'start': utc(start), 'end': utc(end), 'timeZone': zone, 'format': 'range'})
        if response.get('status') != 'success' or not isinstance(response.get('data'), dict):
            raise ProviderError()
        rows = [row for day in response['data'].values() for row in day]
        candidates = [(timestamp(row['start']), timestamp(row['end'])) for row in rows
                      if row.get('seatsRemaining', 1) > 0]
    else:
        response = await request('GET', CALENDLY + '/event_type_available_times', headers=headers(provider, credentials),
            params={'event_type': metadata['id'], 'start_time': utc(start), 'end_time': utc(end)})
        if not isinstance(response.get('collection'), list):
            raise ProviderError()
        candidates = [(timestamp(row['start_time']), timestamp(row['start_time']) + timedelta(minutes=metadata['duration_minutes']))
                      for row in response['collection'] if row.get('status') == 'available' and row.get('invitees_remaining', 1) > 0]
    result = []
    for begin, finish in sorted(set(candidates)):
        if start <= begin < finish <= end and finish - begin == timedelta(minutes=metadata['duration_minutes']):
            result.append({'start': utc(begin), 'end': utc(finish)})
    return result[:100]


def payload(provider, booking, metadata):
    data = booking.request_data
    if provider == 'calcom':
        attendee = {'name': data['name'], 'email': data['email'], 'timeZone': data['timezone']}
        if data.get('phone'):
            attendee['phoneNumber'] = data['phone']
        return {'eventTypeId': int(metadata['id']), 'start': data['start'], 'attendee': attendee,
                'bookingFieldsResponses': data['answers'], 'metadata': {'cynerzaBookingId': booking.id}}
    result = {'event_type': metadata['id'], 'start_time': data['start'],
              'invitee': {'name': data['name'], 'email': data['email'], 'timezone': data['timezone']},
              'tracking': {'utm_source': 'cynerza', 'utm_content': booking.id},
              'questions_and_answers': [{'question': q['label'], 'position': int(q['key']), 'answer': data['answers'][q['key']]}
                                       for q in metadata['questions'] if q['key'] in data['answers']]}
    locations = metadata.get('locations', [])
    if locations and metadata.get('pooling_type') != 'round_robin':
        location = {'kind': locations[0]['kind']}
        if location['kind'] == 'outbound_call':
            location['location'] = data['phone']
        elif location['kind'] in ('physical', 'custom'):
            location['location'] = locations[0]['location']
        result['location'] = location
    return result


async def create(provider, credentials, booking, metadata):
    url = CAL + '/bookings' if provider == 'calcom' else CALENDLY + '/invitees'
    response = await request('POST', url, headers=headers(provider, credentials, CAL_BOOKING_VERSION),
                             json=payload(provider, booking, metadata))
    try:
        return await verified_result(provider, credentials, booking, response)
    except Exception as exc:
        # Once POST returned successfully, a later GET/validation failure is
        # uncertain, even when that follow-up GET was rejected with HTTP403.
        raise ProviderError() from exc


async def verified_result(provider, credentials, booking, response):
    data = booking.request_data
    if provider == 'calcom':
        if response.get('status') != 'success' or not isinstance(response.get('data'), dict):
            raise ProviderError()
        row = response['data']
        if (str(row.get('eventTypeId')) != data['event_type_id'] or utc(row['start']) != data['start']
                or utc(row['end']) != data['end'] or not any(str(x.get('email', '')).lower() == data['email'].lower() for x in row.get('attendees', []))
                or not re.fullmatch(r'[A-Za-z0-9_-]{5,100}', str(row.get('uid', '')))
                or (booking.remote_id and booking.remote_id != row.get('uid'))):
            raise ProviderError()
        state = {'accepted': 'confirmed', 'pending': 'pending_approval', 'cancelled': 'canceled', 'rejected': 'failed'}.get(row.get('status'))
        if not state:
            raise ProviderError()
        return {'state': state, 'remote_id': row['uid'], 'manage_url': 'https://app.cal.com/bookings/upcoming'}
    row = response.get('resource', {})
    uri = row.get('uri', '')
    if not re.fullmatch(r'https://api\.calendly\.com/scheduled_events/[A-Za-z0-9-]{8,100}/invitees/[A-Za-z0-9-]{8,100}', uri):
        raise ProviderError()
    event_uri = calendly_uri(row.get('event'), 'scheduled_events')
    event_response = await request('GET', event_uri, headers=headers(provider, credentials))
    remote = event_response['resource']
    if (row.get('email', '').lower() != data['email'].lower() or remote.get('event_type') != data['event_type_id']
            or remote.get('uri') != event_uri or (booking.remote_id and booking.remote_id != uri)
            or utc(remote['start_time']) != data['start'] or utc(remote['end_time']) != data['end']):
        raise ProviderError()
    if row.get('status') not in ('active', 'canceled') or remote.get('status') not in ('active', 'canceled'):
        raise ProviderError()
    state = 'confirmed' if row['status'] == remote['status'] == 'active' else 'canceled'
    return {'state': state, 'remote_id': uri, 'remote_event_uri': event_uri,
            'manage_url': public_url(row.get('reschedule_url'), 'calendly.com') or 'https://calendly.com/app/scheduled_events/user/me'}


async def reconcile(provider, credentials, booking, metadata):
    """Only GET requests; exact marker required when a POST outcome was lost."""
    if booking.remote_id:
        url = CAL + '/bookings/' + booking.remote_id if provider == 'calcom' else booking.remote_id
        response = await request('GET', url, headers=headers(provider, credentials, CAL_BOOKING_VERSION))
        return await verified_result(provider, credentials, booking, response)
    data = booking.request_data
    if provider == 'calcom':
        response = await request('GET', CAL + '/bookings', headers=headers(provider, credentials, CAL_BOOKING_VERSION), params={
            'eventTypeId': metadata['id'], 'attendeeEmail': data['email'], 'take': 100,
            'afterStart': utc(timestamp(data['start']) - timedelta(seconds=1)), 'beforeEnd': utc(timestamp(data['end']) + timedelta(seconds=1))})
        matches = [x for x in response.get('data', []) if x.get('metadata', {}).get('cynerzaBookingId') == booking.id]
        if len(matches) == 1:
            return await verified_result(provider, credentials, booking, {'status': 'success', 'data': matches[0]})
    else:
        owner = calendly_uri(metadata.get('owner_uri'), 'users')
        response = await request('GET', CALENDLY + '/scheduled_events', headers=headers(provider, credentials), params={
            'user': owner, 'invitee_email': data['email'], 'min_start_time': data['start'],
            'max_start_time': utc(timestamp(data['start']) + timedelta(seconds=1)), 'count': 100})
        matches = []
        for row in response.get('collection', [])[:5]:
            if row.get('event_type') != metadata['id'] or utc(row['start_time']) != data['start']:
                continue
            uri = calendly_uri(row.get('uri'), 'scheduled_events')
            invitees = await request('GET', uri + '/invitees', headers=headers(provider, credentials), params={'email': data['email'], 'count': 100})
            matches.extend(x for x in invitees.get('collection', []) if x.get('tracking', {}).get('utm_content') == booking.id)
        if len(matches) == 1:
            return await verified_result(provider, credentials, booking, {'resource': matches[0]})
    return None
