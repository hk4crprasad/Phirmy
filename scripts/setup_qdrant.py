"""Provision local Qdrant without displaying credentials or changing Docker permissions.

Run from this repository with `uv run python scripts/setup_qdrant.py`.
The default installs a rootless Podman Quadlet; --runtime docker uses Compose.
"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import time

from dotenv import dotenv_values, set_key
import httpx

ROOT = Path(__file__).resolve().parents[1]


def private_write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(body)
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', choices=['podman', 'docker'], default='podman')
    args = parser.parse_args()
    # Fail before changing config if the selected runtime is inaccessible.
    check = ['podman', 'info', '--format', '{{.Host.Security.Rootless}}'] if args.runtime == 'podman' else ['docker', 'info', '--format', '{{.ServerVersion}}']
    subprocess.run(check, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = ROOT / '.env'
    if not env.exists():
        private_write(env, (ROOT / '.env.example').read_text())
    values = dotenv_values(env)
    key = values.get('VECTOR_API_KEY') or secrets.token_urlsafe(48)
    # Refuse arbitrary line breaks before writing a container environment file.
    if any(c in key for c in '\r\n\0'):
        raise RuntimeError('Invalid VECTOR_API_KEY format')
    for name, value in {'VECTOR_PROVIDER': 'qdrant', 'VECTOR_ENDPOINT': 'http://127.0.0.1:6333', 'VECTOR_API_KEY': key, 'VECTOR_COLLECTION': values.get('VECTOR_COLLECTION') or 'voice-studio'}.items():
        set_key(str(env), name, value)
    env.chmod(0o600)

    if args.runtime == 'podman':
        private_write(Path.home() / '.config/voice-studio/qdrant.env', 'QDRANT__SERVICE__API_KEY=' + key + '\nQDRANT__TELEMETRY_DISABLED=true\n')
        unit = Path.home() / '.config/containers/systemd/voice-studio-qdrant.container'
        if unit.exists() and 'Managed by nutaan-platform/' not in unit.read_text():
            raise RuntimeError('An unmanaged Quadlet already exists; it was not overwritten')
        private_write(unit, (ROOT / 'deploy/qdrant.container').read_text())
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', '--user', 'restart', '--no-block', 'voice-studio-qdrant.service'], check=True)
    else:
        subprocess.run(['docker', 'compose', 'up', '-d', 'qdrant'], cwd=ROOT, check=True)

    with httpx.Client(timeout=3, trust_env=False) as client:
        for _ in range(150):
            try:
                ready = client.get('http://127.0.0.1:6333/readyz')
                authenticated = client.get('http://127.0.0.1:6333/collections', headers={'api-key': key})
                if ready.status_code == 200 and authenticated.status_code == 200:
                    denied = client.get('http://127.0.0.1:6333/collections')
                    if denied.status_code not in (401, 403):
                        raise RuntimeError('Qdrant did not enforce authentication')
                    print('Qdrant ready on 127.0.0.1:6333; authentication enforced; configuration saved privately.')
                    print('Restart the host API to load its new vector settings. Compose uses http://qdrant:6333 internally.')
                    return
            except httpx.TransportError:
                pass
            time.sleep(1)
    raise RuntimeError('Qdrant did not become ready; inspect the service logs without printing environment values')


if __name__ == '__main__':
    main()
