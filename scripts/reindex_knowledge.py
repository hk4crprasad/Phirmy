"""Backfill existing published knowledge snapshots into configured Qdrant.

Default is a dry run. --apply uses the configured embedding provider and may
consume embedding credits. Deterministic IDs make retries idempotent.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))
logging.disable(logging.CRITICAL)
from sqlalchemy import select
from studio.db import session_scope
from studio.models import Snapshot
from studio.knowledge import index_snapshot
from studio.retrieval import vector_configured


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with session_scope() as db:
        snapshots = list(db.execute(select(Snapshot.workspace_id, Snapshot.id).where(Snapshot.state == 'published').order_by(Snapshot.created_at)))
    print(json.dumps({'published_snapshots': len(snapshots), 'apply': args.apply}), flush=True)
    if not args.apply:
        return
    if not vector_configured():
        raise RuntimeError('Configure Qdrant and embeddings before reindexing')
    for index, (workspace_id, snapshot_id) in enumerate(snapshots, 1):
        await index_snapshot(workspace_id, snapshot_id)
        print(json.dumps({'indexed_snapshots': index, 'total_snapshots': len(snapshots)}), flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'state': 'failed', 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1)
