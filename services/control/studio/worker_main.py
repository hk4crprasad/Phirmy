"""Dedicated durable worker: python -m studio.worker_main."""
import asyncio
import logging
from pathlib import Path
import signal

from .main import verify_database_schema
from .workers import worker_loop

HEARTBEAT = Path('/tmp/studio-worker-heartbeat')


async def run():
    await asyncio.to_thread(verify_database_schema)
    from .key_provider import warm_active_key
    await asyncio.wait_for(asyncio.to_thread(warm_active_key),15)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(name, stop.set)

    async def heartbeat():
        while not stop.is_set():
            await asyncio.to_thread(HEARTBEAT.touch)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    health = asyncio.create_task(heartbeat())
    try:
        await worker_loop(stop, local_browser_sessions=False)
    finally:
        stop.set()
        await health
        HEARTBEAT.unlink(missing_ok=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
