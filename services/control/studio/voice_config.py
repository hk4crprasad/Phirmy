"""Server-selected voice stack, independent of the agent's text-chat model."""
from .config import settings

SPOKEN_LANGUAGES = {'en': 'en-IN', 'hi': 'hi-IN', 'bn': 'bn-IN', 'kn': 'kn-IN',
                    'ml': 'ml-IN', 'mr': 'mr-IN', 'or': 'od-IN', 'od': 'od-IN',
                    'pa': 'pa-IN', 'ta': 'ta-IN', 'te': 'te-IN', 'gu': 'gu-IN'}


def spoken_language(text='', detected=None):
    """Use supported ASR language first, then native script, then English."""
    if isinstance(detected, str):
        selected = SPOKEN_LANGUAGES.get(detected.split('-')[0].lower())
        if selected:
            return selected
    ranges = [(0x0900, 0x097f, 'hi-IN'), (0x0980, 0x09ff, 'bn-IN'),
              (0x0a00, 0x0a7f, 'pa-IN'), (0x0a80, 0x0aff, 'gu-IN'),
              (0x0b00, 0x0b7f, 'od-IN'), (0x0b80, 0x0bff, 'ta-IN'),
              (0x0c00, 0x0c7f, 'te-IN'), (0x0c80, 0x0cff, 'kn-IN'),
              (0x0d00, 0x0d7f, 'ml-IN')]
    scored = [(sum(start <= ord(c) <= end for c in text), code) for start, end, code in ranges]
    count, code = max(scored)
    return code if count else 'en-IN'


def sarvam_enabled():
    return settings.voice_provider == 'sarvam'


def speech_config(config):
    old = config.get('speech', {})
    if not sarvam_enabled():
        return dict(old)
    language = old.get('live_stt_language') or settings.sarvam_language
    language = {'en': 'en-IN', 'hi': 'hi-IN', 'multi': 'auto', 'unknown': 'auto', 'od-IN': 'or-IN'}.get(language, language)
    native = old.get('provider') == 'sarvam'
    return {
        'provider': 'sarvam', 'model': settings.sarvam_tts_model,
        'voice_id': old.get('voice_id') if native else settings.sarvam_voice_id,
        'live_stt_provider': 'sarvam', 'live_stt_model': settings.sarvam_stt_model,
        'live_stt_language': language,
        'language_code': old.get('language_code') or ('auto' if language == 'auto' else language.replace('or-IN', 'od-IN')),
        'postcall_asr_model': 'transcribe-1-pro',
    }


def stt_provider():
    return 'sarvam-stt' if sarvam_enabled() else 'deepgram'


def voice_profile(workspace_id=None):
    return {'api_key': settings.sarvam_api_key, 'model': settings.sarvam_voice_model,
            'base_url': 'https://api.sarvam.ai/v1', 'api_style': 'chat_completions',
            'token_parameter': 'max_tokens', 'options': {'reasoning_effort': None},
            'provider': 'sarvam-llm', 'voice': True, 'workspace_id': workspace_id,
            'research': {'source_url': 'https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview',
                         'checked_at': '2026-10-29'}}
