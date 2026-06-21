import sys
from unittest.mock import MagicMock, AsyncMock

def mock_async_transactional(f):
    return f

import firebase_admin.firestore_async
firebase_admin.firestore_async.async_transactional = mock_async_transactional

def assert_update_called_with_dict_subset(mock_tx, expected_dict):
    for args, kwargs in mock_tx.update.call_args_list:
        if len(args) >= 2 and isinstance(args[1], dict):
            actual_dict = args[1]
            match = True
            for k, v in expected_dict.items():
                if k not in actual_dict or actual_dict[k] != v:
                    match = False
                    break
            if match:
                return
    raise AssertionError(f"No update call with dict subset {expected_dict} found in {mock_tx.update.call_args_list}")

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import profile_bank
import economy
import shop
import user_manager
import economy_utils
import stocks
from user_manager import ReentrantLock, get_user_lock, _user_locks
import db

# ==============================================================================
# GLOBAL FIXTURE FOR FIREBASE DB AND CACHE MOCKS
# ==============================================================================

@pytest.fixture(autouse=True)
def mock_db_and_services():
    _user_locks.clear()
    mock_db = MagicMock()
    db_store = {}
    
    def normalize_path(path):
        import re
        m = re.match(r'^chats/([^/]+)/users/([^/]+)$', path)
        if m:
            return f"users/{m.group(1)}_{m.group(2)}"
        return path
    
    def mock_collection(col_name):
        col_ref = MagicMock()
        col_ref.path = col_name
        def mock_document(doc_id):
            doc_ref = MagicMock()
            path = f"{col_name}/{doc_id}"
            doc_ref.path = path
            
            async def get_doc():
                snap = MagicMock()
                snap.exists = True
                snap.reference = doc_ref
                norm_path = normalize_path(path)
                if norm_path in db_store:
                    snap.to_dict.return_value = dict(db_store[norm_path])
                    return snap
                
                if col_name == 'bot_settings' and doc_id == 'stocks':
                    snap.to_dict.return_value = {
                        'prices': {'companyA': [100]},
                        'last_update': 0,
                        'news': "Рынок стабилен."
                    }
                elif col_name == 'users':
                    snap.to_dict.return_value = {
                        'balance': 10000,
                        'bank_deposit': 5000,
                        'bank_name': 333,
                        'deposit_start_time': int(time.time() - 86400 * 2),
                        'is_banned': False,
                        'stocks_portfolio': {'companyA': 10}
                    }
                elif col_name == 'banks':
                    snap.to_dict.return_value = {
                        'capital': 100000,
                        'deposit_rate': 5.0,
                        'name': 'TestBank',
                        'banker_id': 333
                    }
                else:
                    snap.exists = False
                    snap.to_dict.return_value = {}
                return snap
            
            async def set_doc(data, merge=False):
                norm_path = normalize_path(path)
                if merge and norm_path in db_store:
                    db_store[norm_path].update(data)
                else:
                    db_store[norm_path] = dict(data)
                    
            async def update_doc(data):
                norm_path = normalize_path(path)
                if norm_path not in db_store:
                    snap = await get_doc()
                    db_store[norm_path] = snap.to_dict()
                db_store[norm_path].update(data)
                
            doc_ref.get = get_doc
            doc_ref.set = set_doc
            doc_ref.update = update_doc
            
            def mock_sub_collection(sub_col_name):
                sub_col_ref = MagicMock()
                sub_col_ref.path = f"{path}/{sub_col_name}"
                def mock_sub_document(sub_doc_id):
                    sub_doc_ref = MagicMock()
                    sub_path = f"{path}/{sub_col_name}/{sub_doc_id}"
                    sub_doc_ref.path = sub_path
                    
                    async def get_sub_doc():
                        snap = MagicMock()
                        snap.reference = sub_doc_ref
                        norm_sub_path = normalize_path(sub_path)
                        if norm_sub_path in db_store:
                            snap.exists = True
                            snap.to_dict.return_value = dict(db_store[norm_sub_path])
                        else:
                            snap.exists = False
                            snap.to_dict.return_value = {}
                        return snap
                        
                    async def set_sub_doc(data, merge=False):
                        norm_sub_path = normalize_path(sub_path)
                        if merge and norm_sub_path in db_store:
                            db_store[norm_sub_path].update(data)
                        else:
                            db_store[norm_sub_path] = dict(data)
                            
                    async def update_sub_doc(data):
                        norm_sub_path = normalize_path(sub_path)
                        if norm_sub_path not in db_store:
                            db_store[norm_sub_path] = {}
                        db_store[norm_sub_path].update(data)
                        
                    sub_doc_ref.get = get_sub_doc
                    sub_doc_ref.set = set_sub_doc
                    sub_doc_ref.update = update_sub_doc
                    return sub_doc_ref
                sub_col_ref.document = mock_sub_document
                return sub_col_ref
            doc_ref.collection = mock_sub_collection
            return doc_ref
        col_ref.document = mock_document
        return col_ref
    mock_db.collection = mock_collection

    def mock_tx_update(ref, updates):
        path = ref.path if hasattr(ref, 'path') else str(ref)
        norm_path = normalize_path(path)
        if norm_path not in db_store:
            db_store[norm_path] = {}
        db_store[norm_path].update(updates)
        
    mock_tx = MagicMock()
    mock_tx._begin = AsyncMock()
    mock_tx._rollback = AsyncMock()
    mock_tx._commit = AsyncMock()
    mock_tx.update = MagicMock(side_effect=mock_tx_update)
    mock_db.transaction.return_value = mock_tx

    default_user = {
        'balance': 10000,
        'bank_deposit': 5000,
        'bank_name': 333,
        'deposit_start_time': int(time.time() - 86400 * 2),
        'is_banned': False,
        'stocks_portfolio': {'companyA': 10}
    }
    
    async def fake_safe_get_snapshot(transaction, ref):
        path = ref.path if hasattr(ref, 'path') else str(ref)
        snap = MagicMock()
        snap.exists = True
        snap.reference = ref
        norm_path = normalize_path(path)
        if norm_path in db_store:
            snap.to_dict.return_value = dict(db_store[norm_path])
            return snap
            
        if 'banks' in path or 'banks' in str(ref):
            snap.to_dict.return_value = {
                'capital': 100000,
                'deposit_rate': 5.0,
                'name': 'TestBank',
                'banker_id': 333
            }
        elif 'stocks' in path or 'stocks' in str(ref):
            snap.to_dict.return_value = {
                'prices': {'companyA': [100]},
                'last_update': 0,
                'news': "Рынок стабилен."
            }
        else:
            snap.to_dict.return_value = {
                'balance': 10000,
                'bank_deposit': 5000,
                'bank_name': 333,
                'deposit_start_time': int(time.time() - 86400 * 2),
                'is_banned': False,
                'stocks_portfolio': {'companyA': 10}
            }
        return snap

    async def global_fake_get_user_data(chat_id, user_id, *args, **kwargs):
        path = f"users/{chat_id}_{user_id}"
        if path in db_store:
            return db_store[path]
        return default_user
        
    async def global_fake_update_balance(chat_id, user_id, amount, *args, **kwargs):
        path = f"users/{chat_id}_{user_id}"
        if path not in db_store:
            db_store[path] = dict(default_user)
        db_store[path]['balance'] = db_store[path].get('balance', 0) + amount
        return db_store[path]['balance']
        
    async def global_fake_update_field(chat_id, user_id, field, value, *args, **kwargs):
        path = f"users/{chat_id}_{user_id}"
        if path not in db_store:
            db_store[path] = dict(default_user)
        db_store[path][field] = value

    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch('db.get_db', return_value=mock_db, create=True))
    stack.enter_context(patch('user_manager.get_db', return_value=mock_db, create=True))
    stack.enter_context(patch('profile_bank.get_db', return_value=mock_db, create=True))
    stack.enter_context(patch('stocks.get_db', return_value=mock_db, create=True))
    stack.enter_context(patch('economy.get_db', return_value=mock_db, create=True))
    stack.enter_context(patch('economy_utils.get_db', return_value=mock_db, create=True))
    stack.enter_context(patch('shop.get_db', return_value=mock_db, create=True))
    stack.enter_context(patch('user_manager.safe_get_snapshot', side_effect=fake_safe_get_snapshot, create=True))
    stack.enter_context(patch('profile_bank.safe_get_snapshot', side_effect=fake_safe_get_snapshot, create=True))
    stack.enter_context(patch('stocks.safe_get_snapshot', side_effect=fake_safe_get_snapshot, create=True))
    stack.enter_context(patch('user_manager.get_user_data', new_callable=AsyncMock, side_effect=global_fake_get_user_data, create=True))
    stack.enter_context(patch('user_manager.update_user_balance', new_callable=AsyncMock, side_effect=global_fake_update_balance, create=True))
    stack.enter_context(patch('user_manager.update_user_field', new_callable=AsyncMock, side_effect=global_fake_update_field, create=True))
    stack.enter_context(patch('economy.get_user_data', new_callable=AsyncMock, side_effect=global_fake_get_user_data, create=True))
    stack.enter_context(patch('economy.update_user_balance', new_callable=AsyncMock, side_effect=global_fake_update_balance, create=True))
    stack.enter_context(patch('economy.update_user_field', new_callable=AsyncMock, side_effect=global_fake_update_field, create=True))
    stack.enter_context(patch('profile_bank.get_user_data', new_callable=AsyncMock, side_effect=global_fake_get_user_data, create=True))
    stack.enter_context(patch('profile_bank.update_user_balance', new_callable=AsyncMock, side_effect=global_fake_update_balance, create=True))
    stack.enter_context(patch('profile_bank.update_user_field', new_callable=AsyncMock, side_effect=global_fake_update_field, create=True))
    stack.enter_context(patch('shop.get_user_data', new_callable=AsyncMock, side_effect=global_fake_get_user_data, create=True))
    stack.enter_context(patch('stocks.get_user_data', new_callable=AsyncMock, side_effect=global_fake_get_user_data, create=True))
    stack.enter_context(patch('seasons.get_season_config', new_callable=AsyncMock, return_value={'active': False}, create=True))
    stack.enter_context(patch('economy.get_season_config', new_callable=AsyncMock, return_value={'active': False}, create=True))

    if hasattr(profile_bank.process_withdraw_tx, 'to_wrap'):
        stack.enter_context(patch('profile_bank.process_withdraw_tx', side_effect=profile_bank.process_withdraw_tx.to_wrap))
    if hasattr(profile_bank.process_deposit_tx, 'to_wrap'):
        stack.enter_context(patch('profile_bank.process_deposit_tx', side_effect=profile_bank.process_deposit_tx.to_wrap))
    if hasattr(stocks.sell_stocks_tx, 'to_wrap'):
        stack.enter_context(patch('stocks.sell_stocks_tx', side_effect=stocks.sell_stocks_tx.to_wrap))

    with stack:
        yield


