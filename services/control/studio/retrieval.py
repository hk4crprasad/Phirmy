"""User-selected embedding and Qdrant infrastructure; no silent production fallback."""
import asyncio
import math
import logging
import sys
from uuid import uuid5, NAMESPACE_URL
from urllib.parse import quote
import httpx
from .config import settings


def vector_configured():
    return bool(settings.vector_endpoint and (settings.embedding_api_key or settings.openai_api_key))


async def embed(texts, client=None):
    if not texts:
        return []
    if settings.embedding_model != "text-embedding-3-small":
        raise RuntimeError("Embedding model must match the user's text-embedding-3-small choice")
    from .cache import get_vectors, put_vectors
    def valid(vector):
        return isinstance(vector, list) and len(vector) == settings.embedding_dimensions and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in vector)
    vectors = await asyncio.to_thread(get_vectors, texts)
    missing = [i for i, value in enumerate(vectors) if not valid(value)]
    if not missing: return vectors
    from openai import AsyncOpenAI
    own = client is None
    from .metering import context,append_cost
    from .admission import provider_hold,provider_release
    from .async_work import durable_to_thread,durable_await
    from .db import uid
    values=dict(context.get());operation_key='embedding:'+uid();units={};source='unreported';started=False
    inputs=[texts[i] for i in missing]
    try:
        await durable_to_thread(provider_hold,values,operation_key,'embedding',
            {'input_tokens':sum(len(value.encode())+32 for value in inputs)})
        if client is None:
            client = AsyncOpenAI(
                api_key=settings.embedding_api_key or settings.openai_api_key,
                base_url=settings.embedding_base_url or "https://api.openai.com/v1",
                timeout=30, max_retries=0,
            )
        started=True
        response = await client.embeddings.create(model=settings.embedding_model, input=inputs, dimensions=settings.embedding_dimensions)
        usage=getattr(response,'usage',None)
        tokens=getattr(usage,'prompt_tokens',None) if not isinstance(usage,dict) else usage.get('prompt_tokens')
        if type(tokens) is int and tokens>=0:units={'input_tokens':tokens};source='provider_usage'
        entries = sorted(response.data, key=lambda x: x.index)
        fresh = [x.embedding for x in entries]
        if len(fresh) != len(inputs) or [x.index for x in entries] != list(range(len(inputs))) or not all(valid(x) for x in fresh):
            raise RuntimeError("Embedding result count/dimension/values do not match configuration")
        for index, vector in zip(missing, fresh, strict=True): vectors[index] = vector
        await asyncio.to_thread(put_vectors, inputs, fresh)
        return vectors
    finally:
        failed=sys.exception() is not None
        try:
            if started:await durable_to_thread(append_cost,values,'embedding','embedding',units,operation_key,source)
            elif values.get('workspace_id'):await durable_to_thread(provider_release,values,operation_key)
        except Exception:
            if not failed:raise
            logging.getLogger(__name__).warning('embedding_settlement_failed')
        finally:
            if own and client is not None:
                try:await durable_await(asyncio.wait_for(client.close(),3))
                except Exception:logging.getLogger(__name__).warning('embedding_client_close_failed')


class Qdrant:
    def __init__(self, client=None):
        self.client = client
        self.base = settings.vector_endpoint.rstrip("/")
        self.collection = quote(settings.vector_collection, safe="")

    async def request(self, method, path, **kwargs):
        headers = {"api-key": settings.vector_api_key} if settings.vector_api_key else {}
        if self.client:
            response = await self.client.request(method, self.base + path, headers=headers, **kwargs)
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(method, self.base + path, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    async def ensure_collection(self):
        async def validate_existing():
            data = await self.request("GET", "/collections/" + self.collection)
            vectors = data["result"]["config"]["params"]["vectors"]
            if vectors.get("size") != settings.embedding_dimensions or vectors.get("distance", "").lower() != "cosine":
                raise RuntimeError("Existing Qdrant collection has incompatible vector dimensions/distance")
        try:
            await validate_existing()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            try:
                await self.request("PUT", "/collections/" + self.collection, json={"vectors": {"size": settings.embedding_dimensions, "distance": "Cosine"}})
            except httpx.HTTPStatusError as race:
                if race.response.status_code not in {400,409}:raise
                # Another worker may have created it after our GET. Read back
                # and validate the actual schema; never accept a failed PUT alone.
                await validate_existing()
        for field in ("workspace_id", "snapshot_id"):
            await self.request("PUT", "/collections/" + self.collection + "/index?wait=true", json={"field_name": field, "field_schema": "keyword"})

    async def upsert(self, workspace_id, snapshot_id, chunks, vectors):
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            points.append({"id": str(uuid5(NAMESPACE_URL, snapshot_id + ":" + chunk["id"])), "vector": vector,
                           "payload": {"workspace_id": workspace_id, "snapshot_id": snapshot_id, "chunk_id": chunk["id"], "source_id": chunk["source_id"]}})
        if points:
            await self.request("PUT", "/collections/" + self.collection + "/points?wait=true", json={"points": points})

    async def search(self, workspace_id, snapshot_ids, vector, limit=20):
        if not snapshot_ids:
            return []
        data = await self.request("POST", "/collections/" + self.collection + "/points/query", json={
            "query": vector, "filter": {"must": [{"key": "workspace_id", "match": {"value": workspace_id}}, {"key": "snapshot_id", "match": {"any": snapshot_ids}}]},
            "limit": limit, "with_payload": True, "with_vector": False,
        })
        points = data["result"]["points"]
        for point in points:
            payload = point["payload"]
            if payload.get("workspace_id") != workspace_id or payload.get("snapshot_id") not in snapshot_ids:
                raise RuntimeError("Vector backend returned an out-of-scope point")
        return points
