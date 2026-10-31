"""Job fencing and per-process async resource limits shared by worker slots."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from weakref import WeakKeyDictionary

claim = ContextVar('worker_job_claim', default=None)
_slots = WeakKeyDictionary()


class LeaseLost(Exception):
    pass


def check_lease(job):
    current = claim.get()
    if current and (not job or (job.id == current[0] and job.lease_token != current[1])):
        raise LeaseLost('Job lease belongs to another worker')
    return job


def get_job(db, job_id):
    from .models import Job
    # Fence checkpoint/publication transactions against a replacement claim.
    return check_lease(db.get(Job, job_id, with_for_update=bool(claim.get()), populate_existing=bool(claim.get())))


@asynccontextmanager
async def resource_slot(name, limit):
    loop = asyncio.get_running_loop()
    limits = _slots.setdefault(loop, {})
    semaphore = limits.setdefault((name, limit), asyncio.Semaphore(limit))
    async with semaphore:
        yield
