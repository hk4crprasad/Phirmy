"""Live Qdrant + configured embeddings acceptance using disposable synthetic points.

Creates the configured collection if needed, verifies auth/semantic lookup and
workspace/snapshot isolation, and removes its own test points. No database writes.
"""
import asyncio
import json
import logging
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))
logging.disable(logging.CRITICAL)
import httpx
from studio.config import settings
from studio.retrieval import Qdrant, embed, vector_configured


async def verify():
    if not vector_configured() or not settings.vector_api_key:
        raise RuntimeError('Configure authenticated Qdrant and embeddings first')
    qdrant = Qdrant()
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        denied = await client.get(settings.vector_endpoint.rstrip('/') + '/collections')
        assert denied.status_code in (401, 403), 'Unauthenticated requests must be denied'
    await qdrant.ensure_collection()
    a, b = 'vector-qa-' + uuid4().hex, 'vector-qa-' + uuid4().hex
    current, old, foreign = [str(uuid4()) for _ in range(3)]
    chunks = [{'id': str(uuid4()), 'source_id': str(uuid4())} for _ in range(4)]
    vectors = await embed([
        'Personalized engraving accepts a maximum of twenty characters.',
        'Delivery tracking is available after your order has shipped.',
        'What is the personalization character limit?',
    ])
    scope = {'filter': {'must': [{'key': 'workspace_id', 'match': {'any': [a, b]}}]}}
    try:
        await qdrant.upsert(a, current, chunks[:2], vectors[:2])
        # Identical vectors outside the requested tenant/revision must stay excluded.
        await qdrant.upsert(a, old, [chunks[2]], [vectors[0]])
        await qdrant.upsert(b, foreign, [chunks[3]], [vectors[0]])
        points = await qdrant.search(a, [current], vectors[2])
        assert len(points) == 2 and points[0]['payload']['chunk_id'] == chunks[0]['id']
        assert all(p['payload']['workspace_id'] == a and p['payload']['snapshot_id'] == current for p in points)
        assert not await qdrant.search(a, [foreign], vectors[2])
        assert not await qdrant.search(b, [current], vectors[2])
        result = {'state': 'passed', 'collection': settings.vector_collection, 'dimensions': len(vectors[0]), 'embedding_model': settings.embedding_model,
                  'authentication': 'enforced', 'semantic_ranking': 'passed', 'workspace_and_snapshot_isolation': 'passed'}
    finally:
        await qdrant.request('POST', '/collections/' + qdrant.collection + '/points/delete?wait=true', json=scope)
        remaining = await qdrant.request('POST', '/collections/' + qdrant.collection + '/points/count', json={**scope, 'exact': True})
        assert remaining['result']['count'] == 0, 'Synthetic points were not removed'
    result['synthetic_points_cleanup'] = 'passed'
    path = Path(__file__).resolve().parents[1] / 'artifacts/qdrant-results.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n')
    return result


async def main():
    print(json.dumps(await verify()), flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        # Provider errors can contain request metadata; never dump credential-bearing responses.
        print(json.dumps({'state': 'failed', 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1)