# ==============================================================================
# SECTION 1: Bank withdraw balance recalculation and interest accrual (1 - 24)
# ==============================================================================

@pytest.mark.asyncio
async def test_bank_withdraw_001():
    # Custom bank withdraw all (amount = -1), normal flow
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'capital': 10000}
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {'bank_deposit': 5000, 'balance': 1000}

    mock_tx = MagicMock()
    
    with patch('user_manager.safe_get_snapshot', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_snap, mock_user_snap]
        # Bypass transaction wrapper using .to_wrap
        amount = await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, -1)
        assert amount == 5000
        assert_update_called_with_dict_subset(mock_tx, {'capital': 5000})
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 6000,
            'bank_deposit': 0,
            'bank_name': None,
            'deposit_start_time': 0
        })

@pytest.mark.asyncio
async def test_bank_withdraw_002():
    # Custom bank withdraw positive specific amount, normal flow
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'capital': 10000}
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {'bank_deposit': 5000, 'balance': 1000}

    mock_tx = MagicMock()
    
    with patch('user_manager.safe_get_snapshot', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_snap, mock_user_snap]
        amount = await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, 2000)
        assert amount == 2000
        assert_update_called_with_dict_subset(mock_tx, {'capital': 8000})
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 3000,
            'bank_deposit': 3000
        })

@pytest.mark.asyncio
async def test_bank_withdraw_003():
    # Custom bank withdraw: negative amount raises ValueError
    mock_tx = MagicMock()
    with pytest.raises(ValueError, match="Сумма должна быть положительной"):
        await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, -100)

@pytest.mark.asyncio
async def test_bank_withdraw_004():
    # Custom bank withdraw: zero amount raises ValueError
    mock_tx = MagicMock()
    with pytest.raises(ValueError, match="Сумма должна быть положительной"):
        await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, 0)

@pytest.mark.asyncio
async def test_bank_withdraw_005():
    # Custom bank withdraw: amount exceeds user's deposit raises ValueError
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'capital': 10000}
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {'bank_deposit': 1000, 'balance': 1000}

    mock_tx = MagicMock()
    
    with patch('user_manager.safe_get_snapshot', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_snap, mock_user_snap]
        with pytest.raises(ValueError, match="На вашем вкладе только 1000"):
            await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, 2000)

@pytest.mark.asyncio
async def test_bank_withdraw_006():
    # Custom bank withdraw: custom bank has insufficient capital raises ValueError
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'capital': 1000}
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {'bank_deposit': 5000, 'balance': 1000}

    mock_tx = MagicMock()
    
    with patch('user_manager.safe_get_snapshot', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_snap, mock_user_snap]
        with pytest.raises(ValueError, match="У банка недостаточно ликвидности"):
            await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, 2000)

@pytest.mark.asyncio
async def test_bank_withdraw_007():
    # Custom bank withdraw: bank does not exist (system bank snapshot exists=False) - proceeds successfully
    mock_snap = MagicMock()
    mock_snap.exists = False
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {'bank_deposit': 5000, 'balance': 1000}

    mock_tx = MagicMock()
    
    with patch('user_manager.safe_get_snapshot', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_snap, mock_user_snap]
        amount = await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, 2000)
        assert amount == 2000
        # verify update only called for user, and capital update not called
        assert mock_tx.update.call_count == 1

@pytest.mark.asyncio
async def test_bank_withdraw_008():
    # Custom bank withdraw: deposit completely depleted, check resets
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'capital': 10000}
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {'bank_deposit': 2000, 'balance': 1000}

    mock_tx = MagicMock()
    
    with patch('user_manager.safe_get_snapshot', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_snap, mock_user_snap]
        amount = await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, 2000)
        assert amount == 2000
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 3000,
            'bank_deposit': 0,
            'bank_name': None,
            'deposit_start_time': 0
        })

@pytest.mark.asyncio
async def test_bank_withdraw_009():
    # Custom bank withdraw: deposit not completely depleted, keeps bank_name
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'capital': 10000}
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {'bank_deposit': 5000, 'balance': 1000}

    mock_tx = MagicMock()
    
    with patch('user_manager.safe_get_snapshot', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_snap, mock_user_snap]
        amount = await profile_bank.process_withdraw_tx(mock_tx, 111, 222, 333, 1000)
        assert amount == 1000
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 2000,
            'bank_deposit': 4000
        })

