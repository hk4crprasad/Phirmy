from types import SimpleNamespace
import pytest
from studio import cache
from studio.config import settings
from studio.retrieval import embed


class MemoryRedis:
    def __init__(self): self.values = {}; self.ttls = []
    def mget(self, keys): return [self.values.get(key) for key in keys]
    def pipeline(self, **kwargs): return self
    def set(self, key, value, ex): self.values[key] = value; self.ttls.append(ex)
    def execute(self): pass


@pytest.mark.asyncio
async def test_embedding_cache_reuses_vectors_and_isolates_provider_configuration(monkeypatch):
    redis = MemoryRedis()
    monkeypatch.setattr(settings, 'redis_url', 'redis://fixture')
    monkeypatch.setattr(settings, 'embedding_dimensions', 2)
    monkeypatch.setattr(cache, '_retry_at', 0)
    monkeypatch.setattr(cache, 'connection', lambda _: redis)
    calls = []
    async def create(**kwargs):
        calls.append(kwargs['input'])
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0, .5]) for i in range(len(kwargs['input']))])
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    assert await embed(['private source'], client) == [[1., .5]]
    assert await embed(['private source', 'new passage'], client) == [[1., .5], [1., .5]]
    assert calls == [['private source'], ['new passage']]
    assert all('private' not in key for key in redis.values)
    assert redis.ttls == [settings.embedding_cache_seconds] * 2
    monkeypatch.setattr(settings, 'embedding_base_url', 'https://another-provider.example/v1')
    await embed(['private source'], client)
    assert calls[-1] == ['private source'] and len(calls) == 3


@pytest.mark.asyncio
async def test_cache_failure_and_malformed_vectors_never_break_embeddings(monkeypatch):
    monkeypatch.setattr(settings, 'redis_url', 'redis://fixture')
    monkeypatch.setattr(settings, 'embedding_dimensions', 2)
    monkeypatch.setattr(cache, '_retry_at', 0)
    redis = MemoryRedis(); redis.values[cache.cache_key('text')] = '[1]'
    monkeypatch.setattr(cache, 'connection', lambda _: redis)
    async def create(**kwargs): return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[.5, .5])])
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    assert await embed(['text'], client) == [[.5, .5]]
    def unavailable(_): raise ConnectionError('unavailable')
    monkeypatch.setattr(cache, 'connection', unavailable)
    assert await embed(['another'], client) == [[.5, .5]]
