"""One streaming interface for Responses and OpenAI-compatible Chat Completions.

No temperature is sent by default. Token caps are API/profile-specific. Validation
errors may negotiate a parameter once before streaming; never replay emitted text.
"""
import json
import logging
import re
import sys
import time
from urllib.parse import urlparse
from sqlalchemy import select
from .config import settings
from .db import session_scope
from .models import LLMProfile
from .secrets import decrypt

DOCS='https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create'


def environment_profile(model=None):
    official=urlparse(settings.openai_base_url).hostname in {'api.openai.com'}
    style=settings.openai_api_style
    if style=='auto':style='responses' if official else 'chat_completions'
    model=model or settings.openai_model
    token=settings.openai_token_parameter
    if token=='auto':token='max_output_tokens' if style=='responses' else 'max_completion_tokens' if official else 'max_tokens'
    effort=settings.openai_reasoning_effort
    if effort=='auto':
        effort='none' if official and model in {'gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','gpt-6-luna','gpt-6-sol'} else 'low' if official and model in {'gpt-6-astra','gpt-6.1-sol'} else None
    return {'api_key':settings.openai_api_key,'model':model,'base_url':settings.openai_base_url,'api_style':style,'token_parameter':token,'options':{'reasoning_effort':effort},'research':{'source_url':DOCS,'checked_at':'2026-10-22'}}


def resolve(config=None,workspace_id=None):
    llm=(config or {}).get('llm',{})
    if llm.get('profile_id'):
        if not workspace_id:raise ValueError('Workspace context required for a custom model')
        with session_scope() as db:
            row=db.scalar(select(LLMProfile).where(LLMProfile.workspace_id==workspace_id,LLMProfile.id==llm['profile_id'],LLMProfile.enabled.is_(True)))
            if not row:raise ValueError('Custom model profile is unavailable')
            return {'api_key':decrypt(row.encrypted_key),'model':row.model,'base_url':row.base_url,'api_style':row.api_style,'token_parameter':row.token_parameter,'options':row.options,'research':row.research,'public_only':True,'workspace_id':workspace_id}
    profile=environment_profile(llm.get('model'))
    if workspace_id:profile['workspace_id']=workspace_id
    return profile


def options(profile,limit):
    result={}
    cap=profile['token_parameter']
    if profile['api_style']=='responses' and cap not in {'none','omit'}:cap='max_output_tokens'
    if cap not in {'none','omit'}:result[cap]=limit
    opts=profile.get('options',{})
    if profile.get('provider') == 'sarvam-llm':
        result['reasoning_effort'] = None
    elif opts.get('reasoning_effort'):
        if profile['api_style']=='responses':result['reasoning']={'effort':opts['reasoning_effort']}
        else:result['reasoning_effort']=opts['reasoning_effort']
    if opts.get('temperature') is not None:result['temperature']=opts['temperature']
    return result


def live_voice_ready(config,workspace_id):
    from .voice_config import sarvam_enabled, speech_config
    if sarvam_enabled():
        return bool(settings.sarvam_api_key and speech_config(config)['voice_id'])
    voice=config.get('speech',{}).get('voice_id') or settings.fish_voice_id
    return bool(settings.fish_api_key and voice and voice!='CONFIGURE_FISH_VOICE' and settings.deepgram_api_key and resolve(config,workspace_id)['api_key'])


