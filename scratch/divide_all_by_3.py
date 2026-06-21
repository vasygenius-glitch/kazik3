import asyncio
import os
from dotenv import load_dotenv
from db import init_db, get_db
from user_manager import invalidate_user_cache, flush_user_cache_immediately, get_user_ref, get_user_data, update_user_field

load_dotenv()

async def main():
    init_db("firebase-key.json")
    db = get_db()
    
    chat_id = "-1002321279920"
    
    user_ids = [
        "5818310207",  # Operator5001
        "8244560608",  # American_pcuxopath
        "6609846288",  # markmark20102002200
        "5341242165",  # ylta_jely
        "7594279469",  # Thomas_Rousseau0
        "7087272188",  # DEDBTRYCAX2
        "8235022368",  # Mr_Zep000
        "8703145309",  # dino69kruteishii
        "6445616086",  # Dont_basyak
        "7127766883",  # Просто Человек
        "873130109",   # User 1
        "1316346846"   # User 2
    ]
    
    for uid in user_ids:
        ref = get_user_ref(chat_id, uid)
        snapshot = await ref.get()
        if not snapshot.exists:
            print(f"⚠️ User ID {uid} not found in database.")
            continue
            
        data = snapshot.to_dict() or {}
        old_balance = data.get('balance', 0)
        old_deposit = data.get('bank_deposit', 0)
        old_portfolio = data.get('crypto_portfolio', {})
        old_inventory = data.get('inventory', {})
        
        # Divide balance by 3 (min 0)
        new_balance = max(0, old_balance // 3)
        
        # Divide bank deposit by 3 (min 0)
        new_deposit = max(0, old_deposit // 3)
        
        # Divide crypto portfolio quantities by 3
        new_portfolio = {}
        if isinstance(old_portfolio, dict):
            for coin, qty in old_portfolio.items():
                new_qty = qty // 3
                if new_qty > 0:
                    new_portfolio[coin] = new_qty
                    
        # Divide inventory quantities by 3
        new_inventory = {}
        if isinstance(old_inventory, dict):
            for item, qty in old_inventory.items():
                new_qty = qty // 3
                if new_qty > 0:
                    new_inventory[item] = new_qty
                    
        updates = {
            'balance': new_balance,
            'bank_deposit': new_deposit,
            'crypto_portfolio': new_portfolio,
            'inventory': new_inventory
        }
        
        # Apply updates
        await ref.update(updates)
        
        # Invalidate cache
        invalidate_user_cache(chat_id, uid)
        
        print(f"✅ Processed {data.get('full_name', 'Unknown')} ({uid}):")
        print(f"   Balance: {old_balance} -> {new_balance}")
        print(f"   Deposit: {old_deposit} -> {new_deposit}")
        print(f"   Crypto: {old_portfolio} -> {new_portfolio}")
        print(f"   Inventory: {old_inventory} -> {new_inventory}")

if __name__ == "__main__":
    asyncio.run(main())
