import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chat_id = "-1002321279920"
    
    for uid in ["1316346846", "873130109"]:
        doc_ref = db.collection('chats').document(chat_id).collection('users').document(uid)
        doc = await doc_ref.get()
        if doc.exists:
            print(f"User ID: {uid}")
            print(doc.to_dict())
        else:
            print(f"User ID {uid} not found in this chat")

if __name__ == "__main__":
    asyncio.run(main())
