import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import types
from shabby_bank import (
    COST_PAY_RENT,
    DAILY_RENT_SECONDS,
    EARLY_RENT_PAY_SECONDS,
    get_shabby_bank_kb,
    execute_shabby_repair,
    format_shabby_bank_stats,
)
from profile_bank import cmd_pay_rent


def test_early_rent_constants():
    assert EARLY_RENT_PAY_SECONDS == 7200
    assert DAILY_RENT_SECONDS == 86400
    assert COST_PAY_RENT == 50000


def test_shabby_bank_kb_rent_buttons():
    now = int(time.time())

    # Case 1: Rent expired
    bank_data_expired = {"rent_paid_until": now - 100, "capital": 100000}
    kb_expired = get_shabby_bank_kb(12345, bank_data_expired)
    texts_expired = [btn.text for row in kb_expired.inline_keyboard for btn in row]
    assert any("Оплатить аренду" in t for t in texts_expired)

    # Case 2: Rent expiring soon (within 2 hours, e.g. 1 hour left)
    bank_data_soon = {"rent_paid_until": now + 3600, "capital": 100000}
    kb_soon = get_shabby_bank_kb(12345, bank_data_soon)
    texts_soon = [btn.text for row in kb_soon.inline_keyboard for btn in row]
    assert any("Продлить аренду" in t for t in texts_soon)

    # Case 3: Rent has plenty of time (10 hours left)
    bank_data_plenty = {"rent_paid_until": now + 36000, "capital": 100000}
    kb_plenty = get_shabby_bank_kb(12345, bank_data_plenty)
    texts_plenty = [btn.text for row in kb_plenty.inline_keyboard for btn in row]
    assert not any("аренду" in t.lower() for t in texts_plenty)


def test_format_shabby_bank_stats_rent_warning():
    now = int(time.time())
    # 30 minutes left -> warning
    bank_data = {
        "name": "Доисторический банк",
        "capital": 100000,
        "rent_paid_until": now + 1800,
        "durability": 50,
        "fire_risk": 20,
        "rats_infestation": 20,
        "babki_queue": 20,
        "inspection_anger": 20,
        "power_grid": True,
    }
    stats = format_shabby_bank_stats(1, 1, bank_data, 5, 50000, 0, 0)
    assert "Скоро истечет" in stats or "Продлите аренду" in stats


@pytest.mark.asyncio
async def test_execute_shabby_repair_rent_early_success():
    now = int(time.time())
    bank_data = {
        "capital": 200000,
        "rent_paid_until": now + 3600,  # 1 hour left
    }
    success, msg, updates = await execute_shabby_repair(1, 12345, "rent", bank_data)
    assert success is True
    assert updates["capital"] == 200000 - COST_PAY_RENT
    assert updates["rent_paid_until"] == (now + 3600) + DAILY_RENT_SECONDS
    assert "продлена" in msg.lower()


@pytest.mark.asyncio
async def test_execute_shabby_repair_rent_too_early():
    now = int(time.time())
    bank_data = {
        "capital": 200000,
        "rent_paid_until": now + 40000,  # 11 hours left
    }
    success, msg, updates = await execute_shabby_repair(1, 12345, "rent", bank_data)
    assert success is False
    assert "ещё активна" in msg
    assert not updates


@pytest.mark.asyncio
async def test_cmd_pay_rent_handler():
    msg = AsyncMock(spec=types.Message)
    msg.chat = MagicMock(id=-1002321279920)
    msg.from_user = MagicMock(id=6896326008)
    msg.answer = AsyncMock()

    now = int(time.time())
    bank_data = {
        "banker_id": 6896326008,
        "is_shabby": True,
        "capital": 100000,
        "rent_paid_until": now - 100,  # expired
    }

    with patch("profile_bank.get_user_data", new=AsyncMock(return_value={"is_banker": True})), \
         patch("profile_bank.get_bank_info", new=AsyncMock(return_value=bank_data)), \
         patch("profile_bank.create_or_update_bank", new=AsyncMock()) as mock_save:

        await cmd_pay_rent(msg)
        assert msg.answer.called
        assert mock_save.called
