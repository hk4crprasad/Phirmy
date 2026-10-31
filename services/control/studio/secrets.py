from cryptography.fernet import Fernet,InvalidToken
from .key_provider import get_provider,legacy_key,valid_id,LEGACY_ID,checked


def cipher():
    """Legacy helper retained for existing unversioned data and integrations."""
    return Fernet(legacy_key())


def encrypt(value,key_id=None):
    provider=get_provider();key_id=valid_id(key_id or provider.active_key_id())
    prefix='vs1:'+key_id+':'
    # Authenticate the ID inside the token as well as the readable envelope.
    token=Fernet(checked(provider.key(key_id))).encrypt((prefix+'\n'+value).encode()).decode()
    return prefix+token


def decrypt(value):
    if not isinstance(value,str):raise InvalidToken()
    if not value.startswith('vs1:'):
        return cipher().decrypt(value.encode()).decode()
    try:
        _,key_id,token=value.split(':',2);valid_id(key_id)
        prefix='vs1:'+key_id+':\n'
        payload=Fernet(checked(get_provider().key(key_id))).decrypt(token.encode()).decode()
        if not payload.startswith(prefix):raise InvalidToken()
        return payload[len(prefix):]
    except (UnicodeError,ValueError) as error:
        if isinstance(error,InvalidToken):raise
        raise InvalidToken() from None


def key_id(value):
    if not value.startswith('vs1:'):return LEGACY_ID
    try:return valid_id(value.split(':',2)[1])
    except (IndexError,ValueError):raise InvalidToken() from None


def reencrypt(value,target_key_id):
    """Preserve the authenticated original timestamp, as Fernet rotation does."""
    plain=decrypt(value);old_id=key_id(value)
    if old_id==target_key_id:return value
    old_token=value.split(':',2)[2] if value.startswith('vs1:') else value
    old_cipher=cipher() if old_id==LEGACY_ID else Fernet(checked(get_provider().key(old_id)))
    timestamp=old_cipher.extract_timestamp(old_token.encode())
    target_key_id=valid_id(target_key_id);prefix='vs1:'+target_key_id+':'
    new_cipher=Fernet(checked(get_provider().key(target_key_id)))
    return prefix+new_cipher.encrypt_at_time((prefix+'\n'+plain).encode(),timestamp).decode()
