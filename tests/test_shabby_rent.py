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
    assert EARLY_RENT_PAY_SECONDS == 86400
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

    # Case 3: Rent has plenty of time (30 hours left > 24h)
    bank_data_plenty = {"rent_paid_until": now + 108000, "capital": 100000}
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
        "rent_paid_until": now + 120000,  # 33 hours left > 24 hours
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


def test_wadiya_one_time_relocation_40_percent():
    from shabby_bank import check_and_apply_shabby_decay

    bank_data = {
        "capital": 1_000_000,
        "durability": 60,
        "rent_paid_until": int(time.time()) - 500,
        "last_incident_time": int(time.time()) - 5000,
    }

    updates, text = check_and_apply_shabby_decay(bank_data)
    assert updates["wadiya_relocated"] is True
    assert updates["wadiya_relocation_paid"] == 400_000
    assert updates["capital"] == 600_000
    assert updates["durability"] == 100
    assert updates["oil_barrels"] == 1000
    assert "40%" in text
    assert "ВАДИЯ" in text.upper()

    # Second run must NOT deduct 40% again
    bank_data.update(updates)
    updates2, _ = check_and_apply_shabby_decay(bank_data)
    assert "wadiya_relocated" not in updates2
    assert updates2.get("capital", 600_000) == 600_000


@pytest.mark.asyncio
async def test_wadiya_aladeen_verdict_and_oil():
    bank_data = {
        "capital": 500_000,
        "oil_barrels": 1000,
        "last_aladeen_time": 0,
        "inspection_anger": 50,
    }
    ok, msg, updates = await execute_shabby_repair(1, 6896326008, "aladeen", bank_data)
    assert ok is True
    assert "АЛАДИН" in msg.upper() or "ШПИЛЮ" in msg.upper()
    assert "last_aladeen_time" in updates

    # Cooldown check
    bank_data.update(updates)
    ok2, msg2, _ = await execute_shabby_repair(1, 6896326008, "aladeen", bank_data)
    assert ok2 is False
    assert "мин." in msg2


@pytest.mark.asyncio
async def test_wadiya_relocation_posts_chat_announcement():
    from profile_bank import generate_bank_main_stats
    from shabby_bank import format_wadiya_relocation_announcement

    bank_data = {
        "banker_id": 6896326008,
        "banker_name": "Диктор",
        "name": "Доисторический",
        "is_shabby": True,
        "capital": 1_000_000,
        "rent_paid_until": int(time.time()) + 10000,
    }

    sample = format_wadiya_relocation_announcement({**bank_data, "capital": 600_000}, 400_000)
    assert len(sample) <= 1024
    assert "Доисторический" in sample
    assert "ВАДИ" in sample.upper()

    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()
    mock_bot.send_message = AsyncMock()

    mock_query = MagicMock()
    mock_query.where.return_value = mock_query
    mock_query.get = AsyncMock(return_value=[])
    mock_col = MagicMock()
    mock_col.where.return_value = mock_query
    mock_chat_doc = MagicMock()
    mock_chat_doc.collection.return_value = mock_col
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_chat_doc

    with patch("profile_bank.get_db", return_value=mock_db), \
         patch("profile_bank.create_or_update_bank", new=AsyncMock()), \
         patch("profile_bank.get_shabby_bank_input_file", return_value="mock_photo"):
        await generate_bank_main_stats(-1002321279920, 6896326008, bank_data, bot=mock_bot)

    mock_bot.send_photo.assert_awaited_once()
    assert mock_bot.send_photo.call_args.kwargs["chat_id"] == -1002321279920
    assert "Доисторический" in mock_bot.send_photo.call_args.kwargs["caption"]


@pytest.mark.asyncio
async def test_startup_wadiya_migration_cleans_40_percent_and_announces():
    import creator

    mock_doc_y = MagicMock(exists=True)
    mock_doc_y.to_dict.return_value = {"sent": True}
    mock_doc_w = MagicMock(exists=False)
    mock_doc_w.to_dict.return_value = {}
    mock_doc_done = MagicMock(exists=True)
    mock_doc_done.to_dict.return_value = {"sent": True}

    mock_ref_w = MagicMock()
    mock_ref_w.get = AsyncMock(return_value=mock_doc_w)
    mock_ref_w.set = AsyncMock()
    mock_ref_done = MagicMock()
    mock_ref_done.get = AsyncMock(return_value=mock_doc_done)

    def _sys_doc(name):
        if name == "wadiya_relocation_v1":
            return mock_ref_w
        return mock_ref_done

    bank_doc = MagicMock()
    bank_doc.id = "6896326008"
    bank_doc.to_dict.return_value = {
        "banker_id": 6896326008,
        "banker_name": "Диктор",
        "name": "Доисторический",
        "capital": 1_000_000,
        "is_shabby": True,
    }
    bank_doc_ref = MagicMock()
    bank_doc_ref.set = AsyncMock()

    banks_col = MagicMock()
    banks_col.get = AsyncMock(return_value=[bank_doc])
    banks_col.document.return_value = bank_doc_ref

    chat_doc = MagicMock()
    chat_doc.collection.return_value = banks_col

    sys_col = MagicMock()
    sys_col.document.side_effect = _sys_doc
    chats_col = MagicMock()
    chats_col.document.return_value = chat_doc

    def _col(name):
        if name == "system_actions":
            return sys_col
        return chats_col

    mock_db = MagicMock()
    mock_db.collection.side_effect = _col

    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_message = AsyncMock()

    with patch("db.get_db", return_value=mock_db), \
         patch("whitelist.get_whitelist", AsyncMock(return_value={-1002321279920: "Main"})):
        await creator.check_and_send_pending_actions(bot)

    bank_doc_ref.set.assert_awaited_once()
    saved_updates = bank_doc_ref.set.call_args[0][0]
    assert saved_updates["capital"] == 600_000
    assert saved_updates["wadiya_relocation_paid"] == 400_000
    assert saved_updates["wadiya_relocated"] is True
    bot.send_photo.assert_awaited_once()
    assert "Доисторический" in bot.send_photo.call_args.kwargs["caption"]
    mock_ref_w.set.assert_awaited_once()

