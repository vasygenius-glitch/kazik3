from db import get_db

_spy_chats_cache = None

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
