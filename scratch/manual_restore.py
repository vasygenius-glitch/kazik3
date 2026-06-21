#!/usr/bin/env python
import os
import sys
import json
import gzip
import base64
import asyncio

# Add project root to sys.path so we can import from db
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import init_db, get_db

async def run_manual_restore(backup_id: str, force: bool = False):
    print("🔄 Initializing database connection...")
    init_db("firebase-key.json")
    db = get_db()
    
    # Check if backup document exists
    print(f"🔍 Fetching backup document '{backup_id}' from Firestore...")
    backup_doc = await db.collection('backups').document(backup_id).get()
    
    if not backup_doc.exists:
        print(f"❌ Error: Backup ID '{backup_id}' not found in Firestore.")
        return False
        
    data = backup_doc.to_dict()
    payload = data.get("payload")
    if not payload:
        print("❌ Error: Backup document has no payload.")
        return False
        
    print(f"📦 Backup details: Created at {data.get('datetime')} UTC")
    
    # Decompress backup data
    try:
        compressed_bytes = base64.b64decode(payload)
        json_bytes = gzip.decompress(compressed_bytes)
        backup_data = json.loads(json_bytes.decode('utf-8'))
    except Exception as e:
        print(f"❌ Error during payload decompression: {e}")
        return False
        
    chats = backup_data.get("chats", {})
    print(f"📋 Backup contains data for {len(chats)} chat(s):")
    for chat_id, collections in chats.items():
        user_count = len(collections.get("users", {}))
        bank_count = len(collections.get("banks", {}))
        clan_count = len(collections.get("clans", {}))
        print(f"  • Chat {chat_id}: {user_count} users, {bank_count} banks, {clan_count} clans")
        
    if not force:
        confirm = input("\n⚠️ WARNING: This will overwrite current database collections (users, banks, clans) in the target chats.\nAre you sure you want to proceed? [y/N]: ")
        if confirm.lower().strip() not in ('y', 'yes'):
            print("🚫 Restore cancelled by user.")
            return False

    print("\n🚀 Starting restore process...")
    
    for chat_str, collections in chats.items():
        chat_doc_ref = db.collection('chats').document(chat_str)
        
        # --- Restore Users ---
        print(f"🧹 Chat {chat_str}: Clearing current 'users'...")
        users_docs = await chat_doc_ref.collection('users').get()
        batch = db.batch()
        count = 0
        for doc in users_docs:
            batch.delete(doc.reference)
            count += 1
            if count >= 500:
                await batch.commit()
                batch = db.batch()
                count = 0
        if count > 0:
            await batch.commit()
            
        print(f"✍️ Chat {chat_str}: Writing {len(collections.get('users', {}))} backup 'users'...")
        batch = db.batch()
        count = 0
        for doc_id, doc_fields in collections.get("users", {}).items():
            batch.set(chat_doc_ref.collection('users').document(doc_id), doc_fields)
            count += 1
            if count >= 500:
                await batch.commit()
                batch = db.batch()
                count = 0
        if count > 0:
            await batch.commit()
            
        # --- Restore Banks ---
        print(f"🧹 Chat {chat_str}: Clearing current 'banks'...")
        banks_docs = await chat_doc_ref.collection('banks').get()
        batch = db.batch()
        count = 0
        for doc in banks_docs:
            batch.delete(doc.reference)
            count += 1
            if count >= 500:
                await batch.commit()
                batch = db.batch()
                count = 0
        if count > 0:
            await batch.commit()
            
        print(f"✍️ Chat {chat_str}: Writing {len(collections.get('banks', {}))} backup 'banks'...")
        batch = db.batch()
        count = 0
        for doc_id, doc_fields in collections.get("banks", {}).items():
            batch.set(chat_doc_ref.collection('banks').document(doc_id), doc_fields)
            count += 1
            if count >= 500:
                await batch.commit()
                batch = db.batch()
                count = 0
        if count > 0:
            await batch.commit()
            
        # --- Restore Clans ---
        print(f"🧹 Chat {chat_str}: Clearing current 'clans'...")
        clans_docs = await chat_doc_ref.collection('clans').get()
        batch = db.batch()
        count = 0
        for doc in clans_docs:
            batch.delete(doc.reference)
            count += 1
            if count >= 500:
                await batch.commit()
                batch = db.batch()
                count = 0
        if count > 0:
            await batch.commit()
            
        print(f"✍️ Chat {chat_str}: Writing {len(collections.get('clans', {}))} backup 'clans'...")
        batch = db.batch()
        count = 0
        for doc_id, doc_fields in collections.get("clans", {}).items():
            batch.set(chat_doc_ref.collection('clans').document(doc_id), doc_fields)
            count += 1
            if count >= 500:
                await batch.commit()
                batch = db.batch()
                count = 0
        if count > 0:
            await batch.commit()

    # Invalidate cache if redis is running
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        print("🔄 Clearing FSM state from Redis...")
        try:
            import redis
            r = redis.from_url(redis_url)
            # Find and delete keys starting with fsm:
            keys = r.keys("fsm:*")
            if keys:
                r.delete(*keys)
                print(f"✅ Cleared {len(keys)} FSM keys from Redis.")
        except Exception as e:
            print(f"⚠️ Failed to clear Redis: {e}")

    print("\n✅ Restore operation completed successfully!")
    print("👉 IMPORTANT: If the bot is currently running, restart it to flush in-memory caches and fetch the restored data.")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scratch/manual_restore.py <backup_doc_id> [--force]")
        sys.exit(1)
        
    backup_id = sys.argv[1]
    force = "--force" in sys.argv
    
    asyncio.run(run_manual_restore(backup_id, force))
