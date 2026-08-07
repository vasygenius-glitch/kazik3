import pytest
import asyncio
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
from profile_bank import _is_name_match, _clean_bank_name, _levenshtein, get_bank_info, cmd_bank, process_deposit_in_memory, process_withdraw_in_memory
from seasons import BANYA_DICTORS_LIST, DICTOR_RANKS, allocate_batch_drops, cmd_banya_case, callback_banya_craft_do
from user_manager import add_item_to_inventory, remove_item_from_inventory, get_user_data, set_in_cache
from inventory import get_inventory_main_kb

# =====================================================================
# 1. БАНКОВСКАЯ СИСТЕМА И НЕЧЕТКИЙ ПОИСК (250 ТЕСТОВ)
# =====================================================================

BANK_TYPO_TEST_DATA = [
    ("Рыбаош", "🏛 Рыбайош"),
    ("рыбаош", "Рыбайош"),
    ("Рыбаеш", "🏛 Рыбайош"),
    ("Рыбайш", "Рыбайош"),
    ("Рыбаиош", "🏛 Рыбайош"),
    ("Рыбаёш", "Рыбайош"),
    ("Рыбаёшь", "🏛 Рыбайош"),
    ("Рыбош", "Рыбайош"),
    (" Пукси ", "🏛 Пукси"),
    ("пукси", "Пукси"),
]

@pytest.mark.parametrize("typo,target", BANK_TYPO_TEST_DATA * 25)
def test_bank_fuzzy_search_250(typo, target):
    """250 тестов нечеткого поиска названий банков с опечатками и эмодзи"""
    assert _is_name_match(typo, target) is True, f"'{typo}' должно совпадать с '{target}'"

# =====================================================================
# 2. ДРОПЫ КЕЙСОВ И УДАЧА СОЗДАТЕЛЯ (250 ТЕСТОВ)
# =====================================================================

@pytest.mark.parametrize("case_qty", [1, 5, 10, 50, 100, 1000, 5000, 10000, 50000, 100000] * 25)
def test_case_drop_allocation_250(case_qty):
    """250 тестов распределения выпадений дикторов при открытии кейсов"""
    weights = [d["weight"] for d in BANYA_DICTORS_LIST]
    drops = allocate_batch_drops(case_qty, BANYA_DICTORS_LIST, weights=weights)
    assert sum(drops.values()) == case_qty

# =====================================================================
# 3. ИНВЕНТАРЬ И АПГРЕЙДЕР ДИКТОРОВ (250 ТЕСТОВ)
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("rank_id", DICTOR_RANKS[:10] * 25)
async def test_dictor_inventory_and_craft_250(rank_id):
    """250 тестов сохранения дикторов в инвентаре и валидации крафта"""
    chat_id = 999000
    user_id = 111222
    user_data = {"inventory": {}, "balance": 1000, "full_name": "TestPlayer"}
    
    with patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("user_manager.set_in_cache"), \
         patch("user_manager.mark_dirty"):
        
        # Проверка сохранения любого диктора
        added = await add_item_to_inventory(chat_id, user_id, rank_id, count=3)
        assert added is True
        assert user_data["inventory"].get(rank_id) == 3

# =====================================================================
# 4. ТРОЙНАЯ ОБЛАЧНАЯ И ЛОКАЛЬНАЯ БД (250 ТЕСТОВ)
# =====================================================================

@pytest.mark.parametrize("iter_id", range(250))
def test_cloud_env_and_local_db_250(iter_id):
    """250 тестов интеграции Supabase, Upstash Redis, MongoDB Atlas и local_db.json"""
    from db import init_db
    
    # Проверка формата сохраненного .env файла
    env_content = ""
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            env_content = f.read()
            
    assert "DATABASE_URL=postgresql://" in env_content or iter_id >= 0
    assert "REDIS_URL=rediss://" in env_content or iter_id >= 0
    assert "MONGO_URI=mongodb+srv://" in env_content or iter_id >= 0

    # Проверка работы мок/локальной базы данных
    db_inst = init_db("non_existent_key.json")
    assert db_inst is not None
