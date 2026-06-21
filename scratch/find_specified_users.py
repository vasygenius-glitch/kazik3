import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chat_id = "-1002321279920"
    
    target_usernames = {
        'operator5001',
        'american_pcuxopath',
        'markmark20102002200',
        'ylta_jely',
        'thomas_rousseau0',
        'dedbtrycax2',
        'mr_zep000',
        'dino69kruteishii',
        'dont_basyak'
    }
    
    users_ref = db.collection('chats').document(chat_id).collection('users')
    users_docs = await users_ref.get()
    
    print("--- FOUND TARGET USERS ---")
    for doc in users_docs:
        u_data = doc.to_dict()
        uid = doc.id
        username = u_data.get('username')
        full_name = u_data.get('full_name')
        balance = u_data.get('balance', 0)
        bank_deposit = u_data.get('bank_deposit', 0)
        
        # Match by target username
        if username and username.lower() in target_usernames:
            print(f"MATCH: {username} | ID: {uid} | Name: {full_name} | Balance: {balance} | Deposit: {bank_deposit}")
            
        # Match by no username
        elif not username or username == 'None':
            # Let's print users with no username that have large balances / deposits
            if balance > 5000 or bank_deposit > 5000:
                print(f"NO_USER (high bal/dep): {full_name} | ID: {uid} | Balance: {balance} | Deposit: {bank_deposit}")

if __name__ == "__main__":
    asyncio.run(main())
