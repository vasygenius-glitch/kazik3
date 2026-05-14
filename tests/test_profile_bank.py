import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from profile_bank import get_bank_info, create_or_update_bank, _bank_name_to_id_cache, _banks_indexed_chats, _bank_cache

@pytest.fixture(autouse=True)
def clear_caches():
    _bank_name_to_id_cache.clear()
    _banks_indexed_chats.clear()
    _bank_cache.clear()

@pytest.mark.asyncio
async def test_get_bank_info_cache_miss():
    chat_id = 123
    with patch('profile_bank.get_db') as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_banks_ref = MagicMock()
        mock_db.collection.return_value.document.return_value.collection.return_value = mock_banks_ref

        # Mock full scan
        mock_doc1 = MagicMock()
        mock_doc1.id = "456"
        mock_doc1.to_dict.return_value = {'name': 'Tinkoff'}

        mock_doc2 = MagicMock()
        mock_doc2.id = "789"
        mock_doc2.to_dict.return_value = {'name': 'Sberbank'}

        mock_banks_ref.get = AsyncMock(return_value=[mock_doc1, mock_doc2])

        # A bit convoluted to mock chain, so we will replace the internal mock document function
        def fake_get_document(doc_id):
            doc = MagicMock()
            if doc_id == "789":
                doc.exists = True
                doc.to_dict.return_value = {'name': 'Sberbank', 'capital': 1000}
            else:
                doc.exists = False
            return doc

        mock_banks_ref.document.side_effect = lambda doc_id: MagicMock(get=AsyncMock(return_value=fake_get_document(doc_id)))

        result = await get_bank_info(chat_id, "sber")

        assert result is not None
        assert result['name'] == 'Sberbank'
        assert (chat_id, 'sberbank') in _bank_name_to_id_cache
        assert _bank_name_to_id_cache[(chat_id, 'sberbank')] == 789
        assert chat_id in _banks_indexed_chats

@pytest.mark.asyncio
async def test_create_or_update_bank_updates_cache():
    chat_id = 123
    banker_id = 456

    with patch('profile_bank.get_bank_info', new_callable=AsyncMock) as mock_get_bank_info, \
         patch('profile_bank.get_db'), \
         patch('profile_bank.fire_and_forget'):

        mock_get_bank_info.return_value = {'name': 'Old Name'}

        await create_or_update_bank(chat_id, banker_id, {'name': 'New Name'})

        assert (chat_id, 'new name') in _bank_name_to_id_cache
        assert _bank_name_to_id_cache[(chat_id, 'new name')] == banker_id
        assert (chat_id, 'old name') not in _bank_name_to_id_cache