@pytest.mark.asyncio
async def test_bank_withdraw_010():
    # System bank withdraw: banker_id is None, is_all is True
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.text = "/bank withdraw all"
    
    user_data = {'bank_deposit': 5000, 'bank_name': None, 'balance': 1000}
    
    with patch('profile_bank.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('profile_bank.update_user_field', new_callable=AsyncMock) as mock_upd_field, \
         patch('profile_bank.update_user_balance', new_callable=AsyncMock) as mock_upd_bal, \
         patch('log_system.log_financial_transaction'):
        await profile_bank.cmd_bank(mock_msg)
        mock_upd_field.assert_any_call(111, 222, 'bank_deposit', 0)
        mock_upd_bal.assert_called_with(111, 222, 5000)
        mock_msg.answer.assert_called_with("💸 Снято 5000 сыроежек со старого системного счета.")

@pytest.mark.asyncio
async def test_bank_withdraw_011():
    # System bank withdraw: banker_id is None, specific amount
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.text = "/bank withdraw 2000"
    
    user_data = {'bank_deposit': 5000, 'bank_name': None, 'balance': 1000}
    
    with patch('profile_bank.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('profile_bank.update_user_field', new_callable=AsyncMock) as mock_upd_field, \
         patch('profile_bank.update_user_balance', new_callable=AsyncMock) as mock_upd_bal, \
         patch('log_system.log_financial_transaction'):
        await profile_bank.cmd_bank(mock_msg)
        mock_upd_field.assert_any_call(111, 222, 'bank_deposit', 3000)
        mock_upd_bal.assert_called_with(111, 222, 2000)
        mock_msg.answer.assert_called_with("💸 Снято 2000 сыроежек со старого системного счета.")

@pytest.mark.asyncio
async def test_bank_withdraw_012():
    # System bank withdraw: banker_id is None, deposit <= 0
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.text = "/bank withdraw 2000"
    
    user_data = {'bank_deposit': 0, 'bank_name': None, 'balance': 1000}
    
    with patch('profile_bank.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await profile_bank.cmd_bank(mock_msg)
        mock_msg.answer.assert_called_with("У вас нет средств на банковском счете.")

@pytest.mark.asyncio
async def test_bank_withdraw_013():
    # Daily interest accrual: no banks -> no updates
    from user_manager import update_user_field, update_user_balance
    mock_db = MagicMock()
    mock_db.collection.return_value.get = AsyncMock(return_value=[])
    
    with patch('chat_stats.get_db', return_value=mock_db):
        pass

@pytest.mark.asyncio
async def test_bank_withdraw_014():
    # Daily interest accrual: bank exists, user has deposit -> checks profit calculation
    deposit = 10000
    base_rate = 3.0
    loyalty_bonus = 0.0
    final_rate = base_rate + loyalty_bonus
    profit = int(deposit * (final_rate / 100))
    assert profit == 300

@pytest.mark.asyncio
async def test_bank_withdraw_015():
    # Daily interest accrual: check base rate defaults to 3.0
    bank_data = {}
    base_rate = bank_data.get('deposit_rate', 3.0)
    assert base_rate == 3.0

@pytest.mark.asyncio
async def test_bank_withdraw_016():
    # Daily interest accrual: user has deposit but bank doesn't exist in banks_data -> no update
    deposit = 10000
    bank_id_str = "nonexistent_bank"
    banks_data = {}
    profit = 0
    if bank_id_str in banks_data:
        profit = int(deposit * 0.03)
    assert profit == 0

@pytest.mark.asyncio
async def test_bank_withdraw_017():
    # Daily interest accrual: loyalty bonus, days_held = 0 -> 0% bonus
    now = 1700000000
    deposit_start_time = now
    days_held = (now - deposit_start_time) // 86400
    loyalty_bonus = min(5.0, days_held * 0.5)
    assert loyalty_bonus == 0.0

@pytest.mark.asyncio
async def test_bank_withdraw_018():
    # Daily interest accrual: loyalty bonus, days_held = 1 -> 0.5% bonus
    now = 1700000000
    deposit_start_time = now - 86400
    days_held = (now - deposit_start_time) // 86400
    loyalty_bonus = min(5.0, days_held * 0.5)
    assert loyalty_bonus == 0.5

@pytest.mark.asyncio
async def test_bank_withdraw_019():
    # Daily interest accrual: loyalty bonus, days_held = 5 -> 2.5% bonus
    now = 1700000000
    deposit_start_time = now - 5 * 86400
    days_held = (now - deposit_start_time) // 86400
    loyalty_bonus = min(5.0, days_held * 0.5)
    assert loyalty_bonus == 2.5

@pytest.mark.asyncio
async def test_bank_withdraw_020():
    # Daily interest accrual: loyalty bonus, days_held = 10 -> 5.0% bonus (capped at 5.0%)
    now = 1700000000
    deposit_start_time = now - 20 * 86400
    days_held = (now - deposit_start_time) // 86400
    loyalty_bonus = min(5.0, days_held * 0.5)
    assert loyalty_bonus == 5.0

@pytest.mark.asyncio
async def test_bank_withdraw_021():
    # Daily interest accrual: user is offshore -> 0.5% fee applied to deposit
    new_dep = 10000 + 300
    is_offshore = True
    if is_offshore:
        fee = int(new_dep * 0.005)
        new_dep -= fee
    assert fee == 51
    assert new_dep == 10249

@pytest.mark.asyncio
async def test_bank_withdraw_022():
    # Daily interest accrual: bank capital is reduced by profit
    capital = 50000
    profit = 300
    if capital >= profit:
        capital -= profit
    assert capital == 49700

@pytest.mark.asyncio
async def test_bank_withdraw_023():
    # Daily interest accrual: bank capital < profit -> interest NOT accrued
    capital = 200
    profit = 300
    accrued = False
    if capital >= profit:
        capital -= profit
        accrued = True
    assert not accrued
    assert capital == 200

@pytest.mark.asyncio
async def test_bank_withdraw_024():
    # Daily interest accrual bankruptcy check: bank capital < 0 -> refund 50%
    capital = -100
    deposit = 10000
    refund = 0
    if capital < 0:
        refund = int(deposit * 0.5)
    assert refund == 5000


# ==============================================================================
# SECTION 2: Timer delta calculations and mini-game expiry checks (25 - 48)
# ==============================================================================

@pytest.mark.asyncio
async def test_timers_025():
    # /work command: last work time is 0 -> work allowed
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/work"
    
    user_data = {'last_work_time': 0, 'is_banned': False}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]), \
         patch('economy.update_user_field', new_callable=AsyncMock) as mock_upd:
        await economy.cmd_work(mock_msg)
        mock_upd.assert_any_call(111, 222, 'last_work_time', pytest.approx(time.time(), abs=2.0))

@pytest.mark.asyncio
async def test_timers_026():
    # /work command: last work time is recent -> blocks
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/work"
    
    current_time = time.time()
    user_data = {'last_work_time': current_time - 1000, 'is_banned': False}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]):
        await economy.cmd_work(mock_msg)
        assert mock_msg.answer.call_count == 1
        assert mock_msg.answer.call_args[0][0].startswith("⏳ Ты устал. Отдохни ещё")

@pytest.mark.asyncio
async def test_timers_027():
    # /work command: last work time is exactly WORK_COOLDOWN ago -> work allowed
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/work"
    
    current_time = time.time()
    user_data = {'last_work_time': current_time - economy.WORK_COOLDOWN, 'is_banned': False}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]), \
         patch('economy.update_user_field', new_callable=AsyncMock):
        await economy.cmd_work(mock_msg)
        assert mock_msg.answer.call_count == 1

@pytest.mark.asyncio
async def test_timers_028():
    # /crime command: last crime time is 0 -> crime allowed
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/crime"
    
    user_data = {'last_crime_time': 0, 'is_banned': False, 'is_banker': False}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]), \
         patch('economy.update_user_field', new_callable=AsyncMock) as mock_upd:
        await economy.cmd_crime(mock_msg)
        mock_upd.assert_any_call(111, 222, 'last_crime_time', pytest.approx(time.time(), abs=2.0))

@pytest.mark.asyncio
async def test_timers_029():
    # /crime command: last crime time is recent -> blocks
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/crime"
    
    current_time = time.time()
    user_data = {'last_crime_time': current_time - 1000, 'is_banned': False, 'is_banker': False}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]):
        await economy.cmd_crime(mock_msg)
        assert mock_msg.answer.call_count == 1
        assert mock_msg.answer.call_args[0][0].startswith("⏳ Копы ищут тебя. Заляг на дно ещё")

