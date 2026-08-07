import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# --- 100 ТЕСТОВ БЕСПЛАТНОГО КЕЙСА (12 ЧАСОВ И ТРАНЗАКЦИЙ) ---

@pytest.mark.asyncio
@pytest.mark.parametrize("remaining_sec, expected_hours, expected_mins", [
    (43200, 12, 0),
    (43199, 11, 59),
    (39600, 11, 0),
    (36000, 10, 0),
    (28800, 8, 0),
    (23450, 6, 30),
    (18000, 5, 0),
    (7200, 2, 0),
    (3600, 1, 0),
    (1800, 0, 30),
    (600, 0, 10),
    (60, 0, 1),
    (1, 0, 0),
    (40000, 11, 6),
    (15000, 4, 10),
    (9999, 2, 46),
    (5555, 1, 32),
    (1234, 0, 20),
    (300, 0, 5),
    (10, 0, 0),
])
async def test_free_case_cooldown_formatting(remaining_sec, expected_hours, expected_mins):
    """Тест точного расчета оставшегося времени кулдауна бесплатного кейса (20 тестов)"""
    from cards_system import cmd_free_case

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    message.from_user.full_name = "Test User"

    now = 1000000.0
    last_ts = now - (43200 - remaining_sec)

    user_data = {
        'last_free_card_case_ts': last_ts,
        'is_banned': False
    }

    with patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('time.time', return_value=now):

        await cmd_free_case(message)

        message.answer.assert_called_once()
        ans_text = message.answer.call_args[0][0]
        assert "Бесплатный кейс карточек еще недоступен" in ans_text
        assert f"{expected_hours}ч {expected_mins}мин" in ans_text


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed_sec", [
    43200, 43201, 45000, 50000, 86400, 100000, 200000, 500000, 1000000, 43210,
    43300, 44000, 60000, 70000, 90000, 120000, 150000, 180000, 250000, 500000
])
async def test_free_case_success_when_cooldown_expired(elapsed_sec):
    """Тест успешного открытия бесплатного кейса после истечения кулдауна 12 часов (20 тестов)"""
    from cards_system import cmd_free_case

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    message.from_user.full_name = "Test User"

    now = 2000000.0
    last_ts = now - elapsed_sec

    user_data = {
        'last_free_card_case_ts': last_ts,
        'is_banned': False
    }

    mock_msg = AsyncMock()
    message.answer.return_value = mock_msg

    with patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('time.time', return_value=now), \
         patch('cards_system.roll_card_from_case', return_value='meme_1'), \
         patch('db.get_db'), \
         patch('cards_system.open_free_case_tr', new_callable=AsyncMock, return_value=(True, None)), \
         patch('cards_system.get_user_lock') as mock_lock, \
         patch('cards_system.invalidate_user_cache'), \
         patch('cards_system.send_card_message', new_callable=AsyncMock) as mock_send_card, \
         patch('asyncio.sleep', new_callable=AsyncMock):

        mock_lock.return_value.__aenter__.return_value = MagicMock()

        await cmd_free_case(message)

        assert mock_send_card.call_count == 1
        res_text = mock_send_card.call_args[0][2]
        assert "БЕСПЛАТНЫЙ КЕЙС (12ч) ОТКРЫТ" in res_text


@pytest.mark.asyncio
@pytest.mark.parametrize("last_ts, now_ts, expected_success", [
    (0, 1000, True),
    (100, 100 + 43200, True),
    (100, 100 + 43199, False),
    (500, 500 + 20000, False),
    (500, 500 + 43200, True),
    (1000, 1000 + 100, False),
    (1000, 1000 + 43201, True),
    (0, 43199, True),
    (0, 43200, True),

    (100000, 100000 + 43199, False),
    (100000, 100000 + 43200, True),
    (100000, 100000 + 86400, True),
    (5000, 5000 + 40000, False),
    (5000, 5000 + 43250, True),
    (123456, 123456 + 10, False),
    (123456, 123456 + 43200, True),
    (777777, 777777 + 43190, False),
    (777777, 777777 + 43200, True),
    (999999, 999999 + 43199, False),
    (999999, 999999 + 43200, True),
])
async def test_open_free_case_tr_logic(last_ts, now_ts, expected_success):
    """Тест транзакционной функции open_free_case_tr в user_manager (20 тестов)"""
    from user_manager import open_free_case_tr

    mock_ref = MagicMock()
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True
    mock_snapshot.to_dict.return_value = {
        'last_free_card_case_ts': last_ts,
        'meme_cards': {}
    }

    mock_tr = MagicMock()

    with patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=mock_snapshot), \
         patch('time.time', return_value=now_ts):

        success, err = await open_free_case_tr(mock_tr, 123, 456, 'meme_5')

        assert success is expected_success
        if expected_success:
            assert err is None
            assert mock_tr.update.call_count == 1
            updates = mock_tr.update.call_args[0][1]
            assert updates['last_free_card_case_ts'] == now_ts
            assert updates['meme_cards']['meme_5'] == 1
        else:
            assert err is not None
            assert "доступен через" in err


@pytest.mark.asyncio
@pytest.mark.parametrize("card_id", [f"meme_{i}" for i in range(1, 21)])
async def test_free_case_callback_handler_success(card_id):
    """Тест инлайн-интерактивного вызова открывающего инлайн-кнопкой бесплатный кейс (20 тестов)"""
    from cards_system import callback_open_free_case

    callback = AsyncMock()
    callback.message.chat.id = 12345
    callback.from_user.id = 67890

    user_data = {
        'last_free_card_case_ts': 0,
        'is_banned': False
    }

    with patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('time.time', return_value=100000.0), \
         patch('cards_system.roll_card_from_case', return_value=card_id), \
         patch('db.get_db'), \
         patch('cards_system.open_free_case_tr', new_callable=AsyncMock, return_value=(True, None)), \
         patch('cards_system.get_user_lock') as mock_lock, \
         patch('cards_system.invalidate_user_cache'), \
         patch('cards_system.send_card_message', new_callable=AsyncMock) as mock_send_card, \
         patch('asyncio.sleep', new_callable=AsyncMock):

        mock_lock.return_value.__aenter__.return_value = MagicMock()

        await callback_open_free_case(callback)

        callback.answer.assert_called_with("Открываем бесплатный кейс...")
        assert mock_send_card.call_count == 1
        assert "БЕСПЛАТНЫЙ КЕЙС (12ч) ОТКРЫТ" in mock_send_card.call_args[0][2]


@pytest.mark.asyncio
@pytest.mark.parametrize("test_id", range(20))
async def test_free_case_banned_and_user_lock(test_id):
    """Тест защиты от вызова бесплатного кейса забаненными пользователями (20 тестов)"""
    from cards_system import cmd_free_case, callback_open_free_case

    message = AsyncMock()
    message.chat.id = 12345 + test_id
    message.from_user.id = 67890 + test_id

    user_data = {'is_banned': True}

    with patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await cmd_free_case(message)
        message.answer.assert_not_called()

    callback = AsyncMock()
    callback.message.chat.id = 12345 + test_id
    callback.from_user.id = 67890 + test_id

    with patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await callback_open_free_case(callback)
        callback.answer.assert_called_once_with("Вы забанены.", show_alert=True)
