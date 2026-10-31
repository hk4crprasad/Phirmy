"""Bounded text credit; no database transaction for each individual LLM delta."""
from .config import settings
from .async_work import durable_to_thread


class SpeechBudget:
    def __init__(self, values, operation_key, *, provider='fish'):
        self.provider = provider
        self.values, self.operation_key = values, operation_key
        self.reserved_bytes = self.submitted_bytes = 0

    async def reserve(self, quantity):
        if type(quantity) is not int or quantity < 0:
            raise ValueError('Invalid speech byte quantity')
        needed = self.submitted_bytes+quantity
        if needed > self.reserved_bytes:
            from .admission import provider_extend
            grant = max(settings.voice_tts_reservation_bytes, needed-self.reserved_bytes)
            # Cancelling to_thread does not stop its DB transaction. Observe its
            # completion before the parent settles, so a late grant cannot reopen
            # an already settled hold. Transport clearing happens independently.
            await durable_to_thread(provider_extend,self.values,self.operation_key,self.provider,{'tts_characters' if self.provider == 'sarvam-tts' else 'tts_utf8_bytes':grant})
            self.reserved_bytes += grant
        self.submitted_bytes = needed
