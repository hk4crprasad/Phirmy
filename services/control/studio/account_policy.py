from contextlib import contextmanager
import secrets
import time

from fastapi import HTTPException
from .config import settings


def verification_required():
    return settings.app_env == 'production' or settings.require_email_verification


def require_verified(db, user):
    from .sessions import profile_for
    if verification_required() and profile_for(db, user.id).email_verified_at is None:
        raise HTTPException(403, {'code': 'email_verification_required', 'message': 'Verify your email first'})


def complete_registration(db, user):
    from sqlalchemy import select
    from .models import PendingRegistration, User
    from .auth_routes import create_workspace
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    pending = db.scalar(select(PendingRegistration).where(PendingRegistration.user_id == user.id))
    if pending is None:
        return None
    workspace = create_workspace(db, user, pending.workspace_name)
    db.delete(pending)
    return workspace.id


@contextmanager
def uniform_auth_response():
    # Identical Argon2 work is also performed by both account-existence paths.
    start = time.monotonic()
    floor = settings.auth_response_floor_ms / 1000 + secrets.randbelow(21) / 1000
    try:
        yield
    finally:
        remaining = floor - (time.monotonic() - start)
        if remaining > 0:
            time.sleep(remaining)
