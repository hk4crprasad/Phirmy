"""Upload database/vector backups to the existing private Azure container."""
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import sys
from urllib.parse import quote

import httpx
from azure.storage.blob import BlobServiceClient

logging.disable(logging.CRITICAL)


def main():
    folder = Path('/backups')
    latest = max(folder.glob('database-*.dump'), key=lambda path: path.name)
    service = BlobServiceClient.from_connection_string(os.environ['AZURE_STORAGE_CONNECTION_STRING'])
    container = service.get_container_client(os.environ['AZURE_STORAGE_CONTAINER'])
    if container.get_container_properties().get('public_access'):
        raise RuntimeError('Backups require a private storage container')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    def upload(path):
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for part in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(part)
        blob = container.get_blob_client('platform-backups/' + stamp + '/' + path.name)
        with path.open('rb') as source:
            blob.upload_blob(source, overwrite=False, metadata={'sha256': digest.hexdigest()})
        assert blob.get_blob_properties().size == path.stat().st_size

    upload(latest)
    with httpx.Client(base_url=os.environ['VECTOR_ENDPOINT'],
                      headers={'api-key': os.environ['VECTOR_API_KEY']}, timeout=120, trust_env=False) as client:
        response = client.get('/collections'); response.raise_for_status()
        collections = response.json()['result']['collections']
        for row in collections:
            name = quote(row['name'], safe='')
            response = client.post('/collections/' + name + '/snapshots'); response.raise_for_status()
            snapshot = quote(response.json()['result']['name'], safe='')
            target = folder / ('vector-' + stamp + '-' + hashlib.sha256(name.encode()).hexdigest()[:12] + '.snapshot')
            with client.stream('GET', '/collections/' + name + '/snapshots/' + snapshot) as response:
                response.raise_for_status()
                with target.open('wb') as output:
                    os.chmod(target, 0o600)
                    for chunk in response.iter_bytes(): output.write(chunk)
            upload(target)
            # Remove only this temporary server-side snapshot after durable upload.
            response = client.delete('/collections/' + name + '/snapshots/' + snapshot)
            response.raise_for_status()
    print('Private Azure backup verified: database and', len(collections), 'vector collections.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Production backup failed:', type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
