from types import SimpleNamespace
import asyncio
import hashlib
import json
import numpy as np
import httpx
import pytest
from studio.config import settings
from studio.storage import AzureBlobObjectStore, LocalObjectStore, object_key
from studio.retrieval import Qdrant, embed
from studio.carrier import mulaw_encode, mulaw_decode
from studio.db import session_scope, now, uid
from studio.models import Job, KnowledgeBase, Snapshot
from studio.domain import enqueue
from studio.workers import execute_job


def test_local_object_store_is_private_and_content_addressed(tmp_path):
    store = LocalObjectStore(tmp_path)
    key = store.put("workspace-a", "documents", b"private-document", "text/plain")
    assert key == store.put("workspace-a", "documents", b"private-document", "text/plain")
    assert store.get("workspace-a", key) == b"private-document"
    with pytest.raises(PermissionError):
        store.get("workspace-b", key)
    with pytest.raises(PermissionError):
        store.get("workspace-a", "workspace-a/../../etc/passwd")
    store.delete("workspace-a", key)
    with pytest.raises(FileNotFoundError):
        store.get("workspace-a", key)


def test_azure_adapter_uses_workspace_key_and_content_type():
    blobs = {}
    class Container:
        def upload_blob(self, key, body, **options):
            assert options["content_settings"].content_type == "text/plain"
            blobs[key] = body
        def download_blob(self, key):
            return SimpleNamespace(readall=lambda: blobs[key])
        def delete_blob(self, key):
            blobs.pop(key)
    class Client:
        def get_container_client(self, name):
            assert name == settings.azure_storage_container
            return Container()
    store = AzureBlobObjectStore(Client())
    key = store.put("workspace-a", "documents", b"Azure fixture", "text/plain")
    assert key.startswith("workspace-a/documents/")
    assert store.get("workspace-a", key) == b"Azure fixture"
    with pytest.raises(PermissionError):
        store.get("workspace-b", key)
    store.delete("workspace-a", key)
    assert not blobs


def test_azure_prefix_preserves_logical_tenant_keys(monkeypatch):
    monkeypatch.setattr(settings,'azure_storage_prefix','platform/production/')
    blobs={}
    class Container:
        def upload_blob(self,key,body,**kwargs):blobs[key]=body
        def download_blob(self,key):return SimpleNamespace(readall=lambda:blobs[key])
        def delete_blob(self,key):blobs.pop(key)
    class Client:
        def get_container_client(self,name):return Container()
    store=AzureBlobObjectStore(Client())
    key=store.put('workspace-a','exports',b'payload','text/plain')
    assert key.startswith('workspace-a/') and list(blobs)==['platform/production/'+key]
    assert store.get('workspace-a',key)==b'payload'
    with pytest.raises(PermissionError):store.get('workspace-b',key)
    store.delete('workspace-a',key);assert not blobs
    monkeypatch.setattr(settings,'azure_storage_prefix','../escape')
    with pytest.raises(ValueError):AzureBlobObjectStore(Client())


def test_chat_model_env_alias(monkeypatch):
    from studio.config import Settings
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    monkeypatch.setenv('OPENAI_CHAT_MODEL','gpt-6-luna')
    assert Settings(_env_file=None).openai_model=='gpt-6-luna'
    monkeypatch.setenv('OPENAI_MODEL','canonical-deployment')
    assert Settings(_env_file=None).openai_model=='canonical-deployment'


def test_requested_fish_model_is_published_in_agent_defaults(monkeypatch,account):
    from studio.domain import default_agent,validate_agent
    monkeypatch.setattr(settings,'fish_tts_model','drama-3')
    config=default_agent()
    assert config['speech']['model']=='drama-3'
    with session_scope() as db:assert validate_agent(db,account[1],config)==[]


