"""Optional Redis cache for derived embedding vectors, never authorization state."""
from functools import lru_cache
import hashlib
import hmac
import json
import threading
import time
from .config import settings

_retry_at = 0.0
_guard = threading.Lock()


@lru_cache(maxsize=4)
def connection(url):
    from redis import Redis
    return Redis.from_url(url, socket_connect_timeout=.25, socket_timeout=.25, retry_on_timeout=False, max_connections=8)


def cache_key(text):
    # Opaque, credential/provider/model-specific keys; no source text in Redis keys.
    scope = json.dumps([settings.embedding_base_url, settings.embedding_model, settings.embedding_dimensions,
                        settings.embedding_api_key or settings.openai_api_key, text], separators=(',', ':'))
    digest = hmac.new(settings.app_secret.encode(), scope.encode(), hashlib.sha256).hexdigest()
    return 'studio:embedding:v1:' + digest


def available():
    return bool(settings.redis_url) and time.monotonic() >= _retry_at


def failed():
    global _retry_at
    with _guard:
        _retry_at = time.monotonic() + 5


def get_vectors(texts):
    if not available(): return [None] * len(texts)
    try:
        values = connection(settings.redis_url).mget([cache_key(x) for x in texts])
        result = []
        for value in values:
            try: result.append(json.loads(value) if value else None)
            except (ValueError, TypeError): result.append(None)
        return result
    except Exception:
        failed()
        return [None] * len(texts)


def put_vectors(texts, vectors):
    if not available(): return
    try:
        pipeline = connection(settings.redis_url).pipeline(transaction=False)
        for text, vector in zip(texts, vectors, strict=True):
            pipeline.set(cache_key(text), json.dumps(vector, allow_nan=False), ex=settings.embedding_cache_seconds)
        pipeline.execute()
    except Exception:
        failed()
