"""Actual local Redis and Qdrant contracts with synthetic vectors; no model calls.

For real provider embeddings/semantic ranking run verify_qdrant.py separately.
Only this run's temporary cache keys and Qdrant points are removed.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))
import httpx
from studio.config import settings
from studio import cache
from studio.retrieval import embed, Qdrant


async def verify():
    redis = cache.connection(settings.redis_url)
    assert await asyncio.to_thread(redis.ping)
    marker = 'synthetic-index-' + uuid4().hex
    texts = [marker + '-a', marker + '-b']
    calls = []
    async def create(**kwargs):
        calls.append(kwargs['input'])
        vectors = []
        for i in range(len(kwargs['input'])):
            vector = [0.] * settings.embedding_dimensions; vector[i] = 1.
            vectors.append(SimpleNamespace(index=i, embedding=vector))
        return SimpleNamespace(data=vectors)
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    qdrant = Qdrant()
    ws, foreign, snapshot = marker, marker+'-foreign', str(uuid4())
    scope = {'filter': {'must': [{'key': 'workspace_id', 'match': {'any': [ws, foreign]}}]}}
    try:
        first = await embed(texts, client)
        second = await embed(texts, client)
        assert first == second and len(calls) == 1
        for text in texts: assert await asyncio.to_thread(redis.ttl, cache.cache_key(text)) > 0
        async with httpx.AsyncClient(trust_env=False) as http:
            response = await http.get(settings.vector_endpoint.rstrip('/')+'/collections')
            assert response.status_code in (401,403)
        await qdrant.ensure_collection()
        chunks = [{'id': str(uuid4()), 'source_id': str(uuid4())} for _ in texts]
        await qdrant.upsert(ws, snapshot, chunks, first)
        await qdrant.upsert(foreign, snapshot, [{'id':str(uuid4()), 'source_id':str(uuid4())} for _ in texts], first)
        points = await qdrant.search(ws, [snapshot], first[0])
        assert len(points) == 2 and points[0]['payload']['chunk_id'] == chunks[0]['id']
        assert not await qdrant.search(ws, [str(uuid4())], first[0])
        assert all(p['payload']['workspace_id'] == ws for p in points)
        result = {'redis': 'passed', 'embedding_cache': 'warm reuse and TTL passed; synthetic provider',
                  'qdrant_authentication': 'passed', 'qdrant_insert_search': 'passed; synthetic vectors',
                  'workspace_and_revision_isolation': 'passed'}
    finally:
        await asyncio.to_thread(redis.delete, *(cache.cache_key(text) for text in texts))
        await qdrant.request('POST', '/collections/'+qdrant.collection+'/points/delete?wait=true', json=scope)
        remaining = await qdrant.request('POST', '/collections/'+qdrant.collection+'/points/count', json={**scope, 'exact': True})
        assert remaining['result']['count'] == 0
    result['cleanup'] = 'passed'
    path = Path('artifacts/local-index-results.json'); path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))

if __name__ == '__main__':
    try: asyncio.run(verify())
    except Exception as exc:
        print(json.dumps({'state': 'failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