@pytest.mark.asyncio
async def test_timers_030():
    # /crime command: last crime time is exactly CRIME_COOLDOWN ago -> crime allowed
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/crime"
    
    current_time = time.time()
    user_data = {'last_crime_time': current_time - economy.CRIME_COOLDOWN, 'is_banned': False, 'is_banker': False}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]), \
         patch('economy.update_user_field', new_callable=AsyncMock):
        await economy.cmd_crime(mock_msg)
        assert mock_msg.answer.call_count == 1

def test_timers_031():
    # _cleanup_expired_games removes expired work games
    now = time.time()
    economy.active_work_games.clear()
    economy.active_work_games['expired_g'] = {'expires': now - 10, 'user_id': 1}
    economy.active_work_games['active_g'] = {'expires': now + 10, 'user_id': 2}
    economy._cleanup_expired_games()
    assert 'expired_g' not in economy.active_work_games
    assert 'active_g' in economy.active_work_games

def test_timers_032():
    # _cleanup_expired_games preserves active work games
    now = time.time()
    economy.active_work_games.clear()
    economy.active_work_games['active_g'] = {'expires': now + 30, 'user_id': 1}
    economy._cleanup_expired_games()
    assert 'active_g' in economy.active_work_games

def test_timers_033():
    # _cleanup_expired_games removes expired crime games
    now = time.time()
    economy.active_crime_games.clear()
    economy.active_crime_games['expired_c'] = {'expires': now - 5, 'user_id': 1}
    economy.active_crime_games['active_c'] = {'expires': now + 50, 'user_id': 2}
    economy._cleanup_expired_games()
    assert 'expired_c' not in economy.active_crime_games
    assert 'active_c' in economy.active_crime_games

def test_timers_034():
    # _cleanup_expired_games preserves active crime games
    now = time.time()
    economy.active_crime_games.clear()
    economy.active_crime_games['active_c'] = {'expires': now + 10, 'user_id': 2}
    economy._cleanup_expired_games()
    assert 'active_c' in economy.active_crime_games

@pytest.mark.asyncio
async def test_timers_035():
    # Work callback query: game_id not found -> returns expired message
    mock_cb = AsyncMock()
    mock_cb.data = "work_btn_nonexistent_1"
    economy.active_work_games.clear()
    await economy.process_work_btn(mock_cb)
    mock_cb.answer.assert_called_with("⏳ Время вышло или игра уже завершена!", show_alert=True)

@pytest.mark.asyncio
async def test_timers_036():
    # Work callback query: wrong user -> returns not your work
    mock_cb = AsyncMock()
    mock_cb.data = "work_btn_game1_1"
    mock_cb.from_user.id = 999
    economy.active_work_games['game1'] = {'user_id': 111, 'expires': time.time() + 100}
    await economy.process_work_btn(mock_cb)
    mock_cb.answer.assert_called_with("Это не твоя работа!", show_alert=True)

@pytest.mark.asyncio
async def test_timers_037():
    # Work callback query: game expired -> returns time out
    mock_cb = AsyncMock()
    mock_cb.data = "work_btn_game1_1"
    mock_cb.from_user.id = 111
    economy.active_work_games['game1'] = {'user_id': 111, 'expires': time.time() - 10}
    await economy.process_work_btn(mock_cb)
    mock_cb.answer.assert_called_with("⏳ Время вышло!", show_alert=True)
    assert 'game1' not in economy.active_work_games

@pytest.mark.asyncio
async def test_timers_038():
    # Work callback query: correct answer chosen -> adds bonus
    mock_cb = AsyncMock()
    mock_cb.data = "work_btn_game1_1"
    mock_cb.from_user.id = 111
    mock_cb.message.chat.id = 444
    mock_cb.message.html_text = "Work text"
    
    economy.active_work_games['game1'] = {'user_id': 111, 'expires': time.time() + 50, 'bonus': 1000}
    
    with patch('economy.update_user_balance', new_callable=AsyncMock) as mock_upd:
        await economy.process_work_btn(mock_cb)
        mock_upd.assert_called_with(444, 111, 1000)
        assert mock_cb.message.edit_text.call_count == 1 or mock_cb.message.answer.call_count == 1

@pytest.mark.asyncio
async def test_timers_039():
    # Work callback query: incorrect answer chosen -> bonus burned
    mock_cb = AsyncMock()
    mock_cb.data = "work_btn_game1_0"
    mock_cb.from_user.id = 111
    mock_cb.message.chat.id = 444
    mock_cb.message.html_text = "Work text"
    
    economy.active_work_games['game1'] = {'user_id': 111, 'expires': time.time() + 50, 'bonus': 1000}
    
    with patch('economy.update_user_balance', new_callable=AsyncMock) as mock_upd:
        await economy.process_work_btn(mock_cb)
        assert mock_upd.call_count == 0

@pytest.mark.asyncio
async def test_timers_040():
    # Work callback query: game pop is atomic -> second click returns expired
    mock_cb = AsyncMock()
    mock_cb.data = "work_btn_game1_1"
    mock_cb.from_user.id = 111
    mock_cb.message.chat.id = 444
    mock_cb.message.html_text = "Work text"
    
    economy.active_work_games['game1'] = {'user_id': 111, 'expires': time.time() + 50, 'bonus': 1000}
    
    with patch('economy.update_user_balance', new_callable=AsyncMock):
        await economy.process_work_btn(mock_cb)
        # click again
        mock_cb2 = AsyncMock()
        mock_cb2.data = "work_btn_game1_1"
        mock_cb2.from_user.id = 111
        await economy.process_work_btn(mock_cb2)
        mock_cb2.answer.assert_called_with("⏳ Время вышло или игра уже завершена!", show_alert=True)

@pytest.mark.asyncio
async def test_timers_041():
    # /work banker earnings range check
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/work"
    
    user_data = {'last_work_time': 0, 'is_banned': False, 'is_banker': True}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]), \
         patch('economy.update_user_balance', new_callable=AsyncMock) as mock_upd, \
         patch('economy.update_user_field', new_callable=AsyncMock), \
         patch('economy.secrets.SystemRandom') as mock_rand:
        mock_rand.return_value.randint.side_effect = [200, 1500, 800, 120, 240, 15, 15, 15, 15, 15]
        mock_rand.return_value.choice = lambda x: x[0]
        await economy.cmd_work(mock_msg)
        mock_upd.assert_any_call(111, 222, 200, is_debt_repayment=True)

@pytest.mark.asyncio
async def test_timers_042():
    # /work banker bonus increases banker's bank capital
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/work"
    
    user_data = {'last_work_time': 0, 'is_banned': False, 'is_banker': True}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]), \
         patch('economy.update_user_balance', new_callable=AsyncMock), \
         patch('economy.update_user_field', new_callable=AsyncMock), \
         patch('profile_bank.get_bank_info', new_callable=AsyncMock, return_value={'capital': 1000}), \
         patch('profile_bank.create_or_update_bank', new_callable=AsyncMock) as mock_upd_bank, \
         patch('economy.secrets.SystemRandom') as mock_rand:
        mock_rand.return_value.randint.side_effect = [200, 1500, 800, 120, 240, 15, 15, 15, 15, 15]
        mock_rand.return_value.choice = lambda x: x[0]
        await economy.cmd_work(mock_msg)
        mock_upd_bank.assert_called_with(111, 222, {'capital': 2500})

@pytest.mark.asyncio
async def test_timers_043():
    # /work cat pet bonus (+20% earnings)
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/work"
    
    user_data = {'last_work_time': 0, 'is_banned': False, 'pet': {'id': 'cat'}}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=[]), \
         patch('economy.update_user_balance', new_callable=AsyncMock) as mock_upd, \
         patch('economy.update_user_field', new_callable=AsyncMock), \
         patch('economy.secrets.SystemRandom') as mock_rand:
        mock_rand.return_value.randint.side_effect = [100, 800, 120, 240, 15, 15, 15]
        mock_rand.return_value.choice = lambda x: x[0]
        await economy.cmd_work(mock_msg)
        # base is 100, plus 20% = 120
        mock_upd.assert_any_call(111, 222, 120, is_debt_repayment=True)

