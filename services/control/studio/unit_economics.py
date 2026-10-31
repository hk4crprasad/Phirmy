"""Configuration-based sensitivity report, separate from immutable actual meters."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .metering import MICRO, cost_micro
from .plans import catalog


class Assumptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['DRAFT']
    default_model: str = Field(min_length=1, max_length=160)
    cache_write_input_bps: StrictInt = Field(ge=0, le=10000)
    chat_input_tokens_per_turn: StrictInt = Field(ge=1, le=1_000_000)
    chat_output_tokens_per_turn: StrictInt = Field(ge=1, le=100_000)
    embedding_query_tokens_per_turn: StrictInt = Field(ge=0, le=100_000)
    voice_turns_per_minute: StrictInt = Field(ge=1, le=60)
    voice_input_tokens_per_turn: StrictInt = Field(ge=1, le=1_000_000)
    voice_output_tokens_per_turn: StrictInt = Field(ge=1, le=100_000)
    voice_tts_utf8_bytes_per_minute: StrictInt = Field(ge=1, le=100_000)
    crawl_embedding_tokens_per_page: StrictInt = Field(ge=1, le=1_000_000)
    notes: str = Field(min_length=20, max_length=2000)


def report():
    body = catalog()
    assumptions = Assumptions.model_validate_json((Path(__file__).resolve().parents[3]/'config/unit_economics.json').read_text()).model_dump()
    provider = body['provider_rates']
    models = body['model_rates'] or {'configured-default':provider}
    results = []
    for model, rates in models.items():
        def llm_units(incoming,outgoing):
            written=(incoming*assumptions['cache_write_input_bps']+9999)//10000 if (
                (rates.get('llm_cache_write_30m_minor_per_million_tokens') or 0)>rates['llm_input_minor_per_million_tokens']) else 0
            return {'input_tokens':incoming,'output_tokens':outgoing,'cache_write_30m_tokens':written}
        query = cost_micro(provider, 'embedding', {'input_tokens':assumptions['embedding_query_tokens_per_turn']})
        chat = query+cost_micro(rates, 'llm', llm_units(assumptions['chat_input_tokens_per_turn'],
                                                     assumptions['chat_output_tokens_per_turn']))
        turns = assumptions['voice_turns_per_minute']
        llm = turns*(query+cost_micro(rates,'llm',llm_units(assumptions['voice_input_tokens_per_turn'],
                                                        assumptions['voice_output_tokens_per_turn'])))
        from .voice_config import sarvam_enabled
        from .config import settings
        if sarvam_enabled():
            voice_rates = body['model_rates'][settings.sarvam_voice_model]
            llm = turns*(query+cost_micro(voice_rates, 'sarvam-llm', {
                'input_tokens': assumptions['voice_input_tokens_per_turn'],
                'output_tokens': assumptions['voice_output_tokens_per_turn']}))
            stt = cost_micro(provider, 'sarvam-stt', {'stt_ms':60000})
            # UTF-8 byte workload is a conservative character upper bound.
            tts = cost_micro(provider, 'sarvam-tts', {'tts_characters':assumptions['voice_tts_utf8_bytes_per_minute']})
        else:
            stt = cost_micro(provider, 'deepgram', {'stt_ms':60000})
            tts = cost_micro(provider, 'fish', {'tts_utf8_bytes':assumptions['voice_tts_utf8_bytes_per_minute']})
        carrier = cost_micro(provider, 'plivo', {'carrier_ms':60000})
        browser = llm+stt+tts
        plans = []
        for slug, plan in body['plans'].items():
            included = plan['included']
            price = plan['monthly_price_minor']*MICRO
            cap = plan['spend_cap_minor']*MICRO
            chat_cost = chat*included['chat_turns']
            browser_cost = (browser*included['voice_ms']+59999)//60000
            phone_cost = ((browser+carrier)*included['voice_ms']+59999)//60000
            embedding = cost_micro(provider,'embedding',{'input_tokens':included['crawl_pages']*assumptions['crawl_embedding_tokens_per_page']})
            storage = (included['storage_bytes']*provider['storage_minor_per_gb_month']*MICRO+999_999_999)//1_000_000_000
            overhead = embedding+storage
            scenarios = []
            for channel, cost in [('chat',chat_cost), ('browser_voice',browser_cost), ('phone_voice',phone_cost),
                                  ('chat_and_browser_voice',chat_cost+browser_cost+overhead),
                                  ('chat_and_phone_voice',chat_cost+phone_cost+overhead)]:
                scenarios.append({'channel':channel, 'allowance_cost_micro_minor':cost,
                    'cost_exceeds_price':cost>price, 'loss_micro_minor':max(0,cost-price),
                    'contribution_bps':((price-cost)*10000)//price if price else None,
                    'cost_exceeds_spend_cap':cost>cap})
            plans.append({'id':slug,'name':plan['name'],'monthly_price_minor':plan['monthly_price_minor'],
                'spend_cap_minor':plan['spend_cap_minor'],'included':included,
                'knowledge_storage_cost_micro_minor':overhead,'scenarios':scenarios,
                'loss_flag':any(row['cost_exceeds_price'] for row in scenarios),
                'quote_required':not plan['self_serve']})
        results.append({'id':model,'unit_cost_micro_minor':{'chat_turn':chat,'browser_voice_minute':browser,
            'phone_voice_minute':browser+carrier},'voice_components_micro_minor':{'llm_and_retrieval':llm,'stt':stt,'tts':tts,'carrier':carrier},
            'plans':plans})
    return {'status':'DRAFT','currency':body['currency'],'catalog_hash':body['content_hash'],
        'catalog_version':body['version'],'provider_rates_status':body['status'],'assumptions':assumptions,
        'default_model':assumptions['default_model'] if assumptions['default_model'] in models else next(iter(models)),
        'models':results,'voice_model':settings.sarvam_voice_model if sarvam_enabled() else 'selected-chat-model',
        'basis':'Gross included allowance exposure before admission caps. A cap can stop delivery before advertised allowances are consumed. '
                'Phone and browser scenarios share the same voice allowance; they are not added together. '
                'No measured latency, actual margin, provider quote or final commercial approval is implied.'}
