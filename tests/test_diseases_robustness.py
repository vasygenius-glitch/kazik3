import sys
import types
import time
from unittest.mock import patch, MagicMock, AsyncMock
import unittest
from aiogram import types as aiogram_types

# Temporarily remove mocks to load the real modules, then restore sys.modules
original_modules = {}
mocked_modules = ['diseases', 'config', 'user_manager', 'whitelist_middleware']
for mod_name in mocked_modules:
    if mod_name in sys.modules:
        original_modules[mod_name] = sys.modules[mod_name]
        if not isinstance(sys.modules[mod_name], types.ModuleType):
            del sys.modules[mod_name]

# Import the real modules
import diseases as real_diseases
import whitelist_middleware as real_whitelist_middleware
import config as real_config
import user_manager as real_user_manager

# Restore the original sys.modules so other tests are not broken
for mod_name, original_val in original_modules.items():
    sys.modules[mod_name] = original_val

class TestDiseasesRobustness(unittest.IsolatedAsyncioTestCase):

    async def test_get_active_diseases_valid_dict(self):
        current_time = time.time()
        
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('user_manager.update_user_field', new_callable=AsyncMock) as mock_update_field, \
                 patch('diseases.is_top_1_hooker', new_callable=AsyncMock) as mock_is_hooker:
                
                mock_is_hooker.return_value = False
                # Test case: user has active hiv (1000s left) and expired syphilis (-1000s left)
                mock_get_user_data.return_value = {
                    'diseases': {
                        'hiv': current_time + 1000,
                        'syphilis': current_time - 1000
                    }
                }
                
                active = await real_diseases.get_active_diseases(123, 456)
                self.assertEqual(active, ['hiv'])
                
                # The expired disease 'syphilis' should be deleted, and db updated
                mock_update_field.assert_called_once_with(123, 456, 'diseases', {'hiv': current_time + 1000})

    async def test_get_active_diseases_list(self):
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('user_manager.update_user_field', new_callable=AsyncMock) as mock_update_field, \
                 patch('diseases.is_top_1_hooker', new_callable=AsyncMock) as mock_is_hooker:
                
                mock_is_hooker.return_value = False
                # Test case: diseases field is a list [] (after wipe_user_data)
                mock_get_user_data.return_value = {
                    'diseases': []
                }
                
                active = await real_diseases.get_active_diseases(123, 456)
                self.assertEqual(active, [])
                mock_update_field.assert_not_called()

    async def test_get_active_diseases_none(self):
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('user_manager.update_user_field', new_callable=AsyncMock) as mock_update_field, \
                 patch('diseases.is_top_1_hooker', new_callable=AsyncMock) as mock_is_hooker:
                
                mock_is_hooker.return_value = False
                # Test case: diseases field is None
                mock_get_user_data.return_value = {
                    'diseases': None
                }
                
                active = await real_diseases.get_active_diseases(123, 456)
                self.assertEqual(active, [])
                mock_update_field.assert_not_called()

    async def test_get_active_diseases_missing(self):
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('user_manager.update_user_field', new_callable=AsyncMock) as mock_update_field, \
                 patch('diseases.is_top_1_hooker', new_callable=AsyncMock) as mock_is_hooker:
                
                mock_is_hooker.return_value = False
                # Test case: diseases field is missing completely
                mock_get_user_data.return_value = {}
                
                active = await real_diseases.get_active_diseases(123, 456)
                self.assertEqual(active, [])
                mock_update_field.assert_not_called()

    async def test_get_active_diseases_hooker_immunity(self):
        current_time = time.time()
        
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('user_manager.update_user_field', new_callable=AsyncMock) as mock_update_field, \
                 patch('diseases.is_top_1_hooker', new_callable=AsyncMock) as mock_is_hooker:
                
                mock_is_hooker.return_value = True
                # Even if user has active diseases, top-1 hooker immunity should result in [] active diseases
                mock_get_user_data.return_value = {
                    'diseases': {'hiv': current_time + 1000}
                }
                
                active = await real_diseases.get_active_diseases(123, 456)
                self.assertEqual(active, [])
                mock_update_field.assert_not_called()

    async def test_infect_user_from_corrupted_diseases(self):
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('user_manager.update_user_field', new_callable=AsyncMock) as mock_update_field, \
                 patch('config.CREATOR_ID', 999):
                
                # Test case: user is infected, but currently has 'diseases' as [] or None in DB
                for bad_val in ([], None):
                    mock_update_field.reset_mock()
                    mock_get_user_data.return_value = {'diseases': bad_val}
                    
                    infected = await real_diseases.infect_user(123, 456)
                    self.assertTrue(len(infected) >= 1)
                    
                    # Verify update_user_field was called and updated diseases with a dictionary
                    self.assertTrue(mock_update_field.called)
                    args = mock_update_field.call_args[0]
                    self.assertEqual(args[0], 123)
                    self.assertEqual(args[1], 456)
                    self.assertEqual(args[2], 'diseases')
                    self.assertIsInstance(args[3], dict)
                    self.assertTrue(all(isinstance(val, float) for val in args[3].values()))

    async def test_infect_full_house_from_corrupted_diseases(self):
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('user_manager.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('user_manager.update_user_field', new_callable=AsyncMock) as mock_update_field, \
                 patch('config.CREATOR_ID', 999):
                
                for bad_val in ([], None):
                    mock_update_field.reset_mock()
                    mock_get_user_data.return_value = {'diseases': bad_val}
                    
                    infected = await real_diseases.infect_full_house(123, 456)
                    self.assertEqual(len(infected), len(real_diseases.DISEASES))
                    
                    # Verify update_user_field was called with a dict containing all diseases
                    self.assertTrue(mock_update_field.called)
                    args = mock_update_field.call_args[0]
                    self.assertIsInstance(args[3], dict)
                    self.assertEqual(len(args[3]), len(real_diseases.DISEASES))

    async def test_middleware_diseases_robustness(self):
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('whitelist_middleware.get_whitelist', new_callable=AsyncMock) as mock_whitelist, \
                 patch('whitelist_middleware.get_spy_chats', new_callable=AsyncMock) as mock_spy_chats, \
                 patch('whitelist_middleware.get_locked_chats', new_callable=AsyncMock) as mock_locked_chats, \
                 patch('whitelist_middleware.get_user_data', new_callable=AsyncMock) as mock_get_user_data, \
                 patch('whitelist_middleware.get_active_diseases', new_callable=AsyncMock) as mock_active_diseases:
                
                # Whitelist contains the chat
                mock_whitelist.return_value = [123]
                mock_spy_chats.return_value = []
                mock_locked_chats.return_value = []
                
                # Setup middleware
                mw = real_whitelist_middleware.WhitelistMiddleware()
                
                # Handler mock
                handler = AsyncMock()
                
                # Event mock (Message)
                event = MagicMock(spec=aiogram_types.Message)
                event.chat = MagicMock()
                event.chat.type = "group"
                event.chat.id = 123
                event.from_user = MagicMock()
                event.from_user.id = 456
                event.from_user.full_name = "Ghost"
                event.text = "/balance"
                event.caption = None
                event.reply_to_message = None
                event.answer = AsyncMock()
                
                data = {'bot': MagicMock()}
                
                # Scenario 1: diseases is None
                mock_get_user_data.return_value = {'diseases': None}
                handler.reset_mock()
                await mw(handler, event, data)
                handler.assert_called_once_with(event, data)
                
                # Scenario 2: diseases is a list []
                mock_get_user_data.return_value = {'diseases': []}
                handler.reset_mock()
                await mw(handler, event, data)
                handler.assert_called_once_with(event, data)

                # Scenario 3: User has AIDS, call non-whitelisted command
                mock_get_user_data.return_value = {'diseases': {'aids': time.time() + 1000}}
                mock_active_diseases.return_value = ['aids']
                handler.reset_mock()
                await mw(handler, event, data)
                # AIDS block should trigger: handler must NOT be called, but alert sent
                handler.assert_not_called()
                self.assertTrue(event.answer.called)
                
                # Scenario 4: User has AIDS, call /зппп
                event.text = "/зппп"
                handler.reset_mock()
                event.answer.reset_mock()
                await mw(handler, event, data)
                # Should bypass AIDS block, so handler is called
                handler.assert_called_once_with(event, data)
                event.answer.assert_not_called()

    async def test_middleware_none_from_user(self):
        with patch.dict(sys.modules, {
            'diseases': real_diseases,
            'config': real_config,
            'user_manager': real_user_manager,
            'whitelist_middleware': real_whitelist_middleware
        }):
            with patch('whitelist_middleware.get_whitelist', new_callable=AsyncMock) as mock_whitelist, \
                 patch('whitelist_middleware.get_spy_chats', new_callable=AsyncMock) as mock_spy_chats, \
                 patch('whitelist_middleware.get_locked_chats', new_callable=AsyncMock) as mock_locked_chats:
                
                # Whitelist contains the chat
                mock_whitelist.return_value = [123]
                mock_spy_chats.return_value = []
                mock_locked_chats.return_value = []
                
                # Setup middleware
                mw = real_whitelist_middleware.WhitelistMiddleware()
                
                # Handler mock
                handler = AsyncMock()
                
                # Event mock (Message) with from_user = None
                event = MagicMock(spec=aiogram_types.Message)
                event.chat = MagicMock()
                event.chat.type = "group"
                event.chat.id = 123
                event.from_user = None
                event.text = "/balance"
                event.caption = None
                event.reply_to_message = None
                event.answer = AsyncMock()
                
                data = {'bot': MagicMock()}
                
                await mw(handler, event, data)
                handler.assert_called_once_with(event, data)

if __name__ == '__main__':
    unittest.main()
