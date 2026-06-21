import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    user_id = "6978846120"
    
    chats_ref = db.collection('chats')
    chat_docs = await chats_ref.get()
    
    found = False
    for chat_doc in chat_docs:
        chat_id = chat_doc.id
        user_ref = chats_ref.document(chat_id).collection('users').document(user_id)
        user_snap = await user_ref.get()
        if user_snap.exists:
            found = True
            print(f"Found user in chat {chat_id}:")
            print(user_snap.to_dict())
            
    if not found:
        print("User not found in any chat.")

if __name__ == "__main__":
    asyncio.run(main())