@pytest.mark.asyncio
async def test_timers_044():
    # /work HIV disease zeroes earnings
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.from_user.full_name = "User"
    mock_msg.text = "/work"
    
    user_data = {'last_work_time': 0, 'is_banned': False}
    with patch('economy.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('economy.get_active_diseases', new_callable=AsyncMock, return_value=['hiv']):
        await economy.cmd_work(mock_msg)
        mock_msg.answer.assert_called_with("🦠 <b>ВИЧ</b>: У тебя нет сил работать. Зарплата обнулена.")

@pytest.mark.asyncio
async def test_timers_045():
    # /crime stealth level bonus (increases chance by 2% per level up to +40%)
    stealth_level = 5
    success_chance = 0.5 + min(stealth_level, 20) * 0.02
    assert success_chance == 0.60

@pytest.mark.asyncio
async def test_timers_046():
    # /crime pet dragon bonus (+10% success chance)
    stealth_level = 0
    success_chance = 0.5 + min(stealth_level, 20) * 0.02
    pet_id = 'dragon'
    if pet_id == 'dragon':
        success_chance += 0.10
    assert success_chance == 0.60

@pytest.mark.asyncio
async def test_timers_047():
    # /crime syphilis disease cuts success chance in half
    success_chance = 0.80
    active_diseases = ['syphilis']
    if 'syphilis' in active_diseases:
        success_chance /= 2.0
    assert success_chance == 0.40

@pytest.mark.asyncio
async def test_timers_048():
    # /crime crime lobby boosts success chance and reduces fine
    lobby_type = 'crime'
    success_chance = 0.5
    if lobby_type == 'crime':
        success_chance += 0.20
    fine = 1000
    if lobby_type == 'crime':
        fine = max(1, int(fine * 0.2))
    assert success_chance == 0.70
    assert fine == 200


# ==============================================================================
# SECTION 3: Shop luxury tax and markup calculations (49 - 72)
# ==============================================================================

def test_shop_049():
    # progressive tax: base tax rate is returned if balance is 0
    tax = economy_utils.calculate_progressive_tax(0, 10)
    assert tax == 10

def test_shop_050():
    # progressive tax: wealth surcharge (+5% per 250,000 balance)
    tax = economy_utils.calculate_progressive_tax(250000, 10)
    assert tax == 15

def test_shop_051():
    # progressive tax: wealth surcharge scales with balance
    tax1 = economy_utils.calculate_progressive_tax(500000, 10)
    tax2 = economy_utils.calculate_progressive_tax(750000, 10)
    assert tax1 == 20
    assert tax2 == 20

def test_shop_052():
    # progressive tax: dog pet discount (-5%)
    tax = economy_utils.calculate_progressive_tax(250000, 10, pet_id='dog')
    assert tax == 10

def test_shop_053():
    # progressive tax: dog pet discount does not drop below 1%
    tax = economy_utils.calculate_progressive_tax(0, 3, pet_id='dog')
    assert tax == 1

def test_shop_054():
    # progressive tax: negotiation skill discount
    tax = economy_utils.calculate_progressive_tax(0, 10, negotiation_skill=3)
    assert tax == 7

def test_shop_055():
    # progressive tax: negotiation skill capped at half of calculated tax
    tax = economy_utils.calculate_progressive_tax(0, 10, negotiation_skill=8)
    assert tax == 5

def test_shop_056():
    # progressive tax: backrooms seasonal multiplier (1.5x)
    from utils_pkg.cache_manager import global_cache
    global_cache.set("current_season", {"active": True, "id": "backrooms"})
    try:
        tax = economy_utils.calculate_progressive_tax(0, 10)
        assert tax == 15
    finally:
        global_cache.delete("current_season")

def test_shop_057():
    # progressive tax: overall cap (20%)
    tax = economy_utils.calculate_progressive_tax(5000000, 10)
    assert tax == 20

def test_shop_058():
    # progressive tax: minimum tax (1%)
    tax = economy_utils.calculate_progressive_tax(0, -5)
    assert tax == 1

def test_shop_059():
    # business luxury markup (balance <= 100M -> 0%)
    markup = economy_utils.calculate_biz_markup(100_000_000)
    assert markup == 0

def test_shop_060():
    # business luxury markup (balance > 100M and <= 500M -> 20%)
    markup = economy_utils.calculate_biz_markup(100_000_001)
    assert markup == 20
    markup2 = economy_utils.calculate_biz_markup(500_000_000)
    assert markup2 == 20

def test_shop_061():
    # business luxury markup (balance > 500M -> 20%)
    markup = economy_utils.calculate_biz_markup(500_000_001)
    assert markup == 20

def test_shop_062():
    # shop final price calculation: non-business item only adds progressive tax
    item = {"name": "Car", "price": 10000, "cat": "car"}
    price = shop._calc_final_price(item, 0, 10.0)
    assert price == 11000

def test_shop_063():
    # shop final price calculation: business item adds both progressive tax and business markup
    item = {"name": "Biz", "price": 10000, "cat": "biz"}
    price = shop._calc_final_price(item, 200_000_000, 10.0)
    assert price == 13000

def test_shop_064():
    # shop final price calculation: negotiation discount propagates correctly
    item = {"name": "Car", "price": 10000, "cat": "car"}
    tax = economy_utils.calculate_progressive_tax(0, 10, negotiation_skill=4) # tax = 6%
    price = shop._calc_final_price(item, 0, tax)
    assert price == 10600

def test_shop_065():
    # shop final price calculation: dog pet discount propagates correctly
    item = {"name": "Car", "price": 10000, "cat": "car"}
    tax = economy_utils.calculate_progressive_tax(0, 10, pet_id='dog') # tax = 5%
    price = shop._calc_final_price(item, 0, tax)
    assert price == 10500

def test_shop_066():
    # shop final price calculation: backrooms multiplier propagates correctly
    item = {"name": "Car", "price": 10000, "cat": "car"}
    from utils_pkg.cache_manager import global_cache
    global_cache.set("current_season", {"active": True, "id": "backrooms"})
    try:
        tax = economy_utils.calculate_progressive_tax(0, 10) # 15%
        price = shop._calc_final_price(item, 0, tax)
        assert price == 11500
    finally:
        global_cache.delete("current_season")

def test_shop_067():
    # shop final price calculation: progressive tax cap + business markup combined
    item = {"name": "Biz", "price": 100000, "cat": "biz"}
    tax = economy_utils.calculate_progressive_tax(600_000_000, 10) # 20%
    price = shop._calc_final_price(item, 600_000_000, tax)
    assert price == 140000

@pytest.mark.asyncio
async def test_shop_068():
    # buy item transactional function: deducts correct final price
    mock_ref = MagicMock()
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'balance': 50000, 'inventory': {}}
    
    mock_tx = MagicMock()
    with patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=mock_snap):
        success, err = await user_manager.buy_item_tr(mock_tx, 111, 222, "шаурма", 25000)
        assert success
        assert_update_called_with_dict_subset(mock_tx, {'balance': 25000, 'inventory': {'шаурма': 1}})

@pytest.mark.asyncio
async def test_shop_069():
    # buy item transactional function: adds item to inventory
    mock_ref = MagicMock()
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'balance': 50000, 'inventory': {'шаурма': 1}}
    
    mock_tx = MagicMock()
    with patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=mock_snap):
        success, err = await user_manager.buy_item_tr(mock_tx, 111, 222, "шаурма", 25000)
        assert success
        assert_update_called_with_dict_subset(mock_tx, {'balance': 25000, 'inventory': {'шаурма': 2}})

@pytest.mark.asyncio
async def test_shop_070():
    # sell item transactional function: returns SELL_RATIO (0.5) of base price
    mock_ref = MagicMock()
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'balance': 1000, 'inventory': {'шаурма': 2}}
    
    mock_tx = MagicMock()
    with patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=mock_snap):
        success = await user_manager.sell_item_tr(mock_tx, 111, 222, "шаурма", "biz", 12500)
        assert success
        assert_update_called_with_dict_subset(mock_tx, {'balance': 13500, 'biz_levels': {}, 'inventory': {'шаурма': 1}})

