import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chat_id = "-1002321279920"
    users_ref = db.collection('chats').document(chat_id).collection('users')
    docs = await users_ref.get()
    
    found = False
    for doc in docs:
        d = doc.to_dict()
        full_name = d.get('full_name', '')
        username = d.get('username', '')
        if "шип" in full_name.lower() or "шип" in username.lower():
            found = True
            print(f"FOUND USER:")
            print(f"ID: {doc.id}")
            print(d)
            
    if not found:
        print("User containing 'Шип' not found.")

if __name__ == "__main__":
    asyncio.run(main())