@pytest.mark.asyncio
async def test_qdrant_filter_is_mandatory_and_result_revalidated(monkeypatch):
    monkeypatch.setattr(settings, "vector_endpoint", "https://qdrant.example.test")
    seen = []
    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx.Response(200, json={"result": {"points": [{"id": uid(), "score": .9, "payload": {"workspace_id": "tenant-a", "snapshot_id": "snap-1", "chunk_id": uid()}}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await Qdrant(client).search("tenant-a", ["snap-1"], [0.1] * 1536)
    must = seen[0]["filter"]["must"]
    assert must == [{"key": "workspace_id", "match": {"value": "tenant-a"}}, {"key": "snapshot_id", "match": {"any": ["snap-1"]}}]
    assert len(results) == 1
    def corrupt(request):
        return httpx.Response(200, json={"result": {"points": [{"score": .9, "payload": {"workspace_id": "tenant-b", "snapshot_id": "snap-1", "chunk_id": uid()}}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(corrupt)) as client:
        with pytest.raises(RuntimeError, match="out-of-scope"):
            await Qdrant(client).search("tenant-a", ["snap-1"], [0.1] * 1536)


@pytest.mark.asyncio
async def test_qdrant_existing_collection_dimension_mismatch_fails(monkeypatch):
    monkeypatch.setattr(settings, "vector_endpoint", "https://qdrant.example.test")
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"result": {"config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="incompatible"):
            await Qdrant(client).ensure_collection()


@pytest.mark.asyncio
async def test_embedding_dimension_and_order_validation():
    class Embeddings:
        async def create(self, **kwargs):
            assert kwargs["model"] == "text-embedding-3-small"
            assert kwargs["dimensions"] == 1536
            return SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[.2] * 1536), SimpleNamespace(index=0, embedding=[.1] * 1536)])
    vectors = await embed(["one", "two"], SimpleNamespace(embeddings=Embeddings()))
    assert vectors[0][0] == .1
    class Invalid:
        async def create(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[float("nan")] * 1536)])
    with pytest.raises(RuntimeError, match="dimension/values"):
        await embed(["one"], SimpleNamespace(embeddings=Invalid()))


def test_mulaw_reference_codes_and_signal_error():
    assert mulaw_encode(np.array([0, 32767, -32768], dtype=np.int16)) == bytes([255, 128, 0])
    assert list(mulaw_decode(bytes([255, 128, 0]))) == [0, 32124, -32124]
    source = (np.sin(np.arange(8000) * 2 * np.pi * 440 / 8000) * 10000).astype(np.int16)
    reconstructed = mulaw_decode(mulaw_encode(source))
    assert np.mean((source.astype(float) - reconstructed) ** 2) ** .5 < 180


def test_streaming_resampler_preserves_sample_count():
    import soxr
    source = np.zeros(24000, dtype=np.int16)
    stream = soxr.ResampleStream(24000, 8000, 1, dtype="int16", quality="LQ")
    chunks = [stream.resample_chunk(source[i:i + 480], last=i + 480 >= len(source)) for i in range(0, len(source), 480)]
    assert sum(len(x) for x in chunks) == 8000


@pytest.mark.asyncio
async def test_crawl_canonicalizes_and_publishes_with_azure_storage_interface(account, monkeypatch):
    client, ws, base = account
    import studio.knowledge as knowledge
    async def validate(url):
        return None
    async def fetch(url, *args, **kwargs):
        if url.endswith("/robots.txt"):
            return url, b"User-agent: *\nAllow: /", "text/plain"
        if "/policy" in url:
            return url, b"<html><title>Policy</title><main>Delivery normally takes 5 business days.</main></html>", "text/html"
        return "https://example.test/", b'<html><title>Store</title><main>Custom cufflinks engraving supports 20 characters.</main><a href="/">Home</a><a href="/?utm_source=test">Home alias</a><a href="/policy">Delivery</a></html>', "text/html"
    monkeypatch.setattr(knowledge, "validate_public_url", validate)
    monkeypatch.setattr(knowledge, "safe_fetch", fetch)
    with session_scope(write=True) as db:
        kb = KnowledgeBase(workspace_id=ws, name="Crawl QA", website_url="https://example.test/")
        db.add(kb); db.flush()
        kb_id = kb.id
        job = enqueue(db, ws, "crawl", {"kb_id": kb.id, "max_pages": 5})
        job_id = job.id
    await execute_job(job_id)
    with session_scope() as db:
        job = db.get(Job, job_id)
        assert job.state == "completed", job.error
        kb = db.get(KnowledgeBase, kb_id)
        assert kb.pages_indexed == 2
        assert kb.active_snapshot_id
        assert db.get(Snapshot, kb.active_snapshot_id).state == "published"


@pytest.mark.asyncio
async def test_failed_recrawl_keeps_previous_snapshot(sample, monkeypatch):
    client, ws, base, fixture = sample
    import studio.knowledge as knowledge
    before = client.get(base + "/knowledge/" + fixture["kb_id"]).json()["active_snapshot_id"]
    async def fail(url):
        raise ValueError("Extraction unavailable")
    monkeypatch.setattr(knowledge, "validate_public_url", fail)
    with session_scope(write=True) as db:
        job = enqueue(db, ws, "crawl", {"kb_id": fixture["kb_id"], "max_pages": 3})
        job_id = job.id
    await execute_job(job_id)
    kb = client.get(base + "/knowledge/" + fixture["kb_id"]).json()
    assert kb["active_snapshot_id"] == before
    assert kb["status"] == "ready"
    assert client.get(base + "/jobs/" + job_id).json()["state"] == "failed"


def test_azure_content_addressed_upload_never_overwrites_existing_blob():
    from azure.core.exceptions import ResourceExistsError
    attempts = []
    class Container:
        def upload_blob(self, key, body, **kwargs):
            assert kwargs['overwrite'] is False
            attempts.append(key)
            if len(attempts) > 1: raise ResourceExistsError('Already stored')
    class Client:
        def get_container_client(self, name): return Container()
    store = AzureBlobObjectStore(Client())
    first = store.put('workspace', 'snapshots', b'same', 'text/html')
    assert store.put('workspace', 'snapshots', b'same', 'text/html') == first


@pytest.mark.asyncio
async def test_pooled_fetch_gates_every_request_including_redirects(monkeypatch):
    from studio import knowledge
    calls, gates = [], []
    async def validate(url): assert url.startswith('https://fixture.example/')
    async def gate(): gates.append(True)
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302,headers={'Location':'/final'}) if request.url.path=='/' else httpx.Response(200,text='evidence')
    monkeypatch.setattr(knowledge, 'validate_public_url', validate)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        token=knowledge.fetch_context.set({'client':client,'before_request':gate})
        try:
            final, body, _ = await knowledge.safe_fetch('https://fixture.example/', same_origin=('https','fixture.example'))
            assert final=='https://fixture.example/final' and body==b'evidence'
            assert len(calls)==len(gates)==2
            assert not client.is_closed
        finally: knowledge.fetch_context.reset(token)
