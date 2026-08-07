import pytest
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# --- 150 ТЕСТОВ ОТОБРАЖЕНИЯ ИНФО О КАРТОЧКАХ И ВЫЗОВА ФОТО-СООБЩЕНИЙ ---

@pytest.mark.asyncio
@pytest.mark.parametrize("card_num", range(1, 51))
async def test_cmd_card_info_displays_unique_name_and_photo(card_num):
    """Тест команды /card_info [1-50] с проверкой уникального имени и отправки фото-сообщения (50 тестов)"""
    from cards_system import cmd_card_info, CARDS

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    message.from_user.full_name = "Test User"
    message.text = f"/card_info {card_num}"

    user_data = {
        'meme_cards': {f"meme_{card_num}": 2},
        'is_banned': False
    }

    card_key = f"meme_{card_num}"
    expected_card = CARDS[card_key]

    with patch('cards_system.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('cards_system.send_card_message', new_callable=AsyncMock) as mock_send_card:

        await cmd_card_info(message)

        mock_send_card.assert_called_once()
        sent_card_id = mock_send_card.call_args[0][1]
        sent_text = mock_send_card.call_args[0][2]

        assert sent_card_id == card_key
        assert expected_card['name'] in sent_text
        assert expected_card['description'] in sent_text
        assert "🎒 В инвентаре • 2 шт." in sent_text


@pytest.mark.parametrize("card_num", range(51, 101))
def test_generate_card_image_fallback_creates_valid_png(card_num):
    """Тест генератора запаса картинок generate_card_image_fallback для всех карт (50 тестов)"""
    from cards_system import generate_card_image_fallback

    card_key = f"meme_{card_num}"
    fallback_path = generate_card_image_fallback(card_key)

    assert fallback_path is not None
    assert os.path.exists(fallback_path)
    assert fallback_path.endswith(".png")
    assert os.path.getsize(fallback_path) > 500


@pytest.mark.asyncio
@pytest.mark.parametrize("card_num", range(101, 151))
async def test_send_card_message_guaranteed_photo(card_num):
    """Тест send_card_message: гарантированная высылка фото-сообщения answer_photo для любых карточек (50 тестов)"""
    from cards_system import send_card_message

    message = AsyncMock()
    card_key = f"meme_{card_num}"
    test_text = f"Тестовое описание карточки #{card_num}"

    with patch('cards_system.get_card_photo_source', return_value="https://example.com/test_pig.jpg?query=123"):
        await send_card_message(message, card_key, test_text)

        message.answer_photo.assert_called_once()
        assert message.answer_photo.call_args[1]['photo'] == "https://example.com/test_pig.jpg"
        assert message.answer_photo.call_args[1]['caption'] == test_text
