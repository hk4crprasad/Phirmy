"""Documented OpenAI voice parameters and explicit, tenant-separated cache input."""
import copy
import hashlib
import hmac
import re
from urllib.parse import urlparse

from fastapi import HTTPException

from .config import settings


def cache_usage_supported(profile):
    """GPT cache usage follows the wire contract, including compatible gateways.

    GPT-5.6+ defaults to 30m when no lifetime is requested. Request extensions
    remain host-gated separately; recognizing usage does not enable extra params.
    https://developers.openai.com/api/docs/guides/prompt-caching#cache-lifetime
    """
    model=profile.get('model')
    return isinstance(model,str) and bool(re.match(r'^gpt-(?:5\.6|6(?:\.1)?)(?:-|$)',model))


def cache_supported(profile):
    return urlparse(profile.get('base_url','')).hostname=='api.openai.com' and cache_usage_supported(profile)


def for_voice(profile, config):
    result={**profile,'voice':True,'options':dict(profile.get('options') or {})}
    if cache_supported(profile) and profile.get('model','').startswith('gpt-5.6'):
        effort=config.get('llm',{}).get('reasoning_effort','none')
        if effort not in {'none','low'}:
            raise HTTPException(409,'Voice reasoning effort must explicitly be none or low')
        result['api_style']='responses'
        result['token_parameter']='max_output_tokens'
        result['options']['reasoning_effort']=effort
    return result


def responses_request(turn):
    """Keep untrusted guidance at user priority; dynamic data is after the cache."""
    result={'instructions':turn.instructions,'input':turn.messages}
    if not cache_supported(turn.profile) or not turn.cache_accounted:
        return result
    if not turn.profile.get('voice'):
        result['prompt_cache_options']={'mode':'implicit','ttl':'30m'} if turn.cache_writes_priced else {'mode':'explicit','ttl':'30m'}
        return result
    result['store']=False
    result['prompt_cache_options']={'mode':'explicit','ttl':'30m'}
    if not (settings.voice_prompt_cache_enabled and turn.cache_writes_priced):
        return result  # No explicit breakpoint => no reads/writes, including legacy tariffs.
    stable=turn.stable_instructions or turn.instructions
    if not turn.instructions.startswith(stable):
        raise ValueError('Stable instructions must be a prefix of the trusted instructions')
    header={'role':'developer','content':[{'type':'input_text','text':stable,
                                        'prompt_cache_breakpoint':{'mode':'explicit'}}]}
    messages=list(turn.messages)
    prefix=[]
    for _ in range(min(turn.cache_prefix_messages,1)):
        if not messages or not isinstance(messages[0],dict) or messages[0].get('role')!='user' or not isinstance(messages[0].get('content'),str):
            raise ValueError('Only explicitly selected stable user guidance can follow the cached developer prefix')
        item=copy.deepcopy(messages.pop(0))
        item['content']=[{'type':'input_text','text':item['content'],'prompt_cache_breakpoint':{'mode':'explicit'}}]
        prefix.append(item)
    dynamic=turn.instructions[len(stable):]
    result.pop('instructions')
    result['input']=[header,*prefix,*([{'role':'developer','content':dynamic}] if dynamic else []),*messages]
    workspace_id=turn.billing_context.get('workspace_id')
    if workspace_id:
        digest=hmac.new(settings.app_secret.encode(),('voice-cache:'+workspace_id).encode(),hashlib.sha256).hexdigest()
        result['prompt_cache_key']='voice:'+digest
    return result
