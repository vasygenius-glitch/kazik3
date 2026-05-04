import asyncio
from contextlib import suppress

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