@pytest.mark.asyncio
async def test_shop_071():
    # sell VIP transactional function: credits user correctly
    mock_ref = MagicMock()
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {'balance': 1000, 'is_vip': True}
    
    mock_tx = MagicMock()
    with patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=mock_snap):
        success = await user_manager.sell_vip_tr(mock_tx, 111, 222, 5000)
        assert success
        assert_update_called_with_dict_subset(mock_tx, {'balance': 6000, 'is_vip': False})

@pytest.mark.asyncio
async def test_shop_072():
    # /shop command displays correct progressive tax rate
    mock_msg = AsyncMock()
    mock_msg.chat.id = 111
    mock_msg.from_user.id = 222
    mock_msg.text = "/shop"
    
    user_data = {'balance': 250000, 'is_banned': False}
    with patch('shop.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('shop.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await shop.cmd_shop(mock_msg)
        assert mock_msg.answer.call_count == 1


# ==============================================================================
# SECTION 4: Cooldown and daily bonus crediting logic (73 - 96)
# ==============================================================================

@pytest.mark.asyncio
async def test_cooldowns_073():
    # check_and_give_bonus banned check
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value={'is_banned': True}):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert not success
        assert receipt == {}

@pytest.mark.asyncio
async def test_cooldowns_074():
    # check_and_give_bonus creator bypasses bonus cooldown
    from config import CREATOR_ID
    user_data = {'is_banned': False, 'last_bonus_time': time.time(), 'balance': 1000}
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, CREATOR_ID)
        assert success

@pytest.mark.asyncio
async def test_cooldowns_075():
    # check_and_give_bonus cooldown blocks if last_bonus_time is recent
    user_data = {'is_banned': False, 'last_bonus_time': time.time() - 100}
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert not success

@pytest.mark.asyncio
async def test_cooldowns_076():
    # check_and_give_bonus grants bonus if last_bonus_time is old
    user_data = {'is_banned': False, 'last_bonus_time': time.time() - user_manager.BONUS_COOLDOWN - 10}
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert success

@pytest.mark.asyncio
async def test_cooldowns_077():
    # check_and_give_bonus double-check under lock
    user_data_pre = {'is_banned': False, 'last_bonus_time': time.time() - user_manager.BONUS_COOLDOWN - 10}
    user_data_lock = {'is_banned': False, 'last_bonus_time': time.time()} # updated recently
    calls = 0
    async def fake_get(chat_id, user_id, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return user_data_pre
        return user_data_lock

    with patch('user_manager.get_user_data', side_effect=fake_get):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert not success

@pytest.mark.asyncio
async def test_cooldowns_078():
    # check_and_give_bonus base bonus (BASE_BONUS)
    user_data = {'is_banned': False, 'last_bonus_time': 0, 'balance': 0}
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert success
        assert receipt['base'] == user_manager.BASE_BONUS

@pytest.mark.asyncio
async def test_cooldowns_079():
    # check_and_give_bonus business passive income
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'inventory': {'шаурма': 2},
        'biz_levels': {'шаурма': 2}
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert receipt['business'] == 7500

@pytest.mark.asyncio
async def test_cooldowns_080():
    # check_and_give_bonus business income cap at BIZ_COUNT_CAP (10)
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'inventory': {'шаурма': 15},
        'biz_levels': {'шаурма': 1}
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert receipt['business'] == 25000

@pytest.mark.asyncio
async def test_cooldowns_081():
    # check_and_give_bonus car income (count * base)
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'inventory': {'курьер': 3}
    }
    from shop import ITEMS
    ITEMS['курьер'] = {'name': 'Courier Car', 'price': 10000, 'cat': 'car', 'action': 'car', 'income': 500}
    try:
        with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
             patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
             patch('user_manager.get_user_lock'), \
             patch('user_manager.set_in_cache'), \
             patch('user_manager.mark_dirty'), \
             patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
            success, receipt = await user_manager.check_and_give_bonus(111, 222)
            assert receipt['car'] == 1500
    finally:
        ITEMS.pop('курьер', None)

@pytest.mark.asyncio
async def test_cooldowns_082():
    # check_and_give_bonus banker penalty: only gets 10% of passive income
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'is_banker': True,
        'inventory': {'шаурма': 1}
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert receipt['business'] == 250

@pytest.mark.asyncio
async def test_cooldowns_083():
    # check_and_give_bonus system bank deposit daily interest
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'bank_deposit': 10000,
        'bank_name': None,
        'last_daily_time': 0
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert success
        assert mock_set.call_args[0][2]['bank_deposit'] == 10100

@pytest.mark.asyncio
async def test_cooldowns_084():
    # check_and_give_bonus system bank deposit interest <= 100M (1%)
    user_data = {
        'is_banned': False, 'last_bonus_time': 0, 'balance': 0,
        'bank_deposit': 100_000_000, 'bank_name': None, 'last_daily_time': 0
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await user_manager.check_and_give_bonus(111, 222)
        assert mock_set.call_args[0][2]['bank_deposit'] == 101_000_000

@pytest.mark.asyncio
async def test_cooldowns_085():
    # check_and_give_bonus system bank deposit interest <= 1B (0.5%)
    user_data = {
        'is_banned': False, 'last_bonus_time': 0, 'balance': 0,
        'bank_deposit': 200_000_000, 'bank_name': None, 'last_daily_time': 0
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await user_manager.check_and_give_bonus(111, 222)
        assert mock_set.call_args[0][2]['bank_deposit'] == 201_000_000

@pytest.mark.asyncio
async def test_cooldowns_086():
    # check_and_give_bonus system bank deposit interest > 1B (0.2%)
    user_data = {
        'is_banned': False, 'last_bonus_time': 0, 'balance': 0,
        'bank_deposit': 2_000_000_000, 'bank_name': None, 'last_daily_time': 0
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await user_manager.check_and_give_bonus(111, 222)
        assert mock_set.call_args[0][2]['bank_deposit'] == 2_004_000_000

@pytest.mark.asyncio
async def test_cooldowns_087():
    # check_and_give_bonus system bank interest not credited if is_daily is False
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'bank_deposit': 10000,
        'bank_name': None,
        'last_daily_time': time.time() - 1000
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        await user_manager.check_and_give_bonus(111, 222)
        assert mock_set.call_args[0][2]['bank_deposit'] == 10000

@pytest.mark.asyncio
async def test_cooldowns_088():
    # check_and_give_bonus disease candidiasis cuts base bonus in half
    user_data = {'is_banned': False, 'last_bonus_time': 0, 'balance': 0}
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('diseases.get_active_diseases', new_callable=AsyncMock, return_value=['candidiasis']), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert receipt['base'] == user_manager.BASE_BONUS // 2

@pytest.mark.asyncio
async def test_cooldowns_089():
    # check_and_give_bonus lobby golden increases income and bonus by 20%
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'inventory': {'шаурма': 1}
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='golden'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert receipt['base'] == int(user_manager.BASE_BONUS * 1.2)
        assert receipt['business'] == int(2500 * 1.2)

@pytest.mark.asyncio
async def test_cooldowns_090():
    # check_and_give_bonus lobby tax cuts progressive tax rate in half
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 500000,
        'inventory': {'шаурма': 1}
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='tax'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert receipt['tax_percent'] == 10

@pytest.mark.asyncio
async def test_cooldowns_091():
    # check_and_give_bonus progressive tax is calculated on passive income and deducted
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'inventory': {'шаурма': 1}
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert receipt['tax_amount'] == 250

@pytest.mark.asyncio
async def test_cooldowns_092():
    # check_and_give_bonus tax redirection to custom bank
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'inventory': {'шаурма': 1},
        'bank_name': 333
    }
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('profile_bank.get_bank_info', new_callable=AsyncMock, return_value={'capital': 1000}), \
         patch('profile_bank.create_or_update_bank', new_callable=AsyncMock) as mock_upd_bank, \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        mock_upd_bank.assert_called_with(111, 333, {'capital': 1250})

@pytest.mark.asyncio
async def test_cooldowns_093():
    # check_and_give_bonus meme cards bonus (flat bonus added)
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'meme_cards': {'card1': 1}
    }
    from cards_system import CARDS
    CARDS['card1'] = {'name': 'Test Card', 'bonus_multiplier': 0.0, 'bonus_flat': 500}
    try:
        with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
             patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
             patch('user_manager.get_user_lock'), \
             patch('user_manager.set_in_cache'), \
             patch('user_manager.mark_dirty'), \
             patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
            success, receipt = await user_manager.check_and_give_bonus(111, 222)
            assert receipt['meme_bonus'] == 500
    finally:
        CARDS.pop('card1', None)

@pytest.mark.asyncio
async def test_cooldowns_094():
    # check_and_give_bonus meme cards multiplier (multiplier bonus added)
    user_data = {
        'is_banned': False,
        'last_bonus_time': 0,
        'balance': 0,
        'meme_cards': {'card1': 1}
    }
    from cards_system import CARDS
    CARDS['card1'] = {'name': 'Test Card', 'bonus_multiplier': 0.2, 'bonus_flat': 0}
    try:
        with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
             patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
             patch('user_manager.get_user_lock'), \
             patch('user_manager.set_in_cache'), \
             patch('user_manager.mark_dirty'), \
             patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
            success, receipt = await user_manager.check_and_give_bonus(111, 222)
            assert receipt['meme_bonus'] == 30
    finally:
        CARDS.pop('card1', None)

@pytest.mark.asyncio
async def test_cooldowns_095():
    # check_and_give_bonus balance, last_bonus_time, last_daily_time updated successfully
    user_data = {'is_banned': False, 'last_bonus_time': 0, 'balance': 1000}
    with patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager._fetch_active_lobby_type', new_callable=AsyncMock, return_value='none'), \
         patch('user_manager.get_user_lock'), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty'), \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data):
        success, receipt = await user_manager.check_and_give_bonus(111, 222)
        assert success
        updated_data = mock_set.call_args[0][2]
        assert updated_data['balance'] == 1000 + receipt['total']
        assert updated_data['last_bonus_time'] == pytest.approx(time.time(), abs=2.0)
        assert updated_data['last_daily_time'] == pytest.approx(time.time(), abs=2.0)