class Turn:
    def __init__(self,profile,instructions,messages,tools=None,limit=1200,force_text=False):
        model=profile.get('model')
        if not isinstance(model,str) or not model.strip():
            from fastapi import HTTPException
            raise HTTPException(409,'Model profile must specify a nonempty model identifier before provider use or metering')
        self.profile,self.instructions,self.messages=profile,instructions,messages
        self.tools=tools or [];self.limit=limit;self.force_text=force_text;self.calls=[];self.output=[];self.text='';self.first_token_ms=None
        from .metering import context
        from .db import uid
        self.billing_context=dict(profile.get('usage_context') or context.get())
        self.billing_context['model']=profile['model']
        if profile.get('workspace_id'):self.billing_context.setdefault('workspace_id',profile['workspace_id'])
        self.invocation_id=uid();self.usage=None;self.request_started=False
        self.usage_complete=False;self.cache_accounted=False;self.cache_writes_priced=False
        self.stable_instructions=None;self.cache_prefix_messages=0
        self.emit_tool_events=False

    async def stream(self):
        from .db import uid
        from .async_work import durable_to_thread
        self.invocation_id=uid();self.usage=None;self.request_started=False;self.usage_complete=False
        self.calls=[];self.output=[];self.text='';self.first_token_ms=None
        from .llm_requests import cache_usage_supported
        self.cache_accounted=cache_usage_supported(self.profile) and bool(self.billing_context.get('workspace_id'))
        self.cache_writes_priced=False
        if self.billing_context.get('workspace_id'):
            from fastapi import HTTPException
            from .admission import provider_hold
            if self.profile['token_parameter'] in {'none','omit'}:
                raise HTTPException(409,'A bounded output-token parameter is required for metered models')
            self.limit=min(self.limit,settings.billing_max_llm_output_tokens)
            serialized=json.dumps([self.instructions,self.messages,self.tools],ensure_ascii=False,default=str).encode()
            if len(serialized)>settings.billing_max_llm_input_bytes:
                raise HTTPException(413,'Model context exceeds the configured input budget')
            # UTF-8 bytes conservatively bound text tokens; include protocol/tool overhead.
        try:
            if self.billing_context.get('workspace_id'):
                from .voice_latency import measure
                with measure('llm_admission'):
                    cache_kwargs={'cache_mode':'responses_30m' if self.profile['api_style']=='responses' else 'chat_30m'} if self.cache_accounted else {}
                    admission=await durable_to_thread(provider_hold,self.billing_context,'llm:'+self.invocation_id,self.profile.get('provider','openai'),
                        {'input_tokens':len(serialized)+8192,'output_tokens':self.limit},**cache_kwargs)
                    if self.cache_accounted:self.cache_writes_priced=admission['cache_writes_priced']
            async for delta in self._stream():yield delta
        finally:
            if self.billing_context.get('workspace_id'):
                failed=sys.exception() is not None
                try:
                    if self.request_started:
                        from .metering import append_cost
                        await durable_to_thread(append_cost,self.billing_context,self.profile.get('provider','openai'),'llm',self.usage or {},
                            'llm:'+self.invocation_id,'provider_usage' if self.usage_complete else 'unreported')
                    else:
                        from .admission import provider_release
                        await durable_to_thread(provider_release,self.billing_context,'llm:'+self.invocation_id)
                except Exception:
                    if not failed:raise
                    # The durable hold remains fail closed. Never replace a
                    # provider/validation error with a cleanup error or log PII.
                    logging.getLogger(__name__).warning('llm_settlement_failed')

    def capture_usage(self,usage,style):
        if usage is None:return
        self.usage_complete=False
        def value(obj,name,default=0):return obj.get(name,default) if isinstance(obj,dict) else getattr(obj,name,default)
        incoming=value(usage,'input_tokens' if style=='responses' else 'prompt_tokens',None)
        outgoing=value(usage,'output_tokens' if style=='responses' else 'completion_tokens',None)
        if any(type(amount) is not int or not 0<=amount<=1_000_000_000 for amount in [incoming,outgoing]):return
        from .llm_requests import cache_supported,cache_usage_supported
        details=value(usage,'input_tokens_details' if style=='responses' else 'prompt_tokens_details',{})
        self.usage={'input_tokens':incoming,'output_tokens':outgoing}
        cached=value(details,'cached_tokens',None if cache_supported(self.profile) else 0)
        if type(cached) is not int or not 0<=cached<=incoming:return
        self.usage['cached_input_tokens']=cached
        written=value(details,'cache_write_tokens',None)
        if written is None:
            self.usage_complete=not cache_supported(self.profile)
            return
        if type(written) is not int or not 0<=written<=incoming-cached:
            self.usage_complete=False;return
        if written:
            self.usage['cache_write_tokens']=written
            lifetime=value(details,'cache_write_tokens_details',None)
            if lifetime is None and cache_usage_supported(self.profile):
                # This adapter requests/defaults to30m and never overrides a
                # breakpoint lifetime. Older API versions report only the total.
                thirty,twelve=written,0
            else:
                thirty=value(lifetime,'ttl_30m_tokens',None)
                twelve=value(lifetime,'ttl_12h_tokens',None)
            if any(type(amount) is not int or amount<0 for amount in [thirty,twelve]) or thirty+twelve!=written:
                self.usage_complete=False;return
            self.usage.update(cache_write_30m_tokens=thirty,cache_write_12h_tokens=twelve)
        self.usage_complete=True

    async def _stream(self):
        from openai import BadRequestError
        from .llm_connections import client_for
        started=time.monotonic();p=self.profile
        kwargs=options(p,self.limit)
        include_usage=p.get('provider') != 'sarvam-llm'  # Sarvam emits terminal usage without stream_options.
        async with client_for(p,self.billing_context.get('workspace_id')) as client:
            for attempt in range(3):
                try:
                    from .voice_latency import mark
                    if p['api_style']=='responses':
                        from .llm_requests import responses_request
                        extra={'tools':self.tools,'parallel_tool_calls':False} if self.tools else {}
                        if self.force_text and self.tools:extra['tool_choice']='none'
                        payload=responses_request(self)
                        self.request_started=True;mark('llm_request_started')
                        stream=await client.responses.create(model=p['model'],stream=True,**payload,**kwargs,**extra)
                    else:
                        extra={'tools':[{'type':'function','function':{k:v for k,v in t.items() if k!='type'}} for t in self.tools]} if self.tools else {}
                        if self.force_text and self.tools:extra['tool_choice']='none'
                        if include_usage:extra['stream_options']={'include_usage':True}
                        self.request_started=True;mark('llm_request_started')
                        stream=await client.chat.completions.create(model=p['model'],messages=[{'role':'system','content':self.instructions}]+self.messages,stream=True,**kwargs,**extra)
                    break
                except BadRequestError as exc:
                    # These are input validation failures: no generation/tool output has run.
                    error=json.dumps(exc.body).lower()
                    if attempt>=2:raise
                    if ('stream_options' in error or 'include_usage' in error):
                        include_usage=False;continue
                    if 'temperature' in error and 'temperature' in kwargs:kwargs.pop('temperature');continue
                    if 'max_tokens' in error and 'max_tokens' in kwargs:
                        kwargs['max_completion_tokens']=kwargs.pop('max_tokens');continue
                    if 'max_completion_tokens' in error and 'max_completion_tokens' in kwargs and not urlparse(p['base_url']).hostname=='api.openai.com':
                        kwargs['max_tokens']=kwargs.pop('max_completion_tokens');continue
                    raise
            else:raise RuntimeError('Model parameter negotiation failed')
            if p['api_style']=='responses':
                from .llm_events import ModelIncompleteError,ToolStreamState,value
                tool_stream=ToolStreamState()
                completed=False
                async with stream:
                    iterator=aiter(stream)
                    async for event in iterator:
                        if event.type=='response.output_text.delta':
                            if not event.delta:continue
                            mark('llm_first_token')
                            if self.first_token_ms is None:self.first_token_ms=round((time.monotonic()-started)*1000)
                            self.text+=event.delta;yield event.delta
                        elif event.type=='response.output_item.added':
                            signal=tool_stream.added(event.item)
                            if signal is not None and self.emit_tool_events:yield signal
                        elif event.type=='response.function_call_arguments.delta':
                            tool_stream.arguments(event)
                        elif event.type=='response.function_call_arguments.done':
                            tool_stream.arguments(event,done=True)
                        elif event.type=='response.completed':
                            self.capture_usage(getattr(event.response,'usage',None),'responses')
                            completed=True;self.output=list(event.response.output)
                            self.calls=tool_stream.completed(self.output)
                            if p.get('voice'):
                                from .llm_connections import drain_completed
                                await drain_completed(iterator)
                            break
                        elif event.type=='response.incomplete':
                            response=value(event,'response')
                            self.capture_usage(value(response,'usage'),'responses')
                            if p.get('voice'):
                                from .llm_connections import drain_completed
                                await drain_completed(iterator)
                            raise ModelIncompleteError(value(value(response,'incomplete_details'),'reason'))
                        elif event.type in {'response.failed','error'}:
                            self.capture_usage(getattr(getattr(event,'response',None),'usage',None),'responses')
                            raise RuntimeError('The model could not finish this turn')
                if not completed:raise RuntimeError('Model stream ended without completion')
            else:
                calls={};finished=False
                async with stream:
                    async for chunk in stream:
                        self.capture_usage(getattr(chunk,'usage',None),'chat')
                        if not chunk.choices:continue
                        choice=chunk.choices[0]
                        if choice.finish_reason:
                            if choice.finish_reason in {'length','content_filter'}:raise RuntimeError('Model response was truncated or filtered')
                            finished=True
                        delta=choice.delta
                        if delta.content:
                            mark('llm_first_token')
                            if self.first_token_ms is None:self.first_token_ms=round((time.monotonic()-started)*1000)
                            self.text+=delta.content;yield delta.content
                        for call in delta.tool_calls or []:
                            if type(call.index) is not int or not 0 <= call.index < 8:
                                raise RuntimeError('Invalid streamed tool index')
                            if call.index not in calls and self.emit_tool_events:
                                from .llm_events import ToolCallStarted
                                yield ToolCallStarted(str(call.index))
                            item=calls.setdefault(call.index,{'id':'','name':'','arguments':''})
                            if call.id:item['id']=call.id
                            if call.function:
                                item['name']+=call.function.name or '';item['arguments']+=call.function.arguments or ''
                            if len(item['id']) > 256 or len(item['name']) > 160 or len(item['arguments'].encode()) > 65536:
                                raise RuntimeError('Streamed tool call exceeded its bounds')
                if not finished:raise RuntimeError('Model stream ended without a finish reason')
                self.calls=list(calls.values())
                if any(not item['id'] or not item['name'] for item in self.calls) or len({item['id'] for item in self.calls}) != len(self.calls):
                    raise RuntimeError('Invalid completed tool identities')

    def append_results(self,results):
        if self.profile['api_style']=='responses':
            self.messages.extend(self.output)
            self.messages.extend({'type':'function_call_output','call_id':call['id'],'output':json.dumps(result)[:16000]} for call,result in zip(self.calls,results))
        else:
            self.messages.append({'role':'assistant','content':self.text or None,'tool_calls':[{'id':c['id'],'type':'function','function':{'name':c['name'],'arguments':c['arguments']}} for c in self.calls]})
            self.messages.extend({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result)[:16000]} for call,result in zip(self.calls,results))
