"""Bounded backup/restore. Multi-document restores are NOT atomic."""
import asyncio
import base64
import gzip
import io
import json
import logging
import re
import time
import uuid
from db import get_db
from whitelist import get_whitelist
from user_manager import invalidate_user_cache, flush_all_user_data
from profile_bank import invalidate_bank_cache

logger = logging.getLogger(__name__)
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ENCODED_BYTES = 1_000_000
_backup_lock = asyncio.Lock()
_restore_lock = asyncio.Lock()


def _invalid_constant(value):
    raise ValueError("Backup contains a non-finite number")


def _validate_value(value):
    if type(value) is int and not -(2**63) <= value <= 2**63 - 1:
        raise ValueError("Integer exceeds Firestore range")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or len(key.encode("utf-8")) > 1500:
                raise ValueError("Invalid field name")
            _validate_value(child)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, list):
                raise ValueError("Firestore does not support nested arrays")
            _validate_value(child)


def validate_backup(data):
    if not isinstance(data, dict) or not isinstance(data.get("chats"), dict) or not data["chats"]:
        raise ValueError("Backup must contain a non-empty chats object")
    for chat_id, sections in data["chats"].items():
        if not isinstance(chat_id, str) or not re.fullmatch(r"-?[1-9][0-9]{0,18}", chat_id):
            raise ValueError("Invalid chat ID")
        if not isinstance(sections, dict) or not all(isinstance(sections.get(k), dict) for k in ("users", "banks", "clans")):
            raise ValueError("Each chat must include users, banks and clans objects")
        for kind in ("users", "banks", "clans"):
            for doc_id, fields in sections[kind].items():
                if (not isinstance(doc_id, str) or not doc_id or "/" in doc_id
                        or len(doc_id.encode("utf-8")) > 1500 or not isinstance(fields, dict)):
                    raise ValueError("Invalid document in backup")
                if doc_id in {".", ".."} or re.fullmatch(r"__.*__", doc_id):
                    raise ValueError("Reserved document ID")
                _validate_value(fields)
                if kind != "clans" and not re.fullmatch(r"[1-9][0-9]{0,18}", doc_id):
                    raise ValueError("Invalid user/bank ID")
                if len(json.dumps(fields, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 900_000:
                    raise ValueError("Document exceeds safe Firestore size")
    return data


def decode_backup(payload):
    if not isinstance(payload, str) or not payload or len(payload) > MAX_ENCODED_BYTES:
        raise ValueError("Invalid backup payload size")
    compressed = base64.b64decode(payload, validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("Decompressed backup exceeds size limit")
    return validate_backup(json.loads(raw.decode("utf-8"), parse_constant=_invalid_constant))


async def backup_database(chat_ids=None, reason="snapshot"):
    async with _backup_lock:
        try:
            db = get_db()
            await flush_all_user_data()
            selected = list(chat_ids) if chat_ids is not None else list(await get_whitelist())
            backup = {"version": 2, "chats": {}}
            for cid in selected:
                sections = {}
                for kind in ("users", "banks", "clans"):
                    ref = db.collection("chats").document(str(cid)).collection(kind)
                    sections[kind] = {doc.id: doc.to_dict() for doc in await ref.get()}
                backup["chats"][str(cid)] = sections
            validate_backup(backup)
            raw = json.dumps(backup, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(raw) > MAX_JSON_BYTES:
                raise ValueError("Backup is too large; use external snapshot storage")
            payload = base64.b64encode(gzip.compress(raw)).decode("ascii")
            if len(payload) > 900_000:
                raise ValueError("Backup exceeds single-document limit; use external snapshot storage")
            timestamp = int(time.time())
            backup_id = f"backup_{timestamp}_{uuid.uuid4().hex[:6]}"
            await db.collection("backups").document(backup_id).set({
                "timestamp": timestamp,
                "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(timestamp)),
                "payload": payload, "reason": reason, "version": 2,
            })
            try:
                ref = db.collection("backups")
                if callable(getattr(ref, "select", None)):
                    ref = ref.select(["timestamp"])
                for doc in await ref.get():
                    if (doc.to_dict() or {}).get("timestamp", timestamp) < timestamp - 7 * 86400:
                        await db.collection("backups").document(doc.id).delete()
            except Exception:
                logger.warning("Backup retention cleanup failed", exc_info=True)
            logger.info("Backup created: %s", backup_id)
            return True, backup_id
        except Exception as exc:
            logger.exception("Backup creation failed")
            return False, f"Не удалось создать копию ({type(exc).__name__}); подробности в журнале."


async def restore_database(backup_doc_id):
    if _restore_lock.locked():
        return False, "Другое восстановление уже выполняется."
    async with _restore_lock:
        touched_users = set()
        touched_banks = {}
        safety_id = None
        try:
            if not isinstance(backup_doc_id, str) or not re.fullmatch(r"backup_[0-9]+(?:_[a-f0-9]{6})?", backup_doc_id):
                raise ValueError("Invalid backup ID")
            db = get_db()
            doc = await db.collection("backups").document(backup_doc_id).get()
            if not doc.exists:
                return False, "Резервная копия не найдена."
            backup = decode_backup((doc.to_dict() or {}).get("payload"))
            maintenance = await db.collection("bot_settings").document("maintenance").get()
            if not (maintenance.to_dict() or {}).get("active"):
                return False, "Сначала включите техрежим и завершите активные игры."
            ok, safety_id = await backup_database(chat_ids=backup["chats"], reason="pre-restore")
            if not ok:
                return False, "Восстановление отменено: защитная копия не создана."
            obsolete = []
            batch = db.batch()
            count = 0
            for chat_id, sections in backup["chats"].items():
                for kind in ("users", "banks", "clans"):
                    ref = db.collection("chats").document(chat_id).collection(kind)
                    current = {doc.id: doc.to_dict() for doc in await ref.get()}
                    if kind == "users":
                        touched_users.update((int(chat_id), int(uid)) for uid in set(current) | set(sections[kind]))
                    if kind == "banks":
                        for uid in set(current) | set(sections[kind]):
                            touched_banks[(int(chat_id), int(uid))] = (current.get(uid, {}).get("name"), sections[kind].get(uid, {}).get("name"))
                    obsolete.extend(ref.document(uid) for uid in current if uid not in sections[kind])
                    for uid, fields in sections[kind].items():
                        batch.set(ref.document(uid), fields)
                        count += 1
                        if count == 400:
                            await batch.commit()
                            batch, count = db.batch(), 0
            if count:
                await batch.commit()
            batch, count = db.batch(), 0
            for ref in obsolete:
                batch.delete(ref)
                count += 1
                if count == 400:
                    await batch.commit()
                    batch, count = db.batch(), 0
            if count:
                await batch.commit()
            logger.info("Restore completed: %s; rollback snapshot: %s", backup_doc_id, safety_id)
            return True, None
        except Exception as exc:
            logger.exception("Restore failed; rollback snapshot: %s", safety_id)
            suffix = f" Защитная копия: {safety_id}." if safety_id else " Данные восстановления не записаны."
            return False, f"Восстановление не завершено ({type(exc).__name__})." + suffix
        finally:
            for cid, uid in touched_users:
                invalidate_user_cache(cid, uid)
            for (cid, uid), names in touched_banks.items():
                for name in names:
                    invalidate_bank_cache(cid, uid, name)


async def backup_database_task():
    # Daily restarts must not postpone the first snapshot forever.
    await asyncio.sleep(60)
    while True:
        await backup_database()
        await asyncio.sleep(86400)
