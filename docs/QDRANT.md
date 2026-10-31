# Self-hosted Qdrant

The local instance runs **Qdrant v1.19.2**, with authenticated REST at `http://127.0.0.1:6333` and the dashboard at `http://127.0.0.1:6333/dashboard`. Its API key is saved privately as `VECTOR_API_KEY` in `.env`. No key is included in this guide, container commands or source exports. The collection is `voice-studio`, using cosine distance and1536-dimensional Azure `text-embedding-3-small` vectors.

## Local Podman service

Docker daemon access is unavailable to the current user, so this machine uses rootless Podman with a systemd user Quadlet. To reproduce on a Linux machine with Podman and a user systemd session:

```sh
uv sync --frozen
uv run python scripts/setup_qdrant.py
systemctl --user status voice-studio-qdrant.service
```

The setup command preserves an existing vector key or generates one, updates only vector settings in `.env`, saves a mode0600 service environment file, and installs `deploy/qdrant.container` under `~/.config/containers/systemd/voice-studio-qdrant.container`. Only the Qdrant key and telemetry setting reach this container; other provider credentials are not passed to it.

The service environment is `~/.config/voice-studio/qdrant.env`. Qdrant is limited to2 CPUs/2GiB RAM, has dropped Linux capabilities, a readiness health check and automatic failure restart. Only REST6333 is published, bound to loopback. gRPC and cluster ports are not published.

On this host, user lingering is enabled, so its generated default-target unit starts at boot and stays available after logout. On another host, enable it if needed:

```sh
loginctl enable-linger "$USER"
```

Manage the service without deleting its data:

```sh
systemctl --user restart voice-studio-qdrant.service
systemctl --user stop voice-studio-qdrant.service
systemctl --user start voice-studio-qdrant.service
```

Named volumes `voice-studio-qdrant-data` and `voice-studio-qdrant-snapshots` preserve `/qdrant/storage` and `/qdrant/snapshots`. Live vector database files require a local persistent filesystem; raw source objects remain in Azure and metadata/chunks in Supabase. The index can be rebuilt from those records. Automatic snapshot export/restore drills and multi-node availability are still production work.

## Docker Compose deployment

If Docker is available, configure just its Qdrant service with:

```sh
uv run python scripts/setup_qdrant.py --runtime docker
docker compose config --quiet
```

The full Compose stack overrides the API endpoint to `http://qdrant:6333`, waits for Qdrant readiness, and uses the same private `VECTOR_API_KEY`. A host-run API uses `http://127.0.0.1:6333`. Restart the API after environment changes. Do not run both runtimes on port6333; Docker and Podman have separate volumes, so switching runtimes requires backfill or snapshot restore. Full API/web Docker images remain unverified on this machine; the Qdrant Podman image was actually run.

Do not print expanded `docker compose config` or container environments because they contain credentials. The `--quiet` validation above avoids that output.

## Index and verify

```sh
uv run python scripts/reindex_knowledge.py
uv run python scripts/reindex_knowledge.py --apply
uv run python scripts/verify_qdrant.py
```

The first command is a dry run. `--apply` indexes all published revisions, including revisions pinned by existing agents, in the existing32-chunk embedding batches. Stable point IDs make retries idempotent. Both indexing and acceptance use the configured embedding API and may consume embedding credits.

The live verifier creates disposable synthetic points in the configured collection, tests authentication, semantic ranking, mandatory workspace/snapshot filters, and removes its test points even on failure. It never writes application database rows. `scripts/verify_providers.py` now also checks Qdrant when configured.

Accepted on22 October2026: all14 existing published snapshots backfilled,29 points persisted, repeat indexing did not duplicate points, application retrieval returned `qdrant-hybrid`, unavailable Qdrant raised a connection error, and persisted retrieval recovered after a service restart. Live semantic ranking and tenant/revision isolation passed using the real Azure embedding endpoint. Artifacts: `artifacts/qdrant-results.json` and `artifacts/qdrant-deployment-results.json`. Full isolated application suite:85 passed.

## Upstream references

- [Pinned Qdrant release](https://github.com/qdrant/qdrant/releases/tag/v1.19.2)
- [Installation and persistent storage](https://qdrant.tech/documentation/installation/)
- [API keys and network binding](https://qdrant.tech/documentation/security/)

For deployment beyond this machine, use a private network/TLS and complete backup/restore and capacity acceptance before public production use.
