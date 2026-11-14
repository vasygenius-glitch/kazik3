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
    assert COST_PAY_RENT == 75000


def test_shabby_bank_kb_rent_buttons():
    now = int(time.time())

    # Case 1: Rent expired
    bank_data_expired = {"rent_paid_until": now - 100, "capital": 100000}
    kb_expired = get_shabby_bank_kb(12345, bank_data_expired)
    texts_expired = [btn.text for row in kb_expired.inline_keyboard for btn in row]
    assert any("Оплатить участок" in t or "Оплатить аренду" in t for t in texts_expired)

    # Case 2: Rent expiring soon (within 2 hours, e.g. 1 hour left)
    bank_data_soon = {"rent_paid_until": now + 3600, "capital": 100000}
    kb_soon = get_shabby_bank_kb(12345, bank_data_soon)
    texts_soon = [btn.text for row in kb_soon.inline_keyboard for btn in row]
    assert any("Продлить участок" in t or "Продлить аренду" in t for t in texts_soon)

    # Case 3: Rent has plenty of time (10 hours left)
    bank_data_plenty = {"rent_paid_until": now + 36000, "capital": 100000}
    kb_plenty = get_shabby_bank_kb(12345, bank_data_plenty)
    texts_plenty = [btn.text for row in kb_plenty.inline_keyboard for btn in row]
    assert not any("участок" in t.lower() or "аренду" in t.lower() for t in texts_plenty)


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
    assert "продлен" in msg.lower()


@pytest.mark.asyncio
async def test_execute_shabby_repair_rent_too_early():
    now = int(time.time())
    bank_data = {
        "capital": 200000,
        "rent_paid_until": now + 40000,  # 11 hours left
    }
    success, msg, updates = await execute_shabby_repair(1, 12345, "rent", bank_data)
    assert success is False
    assert "ещё оплачен" in msg or "ещё активна" in msg
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


@pytest.mark.asyncio
async def test_cmd_bank_stats_caption_safety():
    from profile_bank import cmd_bank_stats, _safe_edit_bank_msg

    # Case 1: Normal length
    msg = AsyncMock(spec=types.Message)
    msg.chat = MagicMock(id=-1002321279920)
    msg.from_user = MagicMock(id=6896326008)
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()

    bank_data = {
        "banker_id": 6896326008,
        "is_shabby": True,
        "name": "Доисторический VIP-банк",
        "capital": 100000,
        "rent_paid_until": int(time.time()) + 10000,
    }

    with patch("profile_bank.get_user_data", new=AsyncMock(return_value={"is_banker": True})), \
         patch("diseases.get_active_diseases", new=AsyncMock(return_value=[])), \
         patch("profile_bank.get_bank_info", new=AsyncMock(return_value=bank_data)), \
         patch("profile_bank.generate_bank_main_stats", new=AsyncMock(return_value="A" * 500)), \
         patch("os.path.exists", return_value=True):

        await cmd_bank_stats(msg)
        assert msg.answer_photo.called
        call_kwargs = msg.answer_photo.call_args[1]
        assert len(call_kwargs["caption"]) == 500

    # Case 2: Text exceeds Telegram 1024 limit
    msg_long = AsyncMock(spec=types.Message)
    msg_long.chat = MagicMock(id=-1002321279920)
    msg_long.from_user = MagicMock(id=6896326008)
    msg_long.answer = AsyncMock()
    msg_long.answer_photo = AsyncMock()

    with patch("profile_bank.get_user_data", new=AsyncMock(return_value={"is_banker": True})), \
         patch("diseases.get_active_diseases", new=AsyncMock(return_value=[])), \
         patch("profile_bank.get_bank_info", new=AsyncMock(return_value=bank_data)), \
         patch("profile_bank.generate_bank_main_stats", new=AsyncMock(return_value="A" * 1200)), \
         patch("os.path.exists", return_value=True):

        await cmd_bank_stats(msg_long)
        assert msg_long.answer_photo.called
        assert msg_long.answer.called

    # Case 3: _safe_edit_bank_msg truncation
    msg_edit = AsyncMock(spec=types.Message)
    msg_edit.photo = [MagicMock()]
    msg_edit.edit_caption = AsyncMock()

    await _safe_edit_bank_msg(msg_edit, "B" * 1200)
    assert msg_edit.edit_caption.called
    caption_arg = msg_edit.edit_caption.call_args[1]["caption"]
    assert len(caption_arg) <= 1024

