import asyncio
import logging
from contextlib import suppress

logger = logging.getLogger(__name__)

_background_tasks = set()

def fire_and_forget(coro):
    """
    Schedules an awaitable to run in the background.
    Useful for non-critical DB updates so they don't block the handler.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if asyncio.iscoroutine(coro):
            coro.close()
        return None  # No running event loop; do not leak an unawaited coroutine.

    async def _runner():
        try:
            if asyncio.iscoroutine(coro):
                await coro
            elif hasattr(coro, '__await__'):
                await coro
        except Exception:
            logger.exception("Ошибка фоновой операции")

    task = loop.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def drain_background_tasks(timeout: float = 5.0):
    """Give best-effort tasks time to finish, then cancel remaining work."""
    tasks = set(_background_tasks)
    if not tasks:
        return
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


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

# Список команд, на которые бот должен реагировать, чтобы не игнорировать их.
ALLOWED_TEXT_COMMANDS = (
    "кусь", "обнять", "поцеловать", "ударить", "диктор", "мут", "бан", "варн",
    "снять варн", "снять", "повысить", "понизить", "админы", "кто админ", "создать банк",
    "выплатить", "вернуть", "кредит", "приветствие", "заметка", "антилинк", "антивойс",
    "био", "+правила", "правила", "+", "спасибо", "реп", "стата", "топ",
    "казино", "блэкджек", "рулетка", "слоты", "кости", "крапс", "банка", "шлюха", "договор",
    "профиль", "банк", "инвентарь", "inv", "inventory", "stocks", "season", "сезон",
    "сделка", "наследство", "ограбить банк", "украсть", "нанять", "заказать", "эскорт",
    "проститут", "топ путан", "топ эскорт", "аудит", "лобби бан", "лобби разбан",
    "брак", "подарок", "развод", "вызвать на дуэль", "дуэль", "бан крипты", "разбан крипты"
)

def is_valid_command(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()

    if text_lower.startswith(('/', '!', '?')):
        return True

    for cmd in ALLOWED_TEXT_COMMANDS:
        if text_lower.startswith(cmd):
            return True

    return False

async def check_maintenance():
    """Checks if maintenance mode is active in the database."""
    from db import get_db
    from utils_pkg.cache_manager import global_cache
    
    cached = global_cache.get("maintenance_mode")
    if cached is not None: return cached
    
    try:
        db = get_db()
        doc = await db.collection('bot_settings').document('maintenance').get()
        status = doc.to_dict().get('active', False) if doc.exists else False
        global_cache.set("maintenance_mode", status, ttl=60)
        return status
    except Exception:
        return False
