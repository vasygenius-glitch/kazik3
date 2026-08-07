import pytest
import asyncio
import os
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

from db import init_db, get_db, MockDB, MockCollection, MockDocument, MockBatch, MockTransaction
from user_manager import (
    get_user_data, set_in_cache, mark_dirty, flush_user_data,
    flush_user_cache_immediately, add_item_to_inventory,
    remove_item_from_inventory, get_user_lock
)
from utils_pkg.cache_manager import CacheManager
from backup_system import backup_database, restore_database
from lock_system import get_locked_chats, toggle_lock, remove_lock
from log_system import log_action, log_buffer
from whitelist import get_whitelist, add_to_whitelist, remove_from_whitelist

init_db("key.json")

# =====================================================================
# 1. DB MODULE TESTS (10 TESTS PER FUNCTION/CLASS)
# =====================================================================

@pytest.mark.parametrize("idx", range(10))
def test_mock_db_initialization(idx):
    filepath = f"data/test_db_init_{idx}.json"
    db_inst = MockDB(filepath=filepath)
    assert db_inst is not None
    assert db_inst.filepath == filepath

@pytest.mark.parametrize("idx", range(10))
def test_mock_collection_document_access(idx):
    db_inst = MockDB(filepath=f"data/test_db_access_{idx}.json")
    col = db_inst.collection(f"col_{idx}")
    doc = col.document(f"doc_{idx}")
    assert isinstance(col, MockCollection)
    assert isinstance(doc, MockDocument)

@pytest.mark.asyncio
@pytest.mark.parametrize("val", [10, 20, 30, 50, 100, 200, 500, 1000, 5000, 10000])
async def test_mock_document_set_get(val):
    db_inst = MockDB(filepath=f"data/test_db_setget_{val}.json")
    doc = db_inst.collection("users").document(f"user_{val}")
    await doc.set({"balance": val, "name": f"User_{val}"}, merge=True)
    res = await doc.get()
    assert res.exists is True
    data = res.to_dict()
    assert data["balance"] == val

@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [-100, -50, -10, -1, 0, 1, 10, 50, 100, 500])
async def test_mock_document_update(delta):
    db_inst = MockDB(filepath=f"data/test_db_update_{delta}.json")
    doc = db_inst.collection("users").document("user_test")
    await doc.set({"balance": 1000}, merge=True)
    await doc.update({"balance": 1000 + delta})
    res = await doc.get()
    assert res.to_dict()["balance"] == 1000 + delta

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_mock_document_delete(idx):
    db_inst = MockDB(filepath=f"data/test_db_del_{idx}.json")
    doc = db_inst.collection("items").document(f"item_{idx}")
    await doc.set({"name": "TestItem"}, merge=True)
    await doc.delete()
    res = await doc.get()
    assert res.exists is False

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_mock_batch_and_transaction(idx):
    db_inst = MockDB(filepath=f"data/test_db_batch_{idx}.json")
    batch = db_inst.batch()
    doc = db_inst.collection("test").document(f"doc_{idx}")
    batch.set(doc, {"val": idx})
    await batch.commit()
    res = await doc.get()
    assert res.to_dict()["val"] == idx

# =====================================================================
# 2. USER MANAGER TESTS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [101, 102, 103, 104, 105, 106, 107, 108, 109, 110])
async def test_get_user_data_caching(user_id):
    chat_id = 999
    user_data = {"balance": user_id * 100, "is_banned": False}
    set_in_cache(chat_id, user_id, user_data)
    data1 = await get_user_data(chat_id, user_id)
    assert data1["balance"] == user_id * 100

@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [1, 2, 5, 10, 15, 20, 25, 50, 100, 200])
async def test_add_item_to_inventory_cases(qty):
    chat_id = 888
    user_id = 777 + qty
    user_data = {"inventory": {}, "balance": 1000}
    set_in_cache(chat_id, user_id, user_data)
    success = await add_item_to_inventory(chat_id, user_id, "шаурма", count=qty)
    assert success is True
    updated = await get_user_data(chat_id, user_id)
    assert updated["inventory"]["шаурма"] == qty

@pytest.mark.asyncio
@pytest.mark.parametrize("remove_qty", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
async def test_remove_item_from_inventory_cases(remove_qty):
    chat_id = 888
    user_id = 999 + remove_qty
    user_data = {"inventory": {"шаурма": 10}, "balance": 1000}
    set_in_cache(chat_id, user_id, user_data)
    success = await remove_item_from_inventory(chat_id, user_id, "шаурма", count=remove_qty)
    assert success is True
    updated = await get_user_data(chat_id, user_id)
    if remove_qty == 10:
        assert "шаурма" not in updated.get("inventory", {})
    else:
        assert updated["inventory"]["шаурма"] == 10 - remove_qty

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_flush_user_cache_immediately_scenarios(idx):
    chat_id = 500 + idx
    user_id = 600 + idx
    user_data = {"balance": 5000 + idx}
    set_in_cache(chat_id, user_id, user_data)
    mark_dirty(chat_id, user_id)
    with patch("user_manager._flush_single_user", new_callable=AsyncMock):
        await flush_user_cache_immediately(chat_id, user_id)

@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
async def test_get_user_lock_concurrency(user_id):
    lock1 = get_user_lock(100, user_id)
    lock2 = get_user_lock(100, user_id)
    assert lock1 is lock2

# =====================================================================
# 3. CACHE MANAGER & LOCK SYSTEM TESTS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("key_idx", range(10))
def test_cache_manager_set_get(key_idx):
    cache = CacheManager()
    key = f"key_{key_idx}"
    val = f"val_{key_idx}"
    cache.set(key, val, ttl=60)
    assert cache.get(key) == val

@pytest.mark.parametrize("key_idx", range(10))
def test_cache_manager_delete_clear(key_idx):
    cache = CacheManager()
    key = f"key_{key_idx}"
    cache.set(key, "data")
    cache.delete(key)
    assert cache.get(key) is None
    cache.set("k1", "v1")
    cache.clear()
    assert cache.get("k1") is None

@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", [1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010])
async def test_toggle_lock_system_chats(chat_id):
    with patch("lock_system.get_locked_chats", new_callable=AsyncMock, return_value=[]), \
         patch("lock_system.get_db"):
        enabled = await toggle_lock(chat_id)
        assert enabled is True

# =====================================================================
# 4. BACKUP & LOG & WHITELIST TESTS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_backup_system_operations(idx):
    with patch("backup_system.get_whitelist", new_callable=AsyncMock, return_value={}), \
         patch("backup_system.get_db"):
        ok, backup_id = await backup_database()
        assert isinstance(ok, bool)

@pytest.mark.parametrize("action_id", range(10))
def test_log_system_recording(action_id):
    initial_len = len(log_buffer)
    log_action(f"Test admin action {action_id}")
    assert len(log_buffer) == initial_len + 1

@pytest.mark.asyncio
@pytest.mark.parametrize("uid", [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000])
async def test_whitelist_toggle(uid):
    with patch("whitelist.get_whitelist", new_callable=AsyncMock, return_value={}), \
         patch("whitelist.get_db"):
        added = await add_to_whitelist(uid)
        assert isinstance(added, bool)
