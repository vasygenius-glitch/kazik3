import gzip
import json
import base64
import time
import asyncio
import logging
from db import get_db
from whitelist import get_whitelist
from user_manager import invalidate_user_cache
from profile_bank import invalidate_bank_cache

logger = logging.getLogger(__name__)

async def backup_database():
    try:
        db = get_db()
        whitelist = await get_whitelist()
        backup_data = {"chats": {}}
        
        for chat_id in whitelist.keys():
            chat_str = str(chat_id)
            backup_data["chats"][chat_str] = {
                "users": {},
                "banks": {},
                "clans": {}
            }
            
            chat_doc_ref = db.collection('chats').document(chat_str)
            
            # Fetch users
            users_docs = await chat_doc_ref.collection('users').get()
            for doc in users_docs:
                backup_data["chats"][chat_str]["users"][doc.id] = doc.to_dict()
                
            # Fetch banks
            banks_docs = await chat_doc_ref.collection('banks').get()
            for doc in banks_docs:
                backup_data["chats"][chat_str]["banks"][doc.id] = doc.to_dict()
                
            # Fetch clans
            clans_docs = await chat_doc_ref.collection('clans').get()
            for doc in clans_docs:
                backup_data["chats"][chat_str]["clans"][doc.id] = doc.to_dict()
                
        # Serialize to JSON and compress using gzip
        json_bytes = json.dumps(backup_data, ensure_ascii=False).encode('utf-8')
        compressed_bytes = gzip.compress(json_bytes)
        base64_str = base64.b64encode(compressed_bytes).decode('utf-8')
        
        timestamp = int(time.time())
        datetime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp))
        
        # Save to backups collection
        backup_doc_id = f"backup_{timestamp}"
        await db.collection('backups').document(backup_doc_id).set({
            "timestamp": timestamp,
            "datetime": datetime_str,
            "payload": base64_str
        })
        
        # Auto cleanup: delete backups older than 7 days
        seven_days_ago = timestamp - (7 * 24 * 3600)
        old_backups = await db.collection('backups').where('timestamp', '<', seven_days_ago).get()
        for doc in old_backups:
            await doc.reference.delete()
            
        logger.info(f"✅ Database backup created: {backup_doc_id}")
        return True, backup_doc_id
    except Exception as e:
        logger.error(f"❌ Backup failed: {e}")
        return False, str(e)

async def restore_database(backup_doc_id: str):
    try:
        db = get_db()
        backup_doc = await db.collection('backups').document(backup_doc_id).get()
        if not backup_doc.exists:
            return False, "Резервная копия не найдена в базе данных."
            
        payload = backup_doc.to_dict().get("payload")
        if not payload:
            return False, "Битые данные резервной копии."
            
        compressed_bytes = base64.b64decode(payload)
        json_bytes = gzip.decompress(compressed_bytes)
        backup_data = json.loads(json_bytes.decode('utf-8'))
        
        # Restore chats
        for chat_str, collections in backup_data.get("chats", {}).items():
            chat_id = int(chat_str)
            chat_doc_ref = db.collection('chats').document(chat_str)
            
            # --- Restore Users ---
            # 1. Clear current users collection
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
                
            # 2. Write backup users
            batch = db.batch()
            count = 0
            for doc_id, doc_fields in collections.get("users", {}).items():
                batch.set(chat_doc_ref.collection('users').document(doc_id), doc_fields)
                invalidate_user_cache(chat_id, int(doc_id))
                count += 1
                if count >= 500:
                    await batch.commit()
                    batch = db.batch()
                    count = 0
            if count > 0:
                await batch.commit()
                
            # --- Restore Banks ---
            # 1. Clear current banks collection
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
                
            # 2. Write backup banks
            batch = db.batch()
            count = 0
            for doc_id, doc_fields in collections.get("banks", {}).items():
                batch.set(chat_doc_ref.collection('banks').document(doc_id), doc_fields)
                invalidate_bank_cache(chat_id, int(doc_id), doc_fields.get('name'))
                count += 1
                if count >= 500:
                    await batch.commit()
                    batch = db.batch()
                    count = 0
            if count > 0:
                await batch.commit()
                
            # --- Restore Clans ---
            # 1. Clear current clans collection
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
                
            # 2. Write backup clans
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
                
        logger.info(f"✅ Database restored from: {backup_doc_id}")
        return True, None
    except Exception as e:
        logger.error(f"❌ Restore failed: {e}")
        return False, str(e)

async def backup_database_task():
    logger.info("🚀 Background database backup task started.")
    while True:
        # Run every 24 hours
        await asyncio.sleep(86400)
        try:
            await backup_database()
        except Exception as e:
            logger.error(f"Error in backup background task: {e}")
