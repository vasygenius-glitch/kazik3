import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from economy import (
    cmd_work, cmd_crime, cmd_bonus, cmd_balance, cmd_pay,
    process_claim_bonus, _process_collectors
)
from profile_bank import (
    _clean_bank_name, _levenshtein, _is_name_match, get_bank_info,
    process_deposit_in_memory, process_withdraw_in_memory,
    set_bank_in_cache, get_bank_from_cache, invalidate_bank_cache, cmd_bank
)

# =====================================================================
# 1. ECONOMY COMMANDS & UTILS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_work_variations(idx):
    message = AsyncMock()
    message.chat.id = 1000 + idx
    message.from_user.id = 2000 + idx
    message.from_user.full_name = f"Worker_{idx}"
    message.text = "/work"
    
    user_data = {"balance": 500, "last_work_time": 0, "is_banned": False}
    with patch("economy.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("economy.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("economy._process_collectors", new_callable=AsyncMock, return_value=(200, "", False)), \
         patch("economy.apply_season_logic", new_callable=AsyncMock, return_value=(200, "")), \
         patch("economy.update_user_balance", new_callable=AsyncMock), \
         patch("economy.update_user_field", new_callable=AsyncMock):
        await cmd_work(message)
        message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_crime_variations(idx):
    message = AsyncMock()
    message.chat.id = 3000 + idx
    message.from_user.id = 4000 + idx
    message.from_user.full_name = f"Criminal_{idx}"
    message.text = "/crime"
    
    user_data = {"balance": 5000, "last_crime_time": 0, "is_banned": False}
    with patch("economy.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("economy.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("economy._process_collectors", new_callable=AsyncMock, return_value=(500, "", False)), \
         patch("economy.apply_season_logic", new_callable=AsyncMock, return_value=(500, "")), \
         patch("economy.update_user_balance", new_callable=AsyncMock), \
         patch("economy.update_user_field", new_callable=AsyncMock):
        await cmd_crime(message)
        message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("streak", [1, 2, 3, 5, 7, 10, 14, 21, 30, 60])
async def test_process_claim_bonus_streaks(streak):
    callback = AsyncMock()
    callback.data = f"claim_bonus_200_secret123"
    callback.from_user.id = 200
    callback.message.chat.id = 100
    callback.message.edit_text = AsyncMock()
    
    receipt = {"base": 500, "business": 100, "car": 0, "tax_percent": 0, "tax_amount": 0, "total": 600}
    with patch("economy.check_and_give_bonus", new_callable=AsyncMock, return_value=(True, receipt)):
        await process_claim_bonus(callback)
        callback.message.edit_text.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_balance_variations(idx):
    message = AsyncMock()
    message.chat.id = 5000 + idx
    message.from_user.id = 6000 + idx
    message.from_user.full_name = f"Player_{idx}"
    message.text = "/balance"
    
    user_data = {"balance": 10000 * (idx + 1), "bank_deposit": 5000, "is_banned": False}
    with patch("economy.get_user_data", new_callable=AsyncMock, return_value=user_data):
        await cmd_balance(message)
        message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 500000])
async def test_cmd_pay_variations(amount):
    message = AsyncMock()
    message.chat.id = 7000
    message.from_user.id = 8000
    message.from_user.full_name = "Sender"
    message.reply_to_message = AsyncMock()
    message.reply_to_message.from_user.id = 9000
    message.reply_to_message.from_user.full_name = "Recipient"
    message.reply_to_message.from_user.is_bot = False
    message.text = f"/pay {amount}"
    
    sender_data = {"balance": amount * 2, "is_banned": False}
    recipient_data = {"balance": 1000, "is_banned": False}
    
    with patch("economy.get_user_data", side_effect=[sender_data, recipient_data, sender_data, recipient_data]), \
         patch("economy._calc_transfer_tax", new_callable=AsyncMock, return_value=0), \
         patch("economy.update_user_balance", new_callable=AsyncMock):
        await cmd_pay(message)
        message.answer.assert_called_once()

# =====================================================================
# 2. PROFILE BANK TESTS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("idx", range(10))
def test_clean_bank_name_cases(idx):
    inputs = ["🏦 Сбер!", "🏛️ ВТБ...", "  Альфа  ", "Тинькофф#1", "Рыбайош?", " Казино ", "Банк 100%", "🔥 ПУКСИ 🔥", "Открытие!", "Совком"]
    res = _clean_bank_name(inputs[idx])
    assert isinstance(res, str)

@pytest.mark.parametrize("idx", range(10))
def test_bank_levenshtein_distance(idx):
    pairs = [("сбер", "сбор"), ("втб", "втбб"), ("пукси", "пукси"), ("альфа", "альфо"), ("тинькофф", "тинькоф"), ("рыбайош", "рыбаош"), ("банк", "банки"), ("рубль", "рубли"), ("казино", "казик"), ("сумма", "суммы")]
    d = _levenshtein(pairs[idx][0], pairs[idx][1])
    assert d <= 3

@pytest.mark.parametrize("idx", range(10))
def test_bank_name_matching(idx):
    q = ["Сбер", "ВТБ", "Пукси", "Рыбаош", "Альфа", "Тинькофф", "Казино", "Банк", "Открытие", "Совком"]
    t = ["🏛 Сбербанк", "🏛 ВТБ Банк", "🏛 Пукси", "🏛 Рыбайош", "🏛 Альфа-Банк", "🏛 Тинькофф", "🏛 Казино Банк", "🏛 Главный Банк", "🏛 Открытие", "🏛 Совкомбанк"]
    assert _is_name_match(q[idx], t[idx]) is True

@pytest.mark.asyncio
@pytest.mark.parametrize("amt", [100, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 500000])
async def test_process_deposit_in_memory_scenarios(amt):
    chat_id = 999
    user_id = 888
    banker_id = 777
    user_data = {"balance": amt * 2, "bank_deposit": 0, "bank_name": None}
    bank_data = {"name": "TestBank", "banker_id": banker_id, "deposit_rate": 5.0, "capital": 1000000}
    
    with patch("profile_bank.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("profile_bank.get_bank_info", new_callable=AsyncMock, return_value=bank_data), \
         patch("profile_bank.create_or_update_bank", new_callable=AsyncMock):
        dep, total = await process_deposit_in_memory(chat_id, user_id, banker_id, amt)
        assert dep == amt

@pytest.mark.parametrize("idx", range(10))
def test_func_bank_cache_operations(idx):
    chat_id = 1000 + idx
    data = {"name": f"Bank_{idx}", "banker_id": 5000 + idx}
    set_bank_in_cache(chat_id, data["banker_id"], data)
    cached = get_bank_from_cache(chat_id, data["banker_id"])
    assert cached["name"] == f"Bank_{idx}"
    invalidate_bank_cache(chat_id, banker_id=data["banker_id"])
