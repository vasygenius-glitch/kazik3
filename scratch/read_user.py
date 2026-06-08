import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chat_id = "-1002321279920"
    user_id = "6226796902"
    
    doc_ref = db.collection('chats').document(chat_id).collection('users').document(user_id)
    doc = await doc_ref.get()
    
    if doc.exists:
        print("USER DATA IN FIRESTORE:")
        print(doc.to_dict())
    else:
        print("USER NOT FOUND")

if __name__ == "__main__":
    asyncio.run(main())
