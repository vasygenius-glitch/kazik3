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
    users_docs = await users_ref.get()
    
    print(f"--- USERS IN CHAT {chat_id} ---")
    for doc in users_docs:
        u_data = doc.to_dict()
        uid = doc.id
        username = u_data.get('username')
        full_name = u_data.get('full_name')
        balance = u_data.get('balance', 0)
        bank_deposit = u_data.get('bank_deposit', 0)
        print(f"ID: {uid} | Username: @{username} | Name: {full_name} | Balance: {balance} | Deposit: {bank_deposit}")

if __name__ == "__main__":
    asyncio.run(main())
