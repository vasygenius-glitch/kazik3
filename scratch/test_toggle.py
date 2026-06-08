import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    # Import user manager components
    from user_manager import get_user_data, update_user_field, flush_user_cache_immediately
    
    chat_id = -1002321279920
    user_id = 6226796902
    
    print("--- STEP 1: INITIAL STATE ---")
    data = await get_user_data(chat_id, user_id)
    print(f"Loaded from cache/db: is_banker = {data.get('is_banker')}")
    
    print("\n--- STEP 2: TOGGLE BANKER ROLE ---")
    new_val = not data.get('is_banker', False)
    print(f"Setting is_banker to: {new_val}")
    await update_user_field(chat_id, user_id, 'is_banker', new_val)
    
    print("\n--- STEP 3: FLUSH TO DB ---")
    await flush_user_cache_immediately(chat_id, user_id)
    
    print("\n--- STEP 4: VERIFY VIA DIRECT FIRESTORE READ ---")
    doc_ref = db.collection('chats').document(str(chat_id)).collection('users').document(str(user_id))
    doc = await doc_ref.get()
    if doc.exists:
        db_data = doc.to_dict()
        print(f"Direct Firestore check: is_banker = {db_data.get('is_banker')}")
    else:
        print("User not found in Firestore")
        
    print("\n--- STEP 5: VERIFY VIA get_user_data ---")
    data2 = await get_user_data(chat_id, user_id)
    print(f"Second call get_user_data: is_banker = {data2.get('is_banker')}")

if __name__ == "__main__":
    asyncio.run(main())
