import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# --- ТЕСТЫ СОХРАНЕНИЯ ДИКТОРОВ ПРИ ВАЙПАХ (50 ТЕСТОВ) ---

DICTOR_IDS = [
    "dictor_common", "dictor_simple", "dictor_basic",
    "dictor_uncommon", "dictor_rare", "dictor_epic", "dictor_legendary", "dictor_mythic", "dictor_cosmic", "dictor_divine",
    "dictor_shadow", "dictor_abyss", "dictor_elder", "dictor_chaos", "dictor_void", "dictor_infinity", "dictor_secret", "dictor_emperor", "dictor_ghost", "dictor_immortal"
]

NON_DICTOR_ITEMS = ["car_bugatti", "house_villa", "business_hotel", "phone_iphone", "item_ring"]

@pytest.mark.asyncio
@pytest.mark.parametrize("d_id", DICTOR_IDS)
async def test_wipe_chats_preserves_single_dictor(d_id):
    """Тест сохранения каждого из 20 видов дикторов при батч-вайпе _wipe_chats (20 тестов)"""
    from admin_dashboard import _wipe_chats

    mock_db = MagicMock()
    mock_batch = MagicMock()
    mock_batch.commit = AsyncMock()
    mock_db.batch.return_value = mock_batch

    mock_doc = MagicMock()
    mock_doc.id = "user_101"
    mock_doc.to_dict.return_value = {
        "balance": 1000000,
        "inventory": {
            d_id: 2,
            "car_bugatti": 1,
            "business_hotel": 5
        }
    }

    mock_users_ref = MagicMock()
    mock_users_ref.get = AsyncMock(return_value=[mock_doc])

    mock_chat_doc = MagicMock()
    mock_chat_doc.collection.return_value = mock_users_ref
    mock_db.collection.return_value.document.return_value = mock_chat_doc

    whitelist = {12345: True}
    fields = {"balance": 500, "inventory": {}}

    with patch('admin_dashboard.get_db', return_value=mock_db):
        users_wiped, clans_wiped = await _wipe_chats(whitelist, fields, preserve_dictors=True)

        assert users_wiped == 1
        mock_batch.set.assert_called_once()
        set_args = mock_batch.set.call_args[0][1]
        
        # Диктор сохранился, обычные предметы удалены
        assert set_args["inventory"] == {d_id: 2}
        assert set_args["balance"] == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("dictor_count", range(1, 21))
async def test_wipe_chats_preserves_multiple_dictors(dictor_count):
    """Тест сохранения произвольных наборов из нескольких дикторов при вайпе (20 тестов)"""
    from admin_dashboard import _wipe_chats

    mock_db = MagicMock()
    mock_batch = MagicMock()
    mock_batch.commit = AsyncMock()
    mock_db.batch.return_value = mock_batch

    dictors_inv = {DICTOR_IDS[i]: i + 1 for i in range(dictor_count)}
    full_inv = dict(dictors_inv)
    for item in NON_DICTOR_ITEMS:
        full_inv[item] = 10

    mock_doc = MagicMock()
    mock_doc.id = "user_202"
    mock_doc.to_dict.return_value = {
        "balance": 5000000,
        "inventory": full_inv
    }

    mock_users_ref = MagicMock()
    mock_users_ref.get = AsyncMock(return_value=[mock_doc])

    mock_chat_doc = MagicMock()
    mock_chat_doc.collection.return_value = mock_users_ref
    mock_db.collection.return_value.document.return_value = mock_chat_doc

    whitelist = {99999: True}
    fields = {"balance": 500, "inventory": {}}

    with patch('admin_dashboard.get_db', return_value=mock_db):
        users_wiped, _ = await _wipe_chats(whitelist, fields, preserve_dictors=True)

        assert users_wiped == 1
        set_args = mock_batch.set.call_args[0][1]
        
        # Все дикторы сохранились, а обычные предметы сбросились
        assert set_args["inventory"] == dictors_inv


@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(5))
async def test_wipe_user_data_preserves_dictors(idx):
    """Тест сохранения дикторов в функции индивидуального вайпа wipe_user_data (5 тестов)"""
    from user_manager import wipe_user_data

    user_inv = {
        "dictor_legendary": 1,
        "dictor_divine": 3,
        "car_ferrari": 1
    }

    mock_ref = AsyncMock()
    mock_lock = AsyncMock()

    with patch('user_manager.get_user_lock') as mock_get_lock, \
         patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_data, \
         patch('user_manager.invalidate_user_cache') as mock_inv_cache:

        mock_get_lock.return_value.__aenter__.return_value = mock_lock
        mock_get_data.return_value = {
            'full_name': 'PlayerOne',
            'is_banned': False,
            'inventory': user_inv
        }

        res = await wipe_user_data(123, 456, preserve_dictors=True)

        assert res is True
        mock_ref.set.assert_called_once()
        saved_data = mock_ref.set.call_args[0][0]

        assert saved_data['inventory'] == {"dictor_legendary": 1, "dictor_divine": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(5))
async def test_wipe_user_data_force_wipe_dictors(idx):
    """Тест полного сброса включая дикторов, если preserve_dictors=False (5 тестов)"""
    from user_manager import wipe_user_data

    user_inv = {
        "dictor_common": 5,
        "item_gold": 10
    }

    mock_ref = AsyncMock()
    mock_lock = AsyncMock()

    with patch('user_manager.get_user_lock') as mock_get_lock, \
         patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_data, \
         patch('user_manager.invalidate_user_cache'):

        mock_get_lock.return_value.__aenter__.return_value = mock_lock
        mock_get_data.return_value = {
            'full_name': 'PlayerTwo',
            'inventory': user_inv
        }

        res = await wipe_user_data(123, 456, preserve_dictors=False)

        assert res is True
        saved_data = mock_ref.set.call_args[0][0]

        # При принудительном выключении иммунитета инвентарь пуст
        assert saved_data['inventory'] == {}
