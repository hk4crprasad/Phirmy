"""Pluggable version-pinned encryption key material. Never expose key values."""
import base64
import hashlib
import json
import re
import threading
import time
from typing import Protocol
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from .config import settings

LEGACY_ID='legacy-app'
_known={}
_known_lock=threading.RLock()


class KeyUnavailable(ValueError):pass


class KeyProvider(Protocol):
    def active_key_id(self) -> str: ...
    def key(self,key_id: str) -> bytes: ...


def valid_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
        raise KeyUnavailable('Invalid encryption key ID')
    return value


def legacy_key():
    return base64.urlsafe_b64encode(hashlib.sha256(('connection-secrets:'+settings.app_secret).encode()).digest())


def checked(value):
    try:
        value=value.encode() if isinstance(value,str) else value
        Fernet(value)
        with _known_lock:
            if len(_known)>=128:_known.pop(next(iter(_known)))
            _known[value]=None
        return value
    except (ValueError,TypeError):raise KeyUnavailable('Encryption key material is unavailable or invalid') from None


def known_materials():
    with _known_lock:return [value.decode() for value in _known]


def warm_active_key():
    selected=get_provider();checked(selected.key(selected.active_key_id()))


class LocalKeyProvider:
    def active_key_id(self):return valid_id(settings.cipher_active_key_id)
    def key(self,key_id):
        valid_id(key_id)
        if key_id in {LEGACY_ID,'app-v1'}:return legacy_key()
        try:keys=json.loads(settings.cipher_keys_json) if settings.cipher_keys_json else {}
        except (ValueError,TypeError):raise KeyUnavailable('Encryption key configuration is invalid') from None
        if not isinstance(keys,dict):raise KeyUnavailable('Encryption key configuration is invalid')
        if key_id in keys:return checked(keys[key_id])
        # Existing installations keep their stable application-root material.
        raise KeyUnavailable('Encryption key ID is unavailable')


class AzureVaultKeyProvider:
    """Key ID is an immutable Vault secret version, never the latest alias."""
    def __init__(self,client=None):
        self.client=client;self.cache={};self.lock=threading.RLock()
    def active_key_id(self):
        identity=valid_id(settings.cipher_active_key_id)
        if identity in {LEGACY_ID,'app-v1'}:raise KeyUnavailable('Select an immutable Vault secret version as the active key ID')
        return identity
    def key(self,key_id):
        valid_id(key_id)
        if key_id==LEGACY_ID:return legacy_key()
        # app-v1 was originally derived from APP_SECRET and remains readable.
        if key_id=='app-v1':return legacy_key()
        with self.lock:
            cached=self.cache.get(key_id)
            if cached and cached[0]>time.monotonic():return cached[1]
            try:
                if self.client is None:
                    parsed=urlsplit(settings.cipher_vault_url)
                    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None,443}:
                        raise KeyUnavailable('Configure a valid HTTPS key vault')
                    from azure.identity import DefaultAzureCredential
                    from azure.keyvault.secrets import SecretClient
                    self.client=SecretClient(vault_url=settings.cipher_vault_url,
                        credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
                        connection_timeout=3,read_timeout=5,retry_total=0)
                secret=self.client.get_secret(settings.cipher_vault_secret_name,version=key_id)
                material=checked(secret.value)
            except Exception:raise KeyUnavailable('Versioned encryption key is unavailable') from None
            if len(self.cache)>=64:self.cache.pop(next(iter(self.cache)))
            self.cache[key_id]=(time.monotonic()+300,material)
            return material


provider: KeyProvider | None=None
local=LocalKeyProvider()
vault=None
vault_configuration=None


def get_provider():
    global vault,vault_configuration
    if provider is not None:return provider
    if settings.cipher_key_provider=='local':return local
    configuration=(settings.cipher_vault_url,settings.cipher_vault_secret_name)
    if vault is None or configuration!=vault_configuration:
        vault=AzureVaultKeyProvider();vault_configuration=configuration
    return vault
