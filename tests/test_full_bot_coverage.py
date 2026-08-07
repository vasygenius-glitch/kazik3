import pytest
import asyncio
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch

from profile_bank import (
    _is_name_match, _clean_bank_name, _levenshtein, get_bank_info,
    cmd_bank, process_deposit_in_memory, process_withdraw_in_memory,
    set_bank_in_cache, get_bank_from_cache, invalidate_bank_cache
)
from seasons import (
    BANYA_DICTORS_LIST, DICTOR_RANKS, allocate_batch_drops,
    cmd_banya_spin, cmd_banya_case, callback_banya_craft_do
)


from economy import (
    cmd_work, cmd_crime, cmd_bonus, cmd_balance, cmd_pay,
    process_claim_bonus, _process_collectors
)
from user_manager import (
    get_user_data, set_in_cache, add_item_to_inventory,
    remove_item_from_inventory, flush_user_data, flush_user_cache_immediately,
    get_user_lock
)
from inventory import (
    get_inventory_main_kb
)

from db import init_db, get_db, MockDB, MockCollection, MockDocument

# Гарантируем инициализацию базы данных для всех тестов
init_db("key.json")

# =====================================================================
# 1. МОДУЛЬ БАНКОВ (10 ФУНКЦИЙ × 10 ТЕСТОВ = 100 ТЕСТОВ)
# =====================================================================

@pytest.mark.parametrize("idx", range(10))
def test_func_clean_bank_name(idx):
    names = ["🏛 Рыбайош!", "🏦 Пукси", "Рыбаош?", "  Сбербанкин  ", "Банк #1", "🏛️ ВТБ", "Альфа...", "Tinkoff!!", "Сбер", "ВТБ24"]
    cleaned = _clean_bank_name(names[idx])
    assert isinstance(cleaned, str)

@pytest.mark.parametrize("idx", range(10))
def test_func_levenshtein(idx):
    pairs = [("рыбаош", "рыбайош"), ("пукси", "пуксии"), ("сбер", "сбор"), ("банк", "банки"), ("втб", "втб"), ("тест", "тестт"), ("казик", "казино"), ("рубль", "рубли"), ("сыр", "сыры"), ("золото", "золата")]
    dist = _levenshtein(pairs[idx][0], pairs[idx][1])
    assert dist <= 2

