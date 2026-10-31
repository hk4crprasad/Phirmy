"""Cloudflare contract: single-use token, remote IP and exact hostname/action."""
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit
import uuid

from fastapi import HTTPException
import httpx

from .config import settings
from .db import now

ACTION='widget_session'


class BotChallengeProvider(Protocol):
    async def verify(self,token: str,remote_ip: str,hostname: str) -> bool: ...


class TurnstileProvider:
    async def verify(self,token,remote_ip,hostname):
        if not settings.turnstile_secret_key:return False
        try:
            async with httpx.AsyncClient(timeout=5,follow_redirects=False) as client:
                response=await client.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',json={
                    'secret':settings.turnstile_secret_key,'response':token,'remoteip':remote_ip,
                    'idempotency_key':str(uuid.uuid4())})
                response.raise_for_status();result=response.json()
            timestamp=datetime.fromisoformat(result.get('challenge_ts','').replace('Z','+00:00'))
            age=(now()-timestamp).total_seconds()
            return (result.get('success') is True and result.get('hostname','').lower()==hostname.lower()
                    and result.get('action')==ACTION and -10<=age<=300)
        except (httpx.HTTPError,ValueError,TypeError,AttributeError):return False


provider: BotChallengeProvider=TurnstileProvider()


def required():
    return settings.widget_bot_challenge_enabled


def public_configuration():
    return {'required':required(),'provider':'turnstile','site_key':settings.turnstile_site_key,'action':ACTION}


def dashboard_preview_user(request,installation,db):
    """Only an authenticated, CSRF-protected workspace builder can preview."""
    if request.headers.get('x-studio-preview')!='1':return None
    from .security import principal,check_origin
    check_origin(request)
    if request.headers.get('origin') not in {settings.app_origin,settings.app_origin.replace('localhost','127.0.0.1')}:
        raise HTTPException(403,'Dashboard previews require the application origin')
    actor=principal(request,installation.workspace_id,db)
    actor.require('widget:write')
    if not actor.user_id:raise HTTPException(403,'Sign in to preview your assistant')
    return actor.user_id


def enforce_session(context):
    if required() and (context is None or context.variables.get('_bot_verified') is not True):
        raise HTTPException(403,'Reconnect and complete the bot check to continue')


async def enforce(token,remote_ip,origin):
    if not required():return
    if not settings.turnstile_site_key or not settings.turnstile_secret_key:
        raise HTTPException(503,'This assistant is awaiting bot-protection configuration')
    if not token or len(token)>2048 or not remote_ip:
        raise HTTPException(403,'Complete the bot check to continue')
    try:verified=await provider.verify(token,remote_ip,urlsplit(origin).hostname or '')
    except Exception:verified=False
    if verified is not True:raise HTTPException(403,'Bot verification failed or expired. Please retry.')
