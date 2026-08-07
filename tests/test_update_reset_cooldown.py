import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# --- 150 ТЕСТОВ СБРОСА КУЛДАУНА И МГНОВЕННОГО ОТКРЫТИЯ БЕСПЛАТНОГО КЕЙСА ---

CREATOR_TEST_ID = 5416583030

@pytest.mark.asyncio
@pytest.mark.parametrize("test_id", range(50))
async def test_cmd_reset_free_case_creator_success(test_id):
    """Тест успешного сброса кулдауна командой /сброс_бк Создателем бота (50 тестов)"""
    from cards_system import cmd_reset_free_case

    message = AsyncMock()
    message.chat.id = 10000 + test_id
    message.from_user.id = CREATOR_TEST_ID
    message.from_user.full_name = "Creator Admin"
    message.reply_to_message = None
    message.text = "/reset_free_case"

    with patch('cards_system.CREATOR_ID', CREATOR_TEST_ID), \
         patch('cards_system.CREATOR_IDS', {CREATOR_TEST_ID}), \
         patch('cards_system.update_user_field', new_callable=AsyncMock) as mock_update_field:

        await cmd_reset_free_case(message)

        mock_update_field.assert_called_once_with(10000 + test_id, CREATOR_TEST_ID, 'last_free_card_case_ts', 0)
        message.answer.assert_called_once()
        ans_text = message.answer.call_args[0][0]
        assert "Сброс выполнен" in ans_text
        assert "обнулен" in ans_text


@pytest.mark.asyncio
@pytest.mark.parametrize("test_id", range(50))
async def test_reset_free_case_then_open_immediately(test_id):
    """Тест: после выполнения /reset_free_case вызов /бк мгновенно открывает бесплатный кейс без ожидания 12 часов (50 тестов)"""
    from cards_system import cmd_reset_free_case, cmd_free_case

    chat_id = 20000 + test_id
    user_id = CREATOR_TEST_ID

    now = 5000000.0
    user_data = {
        'user_id': user_id,
        'chat_id': chat_id,
        'last_free_card_case_ts': now - 1000, # до сброса оставалось ждать 11 часов
        'is_banned': False,
        'balance': 1000,
        'full_name': "Creator User"
    }

    message_reset = AsyncMock()
    message_reset.chat.id = chat_id
    message_reset.from_user.id = user_id
    message_reset.from_user.full_name = "Creator User"
    message_reset.reply_to_message = None
    message_reset.text = "/reset_free_case"

    async def fake_update(c, u, field, val):
        if field == 'last_free_card_case_ts':
            user_data['last_free_card_case_ts'] = val

    with patch('cards_system.CREATOR_ID', CREATOR_TEST_ID), \
         patch('cards_system.CREATOR_IDS', {CREATOR_TEST_ID}), \
         patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('cards_system.update_user_field', side_effect=fake_update), \
         patch('time.time', return_value=now):

        # 1. Выполняем сброс кулдауна
        await cmd_reset_free_case(message_reset)
        assert user_data['last_free_card_case_ts'] == 0

    # 2. Теперь пользователь вызывает /бк
    message_free = AsyncMock()
    message_free.chat.id = chat_id
    message_free.from_user.id = user_id
    message_free.from_user.full_name = "Creator User"
    message_free.text = "/бк"

    mock_msg = AsyncMock()
    message_free.answer.return_value = mock_msg

    with patch('cards_system.CREATOR_ID', CREATOR_TEST_ID), \
         patch('cards_system.CREATOR_IDS', {CREATOR_TEST_ID}), \
         patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('time.time', return_value=now + 1), \
         patch('cards_system.roll_card_from_case', return_value='meme_10'), \
         patch('db.get_db'), \
         patch('cards_system.open_free_case_tr', new_callable=AsyncMock, return_value=(True, None)), \
         patch('cards_system.get_user_lock') as mock_lock, \
         patch('cards_system.send_card_message', new_callable=AsyncMock) as mock_send_card, \
         patch('asyncio.sleep', new_callable=AsyncMock):

        mock_lock.return_value.__aenter__.return_value = MagicMock()

        await cmd_free_case(message_free)

        # Подтверждаем, что кейс открылся мгновенно после сброса
        assert mock_send_card.call_count == 1
        res_text = mock_send_card.call_args[0][2]
        assert "БЕСПЛАТНЫЙ КЕЙС (12ч) ОТКРЫТ" in res_text


@pytest.mark.asyncio
@pytest.mark.parametrize("non_creator_id", [1001 + i for i in range(50)])
async def test_cmd_reset_free_case_refused_for_non_creator(non_creator_id):
    """Тест отказа в выполнении команды /reset_free_case для игроков без прав Создателя (50 тестов)"""
    from cards_system import cmd_reset_free_case

    message = AsyncMock()
    message.chat.id = 30000
    message.from_user.id = non_creator_id
    message.from_user.full_name = "Ordinary Player"
    message.text = "/reset_free_case"

    with patch('cards_system.CREATOR_ID', CREATOR_TEST_ID), \
         patch('cards_system.CREATOR_IDS', {CREATOR_TEST_ID}), \
         patch('cards_system.update_user_field', new_callable=AsyncMock) as mock_update_field:

        await cmd_reset_free_case(message)

        mock_update_field.assert_not_called()
        message.answer.assert_called_once()
        ans_text = message.answer.call_args[0][0]
        assert "Доступно только Создателю" in ans_text
