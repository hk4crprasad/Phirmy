"""Documented carrier redirect adapters. One paid write, no automatic retry."""
import asyncio
import json
from typing import Protocol
from urllib.parse import quote

import httpx

from .config import settings


class TransferProvider(Protocol):
    async def submit(self, payload:dict) -> None: ...


class CarrierTransferProvider:
    async def submit(self, payload):
        credentials=payload['credentials']
        url=settings.media_public_origin.rstrip('/')+'/v1/transfer-webhooks/'+payload['id']+'/instructions'
        if payload['provider']=='twilio':
            from .carrier_config import twilio_client
            client=twilio_client(credentials,timeout=15)
            # The original total-call ceiling stays unchanged. A redirect is
            # not permission to start a fresh duration allowance.
            response=await asyncio.to_thread(client.calls(payload['parent_leg_id']).update,
                url=url,method='POST',time_limit=payload['parent_maximum_seconds'])
            if response.sid!=payload['parent_leg_id']:
                raise RuntimeError('Carrier returned an unexpected call identity')
        elif payload['provider']=='plivo':
            endpoint='https://api.plivo.com/v1/Account/'+quote(credentials['auth_id'],safe='')+'/Call/'+quote(payload['parent_leg_id'],safe='')+'/'
            async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
                response=await client.post(endpoint,auth=(credentials['auth_id'],credentials['auth_token']),
                    json={'legs':'aleg','aleg_url':url,'aleg_method':'POST'})
                response.raise_for_status()
                body=response.json()
                if body.get('message')!='call transferred':
                    raise RuntimeError('Carrier transfer acknowledgement was not recognized')
        else:
            raise RuntimeError('Unsupported carrier')


provider:TransferProvider=CarrierTransferProvider()
