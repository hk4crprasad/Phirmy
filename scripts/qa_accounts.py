"""QA account bootstrap through the real generic signup, sign-in and me APIs.

Returns the actual /auth/me response (HTTP 200, workspaces array). Requires an
isolated development/test API; it never bypasses verification or exposes tokens.
"""


def _status(response):
    return getattr(response, 'status_code', getattr(response, 'status', None))


def bootstrap_account(client, path, **kwargs):
    payload = kwargs.get('json', kwargs.get('data'))
    policy = client.get(path.replace('/auth/signup', '/public/legal')).json()
    mode = 'json' if 'json' in kwargs else 'data'
    kwargs[mode] = {**payload, 'legal_accepted': True, 'legal_version': policy['version']}
    response = client.post(path, **kwargs)
    assert _status(response) == 202, 'QA registration was not accepted'
    mode = 'json' if 'json' in kwargs else 'data'
    options = {mode: {name: payload[name] for name in ['email', 'password']}}
    if 'headers' in kwargs:
        options['headers'] = kwargs['headers']
    response = client.post(path.replace('/auth/signup', '/auth/signin'), **options)
    assert _status(response) == 200, 'QA account sign-in failed'
    response = client.get(path.replace('/auth/signup', '/auth/me'))
    assert _status(response) == 200, 'QA account session failed'
    assert not response.json()['user']['verification_required'], 'Use an isolated QA API with development signup enabled'
    assert response.json()['workspaces'], 'QA workspace is missing'
    return response


async def bootstrap_account_async(client, path, **kwargs):
    payload = kwargs.get('json', kwargs.get('data'))
    policy = (await client.get(path.replace('/auth/signup', '/public/legal'))).json()
    mode = 'json' if 'json' in kwargs else 'data'
    kwargs[mode] = {**payload, 'legal_accepted': True, 'legal_version': policy['version']}
    response = await client.post(path, **kwargs)
    assert _status(response) == 202, 'QA registration was not accepted'
    mode = 'json' if 'json' in kwargs else 'data'
    options = {mode: {name: payload[name] for name in ['email', 'password']}}
    if 'headers' in kwargs:
        options['headers'] = kwargs['headers']
    response = await client.post(path.replace('/auth/signup', '/auth/signin'), **options)
    assert _status(response) == 200, 'QA account sign-in failed'
    response = await client.get(path.replace('/auth/signup', '/auth/me'))
    assert _status(response) == 200
    assert not response.json()['user']['verification_required'] and response.json()['workspaces']
    return response
