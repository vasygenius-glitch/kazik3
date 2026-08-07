from db import get_db

_spy_chats_cache = None
_spy_all_cache = None

async def toggle_spy(chat_id: int):
    global _spy_chats_cache
    db = get_db()
    doc_ref = db.collection('bot_settings').document('spy_chats')
    doc = await doc_ref.get()
    
    spy_chats = []
    if doc.exists:
        spy_chats = doc.to_dict().get('chats', [])
    
    if chat_id in spy_chats:
        spy_chats.remove(chat_id)
        is_enabled = False
    else:
        spy_chats.append(chat_id)
        is_enabled = True
        
    await doc_ref.set({'chats': spy_chats}, merge=True)
    _spy_chats_cache = spy_chats
    return is_enabled

async def toggle_spy_all() -> bool:
    global _spy_all_cache
    db = get_db()
    doc_ref = db.collection('bot_settings').document('spy_chats')
    doc = await doc_ref.get()
    
    current_state = False
    if doc.exists:
        current_state = doc.to_dict().get('spy_all', False)
    
    new_state = not current_state
    await doc_ref.set({'spy_all': new_state}, merge=True)
    _spy_all_cache = new_state
    return new_state

async def is_spy_all_enabled() -> bool:
    global _spy_all_cache
    if _spy_all_cache is not None:
        return _spy_all_cache
    db = get_db()
    doc = await db.collection('bot_settings').document('spy_chats').get()
    if doc.exists:
        _spy_all_cache = bool(doc.to_dict().get('spy_all', False))
    else:
        _spy_all_cache = False
    return _spy_all_cache

async def get_spy_chats():
    global _spy_chats_cache
    if _spy_chats_cache is not None:
        return _spy_chats_cache
    db = get_db()
    doc = await db.collection('bot_settings').document('spy_chats').get()
    if doc.exists:
        _spy_chats_cache = doc.to_dict().get('chats', [])
    else:
        _spy_chats_cache = []
    return _spy_chats_cache

