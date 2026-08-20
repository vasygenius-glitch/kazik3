import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from user_manager import (
    resolve_chat_id,
    _normalize_ids,
    get_user_primary_chat,
    _user_primary_chat_cache,
    _user_known_chats_cache,
    record_user_chat_activity,
)
from inventory import parse_owner_from_cb, get_inventory_main_kb
from shop import get_main_shop_kb, get_sell_confirm_kb
from casino_utils import is_confirmation_callback


# ============================================================================
# 1. ТЕСТЫ СИНХРОНИЗАЦИИ ЛС (PM) И ГРУППОВЫХ ЧАТОВ
# ============================================================================

def test_pm_chat_resolution_when_group_known():
    """Проверяет, что при наличии привязанного чата, ЛС chat_id резолвится в group_id."""
    user_id = 7553529465
    group_chat_id = -1002321279920

    _user_primary_chat_cache[user_id] = group_chat_id

    # Проверка resolve_chat_id
    assert resolve_chat_id(user_id, user_id) == group_chat_id
    assert resolve_chat_id(1234567, user_id) == group_chat_id

    # В самой группе ID не меняется
    assert resolve_chat_id(group_chat_id, user_id) == group_chat_id
    assert resolve_chat_id(-1009999999999, user_id) == -1009999999999

    # Проверка нормализации _normalize_ids
    norm_chat, norm_user = _normalize_ids(user_id, user_id)
    assert norm_chat == group_chat_id
    assert norm_user == user_id


def test_pm_chat_resolution_fallback_for_new_user():
    """Проверяет, что для нового пользователя без групп возвращается его собственный ID."""
    unknown_user_id = 999888777
    _user_primary_chat_cache.pop(unknown_user_id, None)

    assert resolve_chat_id(unknown_user_id, unknown_user_id) == unknown_user_id
    norm_chat, norm_user = _normalize_ids(unknown_user_id, unknown_user_id)
    assert norm_chat == unknown_user_id
    assert norm_user == unknown_user_id


@pytest.mark.asyncio
async def test_record_user_chat_activity():
    """Проверяет запись активности в группе и авто-привязку primary_chat."""
    user_id = 111222333
    group_id = -100555444333
    title = "Тестовая баня"

    _user_primary_chat_cache.pop(user_id, None)
    _user_known_chats_cache.pop(user_id, None)

    await record_user_chat_activity(user_id, group_id, title)

    assert get_user_primary_chat(user_id) == group_id
    assert str(group_id) in _user_known_chats_cache[user_id]
    assert _user_known_chats_cache[user_id][str(group_id)]["title"] == title


# ============================================================================
# 2. ТЕСТЫ БЕЗОПАСНОСТИ КНОПОК (BUTTON ANTI-HIJACKING)
# ============================================================================

def test_inventory_parse_owner_from_cb():
    """Проверяет парсинг owner_id из callback_data инвентаря."""
    raw, owner = parse_owner_from_cb("inv_item_семечки_7553529465")
    assert raw == "inv_item_семечки"
    assert owner == 7553529465

    raw2, owner2 = parse_owner_from_cb("inv_page_2_7553529465")
    assert raw2 == "inv_page_2"
    assert owner2 == 7553529465

    raw3, owner3 = parse_owner_from_cb("inv_main_7553529465")
    assert raw3 == "inv_main"
    assert owner3 == 7553529465

    raw4, owner4 = parse_owner_from_cb("inv_close_7553529465")
    assert raw4 == "inv_close"
    assert owner4 == 7553529465


def test_inventory_keyboard_contains_owner_id():
    """Проверяет генерацию кнопок инвентаря с user_id."""
    user_id = 7553529465
    kb = get_inventory_main_kb(
        inventory={"семечки": 1},
        biz_levels={"семечки": 1},
        meme_cards={"meme_1": 1},
        user_id=user_id,
    )
    # Собираем все callback_data
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert f"open_free_case_cb_{user_id}" in callbacks
    assert f"card_page_0_{user_id}" in callbacks
    assert f"inv_item_семечки_{user_id}" in callbacks
    assert f"inv_close_{user_id}" in callbacks


@pytest.mark.asyncio
async def test_shop_keyboards_contain_owner_id():
    """Проверяет генерацию кнопок магазина с user_id."""
    user_id = 7553529465
    kb = await get_main_shop_kb(prestige_level=1, user_id=user_id)
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert f"shop_cat_biz_{user_id}" in callbacks
    assert f"shop_cat_cars_{user_id}" in callbacks
    assert f"shop_cat_prestige_{user_id}" in callbacks
    assert f"shop_to_inv_{user_id}" in callbacks


def test_casino_confirmation_checker():
    """Проверяет распознавание confirmation callback_data."""
    assert is_confirmation_callback("cas_conf_blackjack_500_7553529465")
    assert is_confirmation_callback("cas_conf_slots_1000_7553529465")
    assert is_confirmation_callback("cas_conf_dice_250_7553529465")
    assert is_confirmation_callback("cas_cancel_7553529465")
    assert not is_confirmation_callback("some_other_callback")
