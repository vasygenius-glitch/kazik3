import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db
from user_manager import update_user_field, invalidate_user_cache, flush_user_cache_immediately

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chat_id = "-1002321279920"
    user_id = "6978846120" # Отдел маркетинг Пятерочки
    
    # 1. Reset balance to 500 (DEFAULT_START_BALANCE)
    await update_user_field(chat_id, user_id, 'balance', 500)
    
    # 2. Reset bank deposit to 0
    await update_user_field(chat_id, user_id, 'bank_deposit', 0)
    
    # 3. Clear crypto portfolio to prevent selling duped coins
    await update_user_field(chat_id, user_id, 'crypto_portfolio', {})
    
    # 4. Flush dirty cache immediately to Firestore
    await flush_user_cache_immediately(chat_id, user_id)
    
    # 5. Invalidate cache
    invalidate_user_cache(chat_id, user_id)
    
    print("✅ Successfully reset and flushed balance, deposit, and crypto portfolio for 'мяукс' (6883804884)")

if __name__ == "__main__":
    asyncio.run(main())
