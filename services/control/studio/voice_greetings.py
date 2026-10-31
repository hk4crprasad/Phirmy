"""Bounded transient cache for completed, non-personalized greeting PCM only."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import threading
import time

from .config import settings


@dataclass(frozen=True)
class Clip:
    audio: bytes
    expires: float


class GreetingCache:
    # No objects, transcripts or audio persist outside this process. Per-process
    # limits also bound total memory when the service has many tenant versions.
    MAX_CLIP_BYTES = 512_000
    MAX_TOTAL_BYTES = 4_000_000
    MAX_ENTRIES = 64
    TTL_SECONDS = 3600

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.items = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def key(self, workspace_id, version_id, config, text):
        if (not settings.voice_greeting_cache_enabled or not workspace_id or not version_id
                or config.get('_runtime_variables') or config.get('variables')
                or '{{' in text or not text or len(text) > 4000):
            return None
        speech = config.get('speech', {})
        content = [text, speech.get('provider'), speech.get('voice_id'), speech.get('model'), speech.get('language_code'), 'pcm', 24000, 'balanced']
        digest = hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()
        return workspace_id, version_id, digest

    def _expire(self):
        now = self.clock()
        for key, clip in list(self.items.items()):
            if clip.expires <= now:
                self.size -= len(self.items.pop(key).audio)

    def get(self, key):
        if key is None or not settings.voice_greeting_cache_enabled:
            return None
        with self.lock:
            self._expire()
            clip = self.items.get(key)
            if clip is None:
                return None
            self.items.move_to_end(key)
            return clip.audio

    def put(self, key, audio):
        if (key is None or not settings.voice_greeting_cache_enabled or not audio
                or len(audio) > self.MAX_CLIP_BYTES or len(audio) % 2):
            return
        with self.lock:
            self._expire()
            previous = self.items.pop(key, None)
            if previous:
                self.size -= len(previous.audio)
            self.items[key] = Clip(bytes(audio), self.clock() + self.TTL_SECONDS)
            self.size += len(audio)
            while len(self.items) > self.MAX_ENTRIES or self.size > self.MAX_TOTAL_BYTES:
                _, expired = self.items.popitem(last=False)
                self.size -= len(expired.audio)


cache = GreetingCache()
