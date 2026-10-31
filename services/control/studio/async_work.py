"""Observe a durable transaction's outcome even if its async caller is canceled."""
import asyncio


async def durable_await(awaitable):
    transaction=asyncio.ensure_future(awaitable)
    cancellation=None
    while True:
        try:
            result=await asyncio.shield(transaction)
            break
        except asyncio.CancelledError as exc:
            if transaction.cancelled():raise
            cancellation=exc
        except Exception:
            if cancellation is not None:raise cancellation
            raise
    if cancellation is not None:raise cancellation
    return result


async def durable_to_thread(function, *args, **kwargs):
    return await durable_await(asyncio.to_thread(function,*args,**kwargs))
