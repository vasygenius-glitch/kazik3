import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chats_ref = db.collection('chats')
    chat_docs = await chats_ref.get()
    
    found = False
    for chat_doc in chat_docs:
        chat_id = chat_doc.id
        users_ref = chats_ref.document(chat_id).collection('users')
        users_docs = await users_ref.get()
        for user_doc in users_docs:
            u_data = user_doc.to_dict()
            name = u_data.get('full_name', '')
            username = u_data.get('username', '')
            if 'мяу' in name.lower() or 'meow' in name.lower() or 'мяу' in username.lower() or 'meow' in username.lower():
                found = True
                print(f"Found user in chat {chat_id} (User ID: {user_doc.id}):")
                print(u_data)
                
    if not found:
        print("No users found containing 'мяу' or 'meow'.")

if __name__ == "__main__":
    asyncio.run(main())
