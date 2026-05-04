import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# Mock dependencies that are not available in the environment
mock_db = MagicMock()
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = MagicMock()
sys.modules['db'] = mock_db

import economy_utils

class TestEconomyUtils(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        economy_utils._tax_cache = None
        economy_utils._tax_cache_time = 0
        self.db_instance = MagicMock()
        mock_db.get_db.return_value = self.db_instance

        self.mock_collection = MagicMock()
        self.mock_document = MagicMock()
        self.mock_doc_res = MagicMock()

        self.db_instance.collection.return_value = self.mock_collection
        self.mock_collection.document.return_value = self.mock_document
        self.mock_document.get = AsyncMock(return_value=self.mock_doc_res)

    async def test_get_global_tax_exists(self):
        # Case: Document exists and has 'tax' key
        self.mock_doc_res.exists = True
        self.mock_doc_res.to_dict.return_value = {'tax': 20}

        tax = await economy_utils.get_global_tax()

        self.assertEqual(tax, 20)
        self.db_instance.collection.assert_called_with('bot_settings')
        self.mock_collection.document.assert_called_with('economy')

    async def test_get_global_tax_exists_no_key(self):
        # Case: Document exists but 'tax' key is missing
        self.mock_doc_res.exists = True
        self.mock_doc_res.to_dict.return_value = {}

        tax = await economy_utils.get_global_tax()

        self.assertEqual(tax, 10) # Default value

    async def test_get_global_tax_not_exists(self):
        # Case: Document does not exist
        self.mock_doc_res.exists = False

        tax = await economy_utils.get_global_tax()

        self.assertEqual(tax, 10) # Default value

if __name__ == '__main__':
    unittest.main()
