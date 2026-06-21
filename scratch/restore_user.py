import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db
from user_manager import invalidate_user_cache, flush_user_cache_immediately, get_user_ref

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chat_id = "-1002321279920"
    user_id = "6883804884" # мяукс
    
    # Original balance divided by 2: 100,072,737 // 2 = 50,036,368
    restored_data = {
        'deposit_start_time': 0,
        'bank_name': None,
        'balance': 50036368,
        'username': 'Meowx_eshkere',
        'warns': [],
        'diseases': {},
        'is_vip': True,
        'last_daily_time': 1782044697.5736895,
        'last_bank_rob_time': 1782030315.1339703,
        'is_banker': False,
        'reputation': 7,
        'clan': 'ЛЮБИТЕЛИ ФУТАНАРИ',
        'pet': {'last_fed': 1782056033, 'id': 'dog'},
        'skills': {'stealth': 5, 'luck': 5, 'negotiation': 5},
        'crypto_portfolio': {'zlb': 20, 'larpcoin': 10, 'komaruim': 20, 'fum': 20},
        'partner': None,
        'last_bonus_time': 1782044697.5736895,
        'is_banned': False,
        'last_crime_time': 1782055801.47621,
        'last_work_time': 1782055796.7996078,
        'last_steal_time': 1782057981,
        'debts': {},
        'hide_in_top': False,
        'inventory': {'завод': 1, 'condom': 7, 'ферма': 1, 'бугатти': 1, 'бмв': 1},
        'biz_levels': {},
        'full_name': 'мяукс',
        'bank_deposit': 0,
        'escort_count': 2
    }
    
    ref = get_user_ref(chat_id, user_id)
    await ref.set(restored_data)
    
    # Invalidate cache
    invalidate_user_cache(chat_id, user_id)
    
    print("✅ Successfully restored 'мяукс' (6883804884) with balance halved to 50,036,368 and all previous assets returned.")

if __name__ == "__main__":
    asyncio.run(main())