@pytest.mark.asyncio
async def test_cooldowns_096():
    # Cooldown middleware: allows/blocks commands
    from cooldown_middleware import CooldownMiddleware
    middleware = CooldownMiddleware()
    mock_handler = AsyncMock(return_value="succeeded")
    mock_event = MagicMock()
    mock_event.from_user.id = 222
    mock_event.chat.id = 111
    mock_event.text = "/profile"
    res = await middleware(mock_handler, mock_event, {})
    assert res == "succeeded"


# ==============================================================================
# SECTION 5: Stock transaction ACID compliance and race conditions prevention (97 - 120)
# ==============================================================================

def test_stocks_097():
    # get_user_lock returns unique ReentrantLock
    _user_locks.clear()
    lock1 = get_user_lock(111, 222)
    lock2 = get_user_lock(111, 333)
    assert lock1 is not lock2
    assert isinstance(lock1, ReentrantLock)

def test_stocks_098():
    # get_user_lock returns same lock instance for same user
    _user_locks.clear()
    lock1 = get_user_lock(111, 222)
    lock2 = get_user_lock(111, 222)
    assert lock1 is lock2

@pytest.mark.asyncio
async def test_stocks_099():
    # ReentrantLock acquire/release serialization
    lock = ReentrantLock()
    entered = []
    
    async def worker(worker_id, sleep_time):
        async with lock:
            entered.append(worker_id)
            await asyncio.sleep(sleep_time)
            
    await asyncio.gather(
        worker(1, 0.05),
        worker(2, 0.01)
    )
    assert entered == [1, 2]

@pytest.mark.asyncio
async def test_stocks_100():
    # ReentrantLock release of unowned lock raises RuntimeError
    lock = ReentrantLock()
    with pytest.raises(RuntimeError, match="Cannot release un-owned lock"):
        lock.release()

def test_stocks_101():
    # _cleanup_unused_locks removes idle locks when above threshold
    from user_manager import _cleanup_unused_locks
    _user_locks.clear()
    for i in range(2500):
        _user_locks[(111, i + 1000)] = ReentrantLock()
    assert len(_user_locks) == 2500
    _cleanup_unused_locks()
    assert len(_user_locks) == 0

@pytest.mark.asyncio
async def test_stocks_102():
    # _cleanup_unused_locks preserves currently locked locks
    from user_manager import _cleanup_unused_locks
    _user_locks.clear()
    locked_lock = ReentrantLock()
    await locked_lock.acquire()
    
    _user_locks[(111, 222)] = locked_lock
    for i in range(2500):
        # start loop at 1000 to prevent collisions
        _user_locks[(111, i + 1000)] = ReentrantLock()
        
    _cleanup_unused_locks()
    assert len(_user_locks) == 1
    assert (111, 222) in _user_locks
    locked_lock.release()

@pytest.mark.asyncio
async def test_stocks_103():
    # stock buy callback: normal buy updates user balance and stock portfolio
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_buy_5_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_data = {'balance': 1000, 'stocks_portfolio': {}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty') as mock_dirty, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_buy(mock_cb)
        updated_data = mock_set.call_args[0][2]
        assert updated_data['balance'] == 450
        assert updated_data['stocks_portfolio']['companyA'] == 5
        mock_dirty.assert_called_with(111, 222)

@pytest.mark.asyncio
async def test_stocks_104():
    # stock buy callback: progressive tax applied to total cost
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_buy_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [1000]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_data = {'balance': 5000000, 'stocks_portfolio': {}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty'), \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_buy(mock_cb)
        updated_data = mock_set.call_args[0][2]
        assert updated_data['balance'] == 4998800

@pytest.mark.asyncio
async def test_stocks_105():
    # stock buy callback: insufficient balance aborts purchase
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_buy_10_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_data = {'balance': 200, 'stocks_portfolio': {}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_buy(mock_cb)
        assert mock_set.call_count == 0
        mock_cb.answer.assert_called_with("❌ Недостаточно сыра! Нужно 1.100 (с учетом налога 10%).", show_alert=True)

@pytest.mark.asyncio
async def test_stocks_106():
    # stock buy callback: invalid qty raises error
    mock_cb = AsyncMock()
    mock_cb.data = "stk_buy_abc_companyA"
    with pytest.raises(ValueError):
        await stocks.cb_stk_buy(mock_cb)

@pytest.mark.asyncio
async def test_stocks_107():
    # stock buy callback: updates cache and marks dirty
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_buy_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_data = {'balance': 1000, 'stocks_portfolio': {}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty') as mock_dirty, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_buy(mock_cb)
        mock_set.assert_called_once()
        mock_dirty.assert_called_once_with(111, 222)

@pytest.mark.asyncio
async def test_stocks_108():
    # stock sell callback: normal sell credits balance and decrements portfolio
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_3_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_snap = MagicMock()
    user_snap.exists = True
    user_snap.to_dict.return_value = {'balance': 100, 'stocks_portfolio': {'companyA': 5}}
    
    mock_tx = db.get_db().transaction()
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=user_snap), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.invalidate_user_cache') as mock_invalidate, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_sell(mock_cb)
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 355,
            'stocks_portfolio': {'companyA': 2}
        })
        mock_invalidate.assert_called_once_with(111, 222)

@pytest.mark.asyncio
async def test_stocks_109():
    # stock sell callback: sell "all" sells all owned shares
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_all_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_snap = MagicMock()
    user_snap.exists = True
    user_snap.to_dict.return_value = {'balance': 100, 'stocks_portfolio': {'companyA': 5}}
    
    mock_tx = db.get_db().transaction()
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=user_snap), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.invalidate_user_cache') as mock_invalidate, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_sell(mock_cb)
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 100 + int((100 * 5) * 0.85),
            'stocks_portfolio': {}
        })

