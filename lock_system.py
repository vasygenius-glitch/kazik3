from db import get_db

_lock_cache = None

async def get_locked_chats() -> list:
    global _lock_cache
    if _lock_cache is not None:
        return _lock_cache

    db = get_db()
    ref = db.collection('bot_settings').document('locked')
    doc = await ref.get()
    if doc.exists:
        _lock_cache = doc.to_dict().get('chats', [])
    else:
        _lock_cache = []
    return _lock_cache

async def toggle_lock(chat_id: int) -> bool:
    global _lock_cache
    db = get_db()
    ref = db.collection('bot_settings').document('locked')
    chats = await get_locked_chats()

    is_enabled = False
    if chat_id in chats:
        chats.remove(chat_id)
    else:
        chats.append(chat_id)
        is_enabled = True

    _lock_cache = chats
    from utils import fire_and_forget
    fire_and_forget(ref.set({'chats': chats}, merge=True))
    return is_enabled

async def remove_lock(chat_id: int):
    global _lock_cache
    db = get_db()
    ref = db.collection('bot_settings').document('locked')
    chats = await get_locked_chats()

    if chat_id in chats:
        chats.remove(chat_id)
        _lock_cache = chats
        from utils import fire_and_forget
        fire_and_forget(ref.set({'chats': chats}, merge=True))
