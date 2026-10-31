"""Prepare private Redis cache settings, preserving all existing .env values."""
from pathlib import Path
import io
import secrets
from urllib.parse import quote
from dotenv import dotenv_values


def configure(path=Path('.env')):
    text = path.read_text() if path.exists() else ''
    values = dotenv_values(stream=io.StringIO(text))
    password = values.get('REDIS_PASSWORD') or secrets.token_urlsafe(32)
    additions = {'REDIS_PASSWORD': password, 'REDIS_URL': 'redis://:'+quote(password, safe='')+'@127.0.0.1:6379/0'}
    lines = text.splitlines()
    for name, value in additions.items():
        if values.get(name): continue
        existing = next((i for i,line in enumerate(lines) if line.startswith(name+'=')), None)
        if existing is None: lines.append(name+'='+value)
        else: lines[existing] = name+'='+value
    output = '\n'.join(lines)+'\n'
    if output != text: path.write_text(output)
    path.chmod(0o600)
    print('Private Redis settings prepared; existing values preserved.')


if __name__ == '__main__': configure()
