"""Bound request bodies before parsing, preserve webhook bytes, harden API headers."""
import asyncio
import time

from starlette.responses import JSONResponse
from .config import settings


class RequestSecurity:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def secure_send(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                names = {name.lower() for name, _ in headers}
                for name, value in [(b'x-content-type-options', b'nosniff'),
                                    (b'referrer-policy', b'no-referrer'),
                                    (b'content-security-policy', b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")]:
                    if name not in names:
                        headers.append((name, value))
                if settings.app_env == 'production':
                    headers.append((b'strict-transport-security', b'max-age=31536000; includeSubDomains'))
                message = {**message, 'headers': headers}
            await send(message)
        async def reject(status, message):
            await JSONResponse({'detail':message}, status_code=status)(scope, receive, secure_send)
        if scope['method'] not in {'POST','PUT','PATCH','DELETE'}:
            return await self.app(scope, receive, secure_send)
        headers = dict(scope.get('headers', []))
        if headers.get(b'content-encoding', b'identity').lower() not in {b'',b'identity'}:
            return await reject(415, 'Compressed request bodies are not supported')
        multipart = headers.get(b'content-type', b'').lower().startswith(b'multipart/form-data')
        maximum = settings.request_max_bytes if multipart else settings.request_json_max_bytes
        try:
            declared = int(headers.get(b'content-length', b'0'))
            if declared < 0:
                raise ValueError()
        except ValueError:
            return await reject(400, 'Invalid Content-Length')
        if declared > maximum:
            return await reject(413, 'Request body is too large')
        chunks, size = [], 0
        deadline = time.monotonic() + settings.request_body_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return await reject(408, 'Request body timed out')
            try:
                message = await asyncio.wait_for(receive(), remaining)
            except asyncio.TimeoutError:
                return await reject(408, 'Request body timed out')
            if message['type'] == 'http.disconnect':
                return
            body = message.get('body', b'')
            size += len(body)
            if size > maximum:
                return await reject(413, 'Request body is too large')
            chunks.append(body)
            if not message.get('more_body'):
                break
        buffered = b''.join(chunks)
        replayed = False
        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {'type':'http.request', 'body':buffered, 'more_body':False}
        return await self.app(scope, replay, secure_send)
