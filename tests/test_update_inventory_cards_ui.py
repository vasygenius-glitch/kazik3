import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# --- 100 ТЕСТОВ ИНТЕРФЕЙСА ИНВЕНТАРЯ И ОТОБРАЖЕНИЯ КАРТОЧЕК ---

@pytest.mark.asyncio
@pytest.mark.parametrize("unique_count, total_count", [
    (1, 1),
    (2, 2),
    (5, 10),
    (10, 25),
    (20, 50),
    (50, 100),
    (100, 200),
    (150, 300),
    (199, 500),
    (200, 1000),
    (3, 5),
    (7, 14),
    (12, 30),
    (25, 60),
    (40, 90),
    (60, 150),
    (80, 210),
    (110, 270),
    (140, 350),
    (180, 450),
])
async def test_cmd_inventory_cards_summary_text(unique_count, total_count):
    """Тест форматирования текста коллекции карточек свинок в инвентаре /inv (20 тестов)"""
    from inventory import cmd_inventory

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890

    # Заполняем unique_count уникальных ключей карточек
    meme_cards = {f"meme_{i}": (total_count // unique_count) for i in range(1, unique_count + 1)}
    
    user_data = {
        'inventory': {'item_gold': 1},
        'biz_levels': {},
        'meme_cards': meme_cards,
        'is_banned': False
    }

    item_info = {'name': 'Золотой слиток', 'price': 1000}

    with patch('inventory.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('shop.ITEMS', {'item_gold': item_info}):

        await cmd_inventory(message)

        message.answer.assert_called_once()
        ans_text = message.answer.call_args[0][0]
        assert "🎒 <b>ВАШ ИНВЕНТАРЬ И КОЛЛЕКЦИЯ</b>" in ans_text
        assert f"<code>{unique_count}/200</code>" in ans_text
        assert f"всего {sum(meme_cards.values())} шт." in ans_text


@pytest.mark.asyncio
@pytest.mark.parametrize("unique_count", range(1, 21))
async def test_get_inventory_main_kb_buttons(unique_count):
    """Тест генерации кнопок инвентаря с кнопкой бесплатного кейса и коллекции карточек (20 тестов)"""
    from inventory import get_inventory_main_kb

    inventory = {'item_gold': 1}
    biz_levels = {}
    meme_cards = {f"meme_{i}": 1 for i in range(1, unique_count + 1)}

    markup = get_inventory_main_kb(inventory, biz_levels, meme_cards)
    buttons = [btn for row in markup.inline_keyboard for btn in row]

    # Кнопка бесплатного кейса
    free_case_btn = next((b for b in buttons if b.callback_data == "open_free_case_cb"), None)
    assert free_case_btn is not None
    assert free_case_btn.text == "🎁 Бесплатный кейс карт (12ч)"

    # Кнопка перехода к коллекции
    coll_btn = next((b for b in buttons if b.callback_data == "card_page_0"), None)
    assert coll_btn is not None
    assert f"({unique_count}/200)" in coll_btn.text


@pytest.mark.asyncio
@pytest.mark.parametrize("unique_count", range(1, 21))
async def test_inv_back_cards_refresh(unique_count):
    """Тест коллбэка возврата в главный инвентарь inv_main с обновлением карточек (20 тестов)"""
    from inventory import inv_back

    callback = AsyncMock()
    callback.message.chat.id = 12345
    callback.from_user.id = 67890

    meme_cards = {f"meme_{i}": 1 for i in range(1, unique_count + 1)}

    user_data = {
        'inventory': {},
        'biz_levels': {},
        'meme_cards': meme_cards
    }

    with patch('inventory.get_user_data', new_callable=AsyncMock, return_value=user_data):

        await inv_back(callback)

        callback.message.edit_text.assert_called_once()
        ans_text = callback.message.edit_text.call_args[0][0]
        assert "🎒 <b>ВАШ ИНВЕНТАРЬ И КОЛЛЕКЦИЯ</b>" in ans_text
        assert f"<code>{unique_count}/200</code>" in ans_text


@pytest.mark.parametrize("multiplier, flat, expected_str", [
    (0.05, 1000, "✨ Множитель • +5.0%\n💰 Доход • +1 000 сыр."),
    (0.02, 400, "✨ Множитель • +2.0%\n💰 Доход • +400 сыр."),
    (0.10, 5000, "✨ Множитель • +10.0%\n💰 Доход • +5 000 сыр."),
    (0.0, 100, "💰 Доход • +100 сыр."),
    (0.01, 0, "✨ Множитель • +1.0%"),
    (0.0, 0, "✨ Бонусы • Отсутствуют"),
    (0.15, 10000, "✨ Множитель • +15.0%\n💰 Доход • +10 000 сыр."),
    (0.03, 750, "✨ Множитель • +3.0%\n💰 Доход • +750 сыр."),
    (0.08, 2500, "✨ Множитель • +8.0%\n💰 Доход • +2 500 сыр."),
    (0.20, 50000, "✨ Множитель • +20.0%\n💰 Доход • +50 000 сыр."),
    (0.005, 50, "✨ Множитель • +0.5%\n💰 Доход • +50 сыр."),
    (0.025, 200, "✨ Множитель • +2.5%\n💰 Доход • +200 сыр."),
    (0.07, 1500, "✨ Множитель • +7.0%\n💰 Доход • +1 500 сыр."),
    (0.12, 8000, "✨ Множитель • +12.0%\n💰 Доход • +8 000 сыр."),
    (0.04, 900, "✨ Множитель • +4.0%\n💰 Доход • +900 сыр."),
    (0.06, 1200, "✨ Множитель • +6.0%\n💰 Доход • +1 200 сыр."),
    (0.09, 3000, "✨ Множитель • +9.0%\n💰 Доход • +3 000 сыр."),
    (0.11, 6000, "✨ Множитель • +11.0%\n💰 Доход • +6 000 сыр."),
    (0.14, 9000, "✨ Множитель • +14.0%\n💰 Доход • +9 000 сыр."),
    (0.18, 20000, "✨ Множитель • +18.0%\n💰 Доход • +20 000 сыр."),
])
def test_format_card_bonuses(multiplier, flat, expected_str):
    """Тест формирования строки бонусов карт format_card_bonuses (20 тестов)"""
    from cards_system import format_card_bonuses

    card = {
        'bonus_multiplier': multiplier,
        'bonus_flat': flat
    }
    res = format_card_bonuses(card)
    assert res == expected_str


@pytest.mark.parametrize("card_qty", range(1, 21))
def test_get_user_meme_bonuses_sum(card_qty):
    """Тест суммы бонусов коллекции карточек пользователей get_user_meme_bonuses (20 тестов)"""
    from user_manager import get_user_meme_bonuses

    user_data = {
        'meme_cards': {f"meme_{i}": 1 for i in range(1, card_qty + 1)}
    }

    res = get_user_meme_bonuses(user_data)
    assert 'multiplier' in res
    assert 'flat' in res
    assert res['multiplier'] >= 0.0
    assert res['flat'] >= 0

