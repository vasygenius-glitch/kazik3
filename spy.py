from db import get_db

async def toggle_spy(chat_id: int):
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
    return is_enabled

async def get_spy_chats():
    db = get_db()
    doc = await db.collection('bot_settings').document('spy_chats').get()
    if doc.exists:
        return doc.to_dict().get('chats', [])
    return []