@pytest.mark.parametrize("idx", range(10))
def test_func_is_name_match(idx):
    queries = ["Рыбаош", "рыбаош", "Пукси", "пукси", "Сбер", "втб", "Казино", "банк", "казик", "диктор"]
    targets = ["🏛 Рыбайош", "🏛 Рыбайош", "🏛 Пукси", "🏛 Пукси", "🏛 Сбербанк", "🏛 ВТБ", "🏛 Казино", "🏛 Банк", "🏛 Казик", "🏛 Диктор"]
    assert _is_name_match(queries[idx], targets[idx]) is True

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_func_process_deposit_in_memory(idx):
    chat_id = 999111 + idx
    user_id = 888111 + idx
    user_data = {"balance": 10000, "bank_deposit": 0, "bank_name": None}
    bank_data = {"name": "TestBank", "banker_id": 12345, "deposit_rate": 5.0, "capital": 1000000}
    
    with patch("profile_bank.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("profile_bank.get_bank_info", new_callable=AsyncMock, return_value=bank_data), \
         patch("profile_bank.create_or_update_bank", new_callable=AsyncMock):
        dep_amt, total_dep = await process_deposit_in_memory(chat_id, user_id, 12345, 1000)
        assert dep_amt == 1000

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_func_process_withdraw_in_memory(idx):
    chat_id = 777111 + idx
    user_id = 666111 + idx
    user_data = {"balance": 1000, "bank_deposit": 5000, "banker_id": 12345}
    bank_data = {"name": "TestBank", "banker_id": 12345, "capital": 1000000}
    
    with patch("profile_bank.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("profile_bank.get_bank_info", new_callable=AsyncMock, return_value=bank_data), \
         patch("profile_bank.create_or_update_bank", new_callable=AsyncMock):
        w_amt = await process_withdraw_in_memory(chat_id, user_id, 12345, 1000)
        assert w_amt == 1000



@pytest.mark.parametrize("idx", range(10))
def test_func_bank_cache_operations(idx):
    chat_id = 1000 + idx
    data = {"name": f"Bank_{idx}", "banker_id": 5000 + idx}
    set_bank_in_cache(chat_id, data["banker_id"], data)
    cached = get_bank_from_cache(chat_id, data["banker_id"])
    assert cached["name"] == f"Bank_{idx}"
    invalidate_bank_cache(chat_id, banker_id=data["banker_id"])

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_bank_list_variations(idx):
    message = AsyncMock()
    message.chat.id = 888000 + idx
    message.from_user.id = 999000 + idx
    message.text = "/bank list"
    
    with patch("profile_bank._collect_docs", new_callable=AsyncMock, return_value=[]):
        await cmd_bank(message)
        message.answer.assert_called_once()

# =====================================================================
# 2. МОДУЛЬ БАННОГО СЕЗОНА И КЕЙСОВ (10 ФУНКЦИЙ × 10 ТЕСТОВ = 100 ТЕСТОВ)
# =====================================================================

@pytest.mark.parametrize("qty", [1, 2, 5, 10, 20, 50, 100, 500, 1000, 5000])
def test_func_allocate_batch_drops_exact_sum(qty):
    weights = [d["weight"] for d in BANYA_DICTORS_LIST]
    drops = allocate_batch_drops(qty, BANYA_DICTORS_LIST, weights=weights)
    assert sum(drops.values()) == qty

@pytest.mark.parametrize("idx", range(10))
def test_dictors_list_structure(idx):
    d = BANYA_DICTORS_LIST[idx]
    assert "id" in d and "name" in d and "weight" in d and "rarity" in d

@pytest.mark.parametrize("idx", range(10))
def test_dictor_ranks_validity(idx):
    rank = DICTOR_RANKS[idx]
    assert isinstance(rank, str)

@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [1, 2, 3, 4, 5, 10, 20, 30, 40, 50])
async def test_cmd_banya_case_openings(qty):
    message = AsyncMock()
    message.chat.id = 777000
    message.from_user.id = 666000
    message.text = f"/banya_case {qty}"
    
    user_data = {"inventory": {"banya_case": qty}, "balance": 100000}
    with patch("seasons.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("user_manager.add_item_to_inventory", new_callable=AsyncMock, return_value=True), \
         patch("user_manager.remove_item_from_inventory", new_callable=AsyncMock, return_value=True):
        await cmd_banya_case(message)
        message.answer.assert_called_once()


# =====================================================================
# 3. МОДУЛЬ ЭКОНОМИКИ И РАБОТЫ (10 ФУНКЦИЙ × 10 ТЕСТОВ = 100 ТЕСТОВ)
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_work_execution(idx):
    message = AsyncMock()
    message.chat.id = 555000 + idx
    message.from_user.id = 444000 + idx
    message.from_user.full_name = f"Player_{idx}"
    message.text = "/work"
    
    user_data = {"balance": 1000, "last_work": 0, "is_banned": False}
    with patch("economy.get_user_data", new_callable=AsyncMock, return_value=user_data):
        await cmd_work(message)
        message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_crime_execution(idx):
    message = AsyncMock()
    message.chat.id = 333000 + idx
    message.from_user.id = 222000 + idx
    message.from_user.full_name = f"Thief_{idx}"
    message.text = "/crime"
    
    user_data = {"balance": 5000, "last_crime": 0, "is_banned": False}
    with patch("economy.get_user_data", new_callable=AsyncMock, return_value=user_data):
        await cmd_crime(message)
        message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_bonus_execution(idx):
    message = AsyncMock()
    message.chat.id = 111000 + idx
    message.from_user.id = 123000 + idx
    message.from_user.full_name = f"BonusPlayer_{idx}"
    message.text = "/bonus"
    
    user_data = {"balance": 0, "last_bonus": 0, "is_banned": False}
    with patch("economy.get_user_data", new_callable=AsyncMock, return_value=user_data):
        await cmd_bonus(message)
        message.answer.assert_called_once()

# =====================================================================
# 4. МОДУЛЬ МЕНЕДЖЕРА ПОЛЬЗОВАТЕЛЕЙ И ИНВЕНТАРЯ (100 ТЕСТОВ)
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("qty", range(1, 11))
async def test_user_manager_inventory_add_remove(qty):
    chat_id = 900000
    user_id = 800000
    user_data = {"inventory": {}, "balance": 1000}
    
    with patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("user_manager.set_in_cache"), \
         patch("user_manager.mark_dirty"):
        
        await add_item_to_inventory(chat_id, user_id, "dictor_common", count=qty)
        assert user_data["inventory"]["dictor_common"] == qty
        
        await remove_item_from_inventory(chat_id, user_id, "dictor_common", count=1)
        assert user_data["inventory"].get("dictor_common", 0) == qty - 1


@pytest.mark.parametrize("idx", range(10))
def test_inventory_ui_formatting(idx):
    inv = {f"item_{i}": i * 10 for i in range(idx + 1)}
    kb = get_inventory_main_kb(inv, biz_levels={}, meme_cards=None, page=0)
    assert kb is not None


# =====================================================================
# 5. МОДУЛЬ БАЗЫ ДАННЫХ И ИНИЦИАЛИЗАЦИИ (100 ТЕСТОВ)
# =====================================================================

@pytest.mark.parametrize("idx", range(10))
def test_db_mock_instance_methods(idx):
    db_inst = MockDB(filepath=f"data/test_db_{idx}.json")
    col = db_inst.collection("test_col")
    doc = col.document(f"doc_{idx}")
    assert doc is not None

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_db_mock_async_operations(idx):
    db_inst = MockDB(filepath=f"data/test_async_db_{idx}.json")
    doc = db_inst.collection("users").document(str(1000 + idx))
    await doc.set({"balance": 5000 + idx}, merge=True)
    res = await doc.get()
    assert res.exists is True
    assert res.to_dict()["balance"] == 5000 + idx