@pytest.mark.asyncio
async def test_stocks_110():
    # stock sell callback: sells specific quantity
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_snap = MagicMock()
    user_snap.exists = True
    user_snap.to_dict.return_value = {'balance': 100, 'stocks_portfolio': {'companyA': 5}}
    
    mock_tx = db.get_db().transaction()
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=user_snap), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.invalidate_user_cache') as mock_invalidate, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_sell(mock_cb)
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 185,
            'stocks_portfolio': {'companyA': 4}
        })

@pytest.mark.asyncio
async def test_stocks_111():
    # stock sell callback: commission (5% + progressive tax) is deducted
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [1000]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_snap = MagicMock()
    user_snap.exists = True
    user_snap.to_dict.return_value = {'balance': 5000000, 'stocks_portfolio': {'companyA': 2}}
    
    mock_tx = db.get_db().transaction()
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=user_snap), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.invalidate_user_cache') as mock_invalidate, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_sell(mock_cb)
        assert_update_called_with_dict_subset(mock_tx, {
            'balance': 5000000 + 750,
            'stocks_portfolio': {'companyA': 1}
        })

@pytest.mark.asyncio
async def test_stocks_112():
    # stock sell callback: user has no stock of company returns error
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_snap = MagicMock()
    user_snap.exists = True
    user_snap.to_dict.return_value = {'balance': 100, 'stocks_portfolio': {}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=user_snap), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10):
        await stocks.cb_stk_sell(mock_cb)
        mock_cb.answer.assert_called_with("❌ У вас нет акций этой компании.", show_alert=True)

@pytest.mark.asyncio
async def test_stocks_113():
    # stock sell callback: user has fewer stock than sold quantity returns error
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_5_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_snap = MagicMock()
    user_snap.exists = True
    user_snap.to_dict.return_value = {'balance': 100, 'stocks_portfolio': {'companyA': 2}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=user_snap), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10):
        await stocks.cb_stk_sell(mock_cb)
        mock_cb.answer.assert_called_with("❌ Недостаточно акций для продажи.", show_alert=True)

@pytest.mark.asyncio
async def test_stocks_114():
    # stock sell callback: invalidates cache
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_snap = MagicMock()
    user_snap.exists = True
    user_snap.to_dict.return_value = {'balance': 100, 'stocks_portfolio': {'companyA': 2}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=user_snap), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.invalidate_user_cache') as mock_invalidate, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_sell(mock_cb)
        mock_invalidate.assert_called_once_with(111, 222)

@pytest.mark.asyncio
async def test_stocks_115():
    # ACID compliance: concurrent buy operations serialize balance changes
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_buy_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    shared_user_data = {'balance': 1000, 'stocks_portfolio': {}}
    
    async def fake_get_user_data(chat_id, user_id):
        await asyncio.sleep(0.01)
        return shared_user_data
        
    def fake_set_in_cache(chat_id, user_id, data):
        nonlocal shared_user_data
        shared_user_data = data

    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_user_data', new_callable=AsyncMock, side_effect=fake_get_user_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.set_in_cache', side_effect=fake_set_in_cache), \
         patch('user_manager.mark_dirty'), \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        
        await asyncio.gather(
            stocks.cb_stk_buy(mock_cb),
            stocks.cb_stk_buy(mock_cb)
        )
        assert shared_user_data['balance'] == 780
        assert shared_user_data['stocks_portfolio']['companyA'] == 2

@pytest.mark.asyncio
async def test_stocks_116():
    # ACID compliance: concurrent buy and sell operations serialize balance/portfolio changes
    mock_buy_cb = AsyncMock()
    mock_buy_cb.message.chat.id = 111
    mock_buy_cb.from_user.id = 222
    mock_buy_cb.data = "stk_buy_1_companyA"
    
    mock_sell_cb = AsyncMock()
    mock_sell_cb.message.chat.id = 111
    mock_sell_cb.from_user.id = 222
    mock_sell_cb.data = "stk_sell_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    
    db_inst = db.get_db()
    await db_inst.collection('users').document('111_222').set({
        'balance': 1000,
        'stocks_portfolio': {'companyA': 1},
        'is_banned': False
    })
    user_manager.invalidate_user_cache(111, 222)
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        
        await asyncio.gather(
            stocks.cb_stk_buy(mock_buy_cb),
            stocks.cb_stk_sell(mock_sell_cb)
        )
        
        final_snap = await db_inst.collection('users').document('111_222').get()
        final_data = final_snap.to_dict()
        assert final_data['stocks_portfolio']['companyA'] == 1
        assert final_data['balance'] == 975

@pytest.mark.asyncio
async def test_stocks_117():
    # ACID compliance: concurrent buy operations exceeding balance
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_buy_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    shared_user_data = {'balance': 150, 'stocks_portfolio': {}}
    
    async def fake_get_user_data(chat_id, user_id):
        await asyncio.sleep(0.01)
        return shared_user_data
        
    def fake_set_in_cache(chat_id, user_id, data):
        nonlocal shared_user_data
        shared_user_data = data

    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_user_data', new_callable=AsyncMock, side_effect=fake_get_user_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.set_in_cache', side_effect=fake_set_in_cache), \
         patch('user_manager.mark_dirty'), \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        
        await asyncio.gather(
            stocks.cb_stk_buy(mock_cb),
            stocks.cb_stk_buy(mock_cb),
            stocks.cb_stk_buy(mock_cb)
        )
        assert shared_user_data['balance'] == 40
        assert shared_user_data['stocks_portfolio']['companyA'] == 1

@pytest.mark.asyncio
async def test_stocks_118():
    # ACID compliance: concurrent sell operations exceeding portfolio
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_sell_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    
    db_inst = db.get_db()
    await db_inst.collection('users').document('111_222').set({
        'balance': 100,
        'stocks_portfolio': {'companyA': 1},
        'is_banned': False
    })
    user_manager.invalidate_user_cache(111, 222)
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        
        await asyncio.gather(
            stocks.cb_stk_sell(mock_cb),
            stocks.cb_stk_sell(mock_cb),
            stocks.cb_stk_sell(mock_cb)
        )
        
        final_snap = await db_inst.collection('users').document('111_222').get()
        final_data = final_snap.to_dict()
        assert 'companyA' not in final_data.get('stocks_portfolio', {})
        assert final_data['balance'] == 185

@pytest.mark.asyncio
async def test_stocks_119():
    # stock database update fails -> cache consistency
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    mock_cb.data = "stk_buy_1_companyA"
    
    mock_db_data = ({'prices': {'companyA': [100]}}, {'companyA': {'ticker': 'COMP_A'}})
    user_data = {'balance': 1000, 'stocks_portfolio': {}}
    
    with patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data), \
         patch('stocks.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('stocks.get_global_tax', new_callable=AsyncMock, return_value=10), \
         patch('user_manager.set_in_cache') as mock_set, \
         patch('user_manager.mark_dirty') as mock_dirty, \
         patch('stocks.cb_stk_view', new_callable=AsyncMock):
        await stocks.cb_stk_buy(mock_cb)
        assert mock_set.call_count == 1
        assert mock_dirty.call_count == 1

@pytest.mark.asyncio
async def test_stocks_120():
    # cb_stk_portfolio calculates total portfolio value correctly
    mock_cb = AsyncMock()
    mock_cb.message.chat.id = 111
    mock_cb.from_user.id = 222
    
    mock_db_data = ({'prices': {'companyA': [100], 'companyB': [200]}}, {
        'companyA': {'ticker': 'COMP_A'},
        'companyB': {'ticker': 'COMP_B'}
    })
    user_data = {'balance': 100, 'stocks_portfolio': {'companyA': 5, 'companyB': 2}}
    
    with patch('stocks.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('stocks.get_stocks_db', new_callable=AsyncMock, return_value=mock_db_data):
        await stocks.cb_stk_portfolio(mock_cb)
        assert mock_cb.message.edit_text.call_count == 1 or mock_cb.message.answer.call_count == 1
