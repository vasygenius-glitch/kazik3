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
    
    print("ALL USERS IN CHAT:")
    for doc in docs:
        d = doc.to_dict()
        uid = doc.id
        full_name = d.get('full_name', '')
        username = d.get('username', '')
        balance = d.get('balance', 0)
        is_banker = d.get('is_banker', False)
        print(f"ID: {uid} | Name: {full_name} | Username: @{username} | Balance: {balance} | Banker: {is_banker}")

if __name__ == "__main__":
    asyncio.run(main())
