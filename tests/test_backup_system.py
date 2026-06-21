import pytest
import gzip
import json
import base64
import time
from unittest.mock import AsyncMock, MagicMock, patch
from backup_system import backup_database, restore_database

@pytest.mark.asyncio
async def test_backup_database():
    mock_db = MagicMock()
    mock_whitelist = {12345: "Super Chat"}
    
    # Mock data to be backed up
    mock_user_doc = MagicMock()
    mock_user_doc.id = "11111"
    mock_user_doc.to_dict.return_value = {"balance": 100}
    
    mock_bank_doc = MagicMock()
    mock_bank_doc.id = "22222"
    mock_bank_doc.to_dict.return_value = {"balance": 500}
    
    mock_clan_doc = MagicMock()
    mock_clan_doc.id = "33333"
    mock_clan_doc.to_dict.return_value = {"name": "Test Clan"}
    
    # Mock firestore calls
    async def mock_get_users():
        return [mock_user_doc]
    
    async def mock_get_banks():
        return [mock_bank_doc]
        
    async def mock_get_clans():
        return [mock_clan_doc]
        
    chat_doc_ref = MagicMock()
    chat_doc_ref.collection.side_effect = lambda coll_name: MagicMock(
        get=AsyncMock(return_value={
            "users": [mock_user_doc],
            "banks": [mock_bank_doc],
            "clans": [mock_clan_doc]
        }[coll_name])
    )
    
    mock_db.collection.return_value.document.return_value = chat_doc_ref
    
    # Mock old backups cleanup
    mock_old_backup_doc = MagicMock()
    mock_old_backup_doc.reference.delete = AsyncMock()
    mock_db.collection.return_value.where.return_value.get = AsyncMock(return_value=[mock_old_backup_doc])
    
    # Mock set for backups collection
    mock_db.collection.return_value.document.return_value.set = AsyncMock()
    
    with patch("backup_system.get_db", return_value=mock_db), \
         patch("backup_system.get_whitelist", AsyncMock(return_value=mock_whitelist)):
        
        success, backup_id = await backup_database()
        
        assert success is True
        assert backup_id.startswith("backup_")
        
        # Verify old backups search was performed
        mock_db.collection.assert_any_call("backups")
        
        # Verify the backup set call
        set_call_args = mock_db.collection("backups").document().set.call_args[0][0]
        assert "timestamp" in set_call_args
        assert "datetime" in set_call_args
        assert "payload" in set_call_args
        
        # Decompress payload and verify structure
        payload_bytes = base64.b64decode(set_call_args["payload"])
        decompressed = gzip.decompress(payload_bytes)
        backup_data = json.loads(decompressed.decode('utf-8'))
        
        assert "chats" in backup_data
        assert "12345" in backup_data["chats"]
        assert backup_data["chats"]["12345"]["users"]["11111"] == {"balance": 100}
        assert backup_data["chats"]["12345"]["banks"]["22222"] == {"balance": 500}
        assert backup_data["chats"]["12345"]["clans"]["33333"] == {"name": "Test Clan"}


@pytest.mark.asyncio
async def test_restore_database():
    mock_db = MagicMock()
    
    # Generate mock backup payload
    backup_data = {
        "chats": {
            "12345": {
                "users": {"11111": {"balance": 100}},
                "banks": {"22222": {"balance": 500, "name": "Main Bank"}},
                "clans": {"33333": {"name": "Test Clan"}}
            }
        }
    }
    json_bytes = json.dumps(backup_data).encode('utf-8')
    compressed = gzip.compress(json_bytes)
    payload_str = base64.b64encode(compressed).decode('utf-8')
    
    # Mock backup document
    mock_backup_doc = MagicMock()
    mock_backup_doc.exists = True
    mock_backup_doc.to_dict.return_value = {"payload": payload_str}
    
    # Mock current collection fetch for clearing
    mock_current_doc = MagicMock()
    mock_current_doc.reference = MagicMock()
    
    mock_coll = MagicMock()
    mock_coll.get = AsyncMock(return_value=[mock_current_doc])
    
    chat_doc_ref = MagicMock()
    chat_doc_ref.collection.return_value = mock_coll
    
    # Configure side effect for collection to return different setups for backups and chats
    def collection_side_effect(collection_name):
        coll_mock = MagicMock()
        if collection_name == "backups":
            doc_mock = MagicMock()
            doc_mock.get = AsyncMock(return_value=mock_backup_doc)
            coll_mock.document.return_value = doc_mock
        elif collection_name == "chats":
            coll_mock.document.return_value = chat_doc_ref
        return coll_mock
        
    mock_db.collection.side_effect = collection_side_effect
    
    # Mock batch
    mock_batch = MagicMock()
    mock_batch.commit = AsyncMock()
    mock_db.batch.return_value = mock_batch
    
    with patch("backup_system.get_db", return_value=mock_db), \
         patch("backup_system.invalidate_user_cache") as mock_inv_user, \
         patch("backup_system.invalidate_bank_cache") as mock_inv_bank:
        
        success, error = await restore_database("backup_test")
        
        assert success is True
        assert error is None
        
        # Verify batch delete was called on current docs
        mock_batch.delete.assert_called()
        
        # Verify batch set was called to write backup docs
        mock_batch.set.assert_called()
        
        # Verify cache invalidations were called
        mock_inv_user.assert_called_with(12345, 11111) # user1 converted to int
        mock_inv_bank.assert_called_with(12345, 22222, "Main Bank") # bank1 and name
