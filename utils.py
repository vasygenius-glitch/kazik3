import asyncio
from contextlib import suppress

_background_tasks = set()

def fire_and_forget(coro):
    """
    Schedules an awaitable to run in the background.
    Useful for non-critical DB updates so they don't block the handler.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # No running event loop

    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

async def schedule_delete(*messages, delay: int = 40):
    """
    Schedules the deletion of one or more messages after a specified delay.

    :param messages: The message objects to be deleted.
    :param delay: The delay in seconds before deletion. Default is 40.
    """
    await asyncio.sleep(delay)
    for msg in messages:
        if msg and hasattr(msg, 'delete'):
            with suppress(Exception):
                await msg.delete()
