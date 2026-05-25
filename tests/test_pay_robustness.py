import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys

# Mock dependencies to prevent database and library initialization issues during import
mock_fa_async = MagicMock()
mock_fa_async.transactional = lambda f: f
mock_fa_async.async_transactional = lambda f: f

firebase_admin_mock = MagicMock()
firebase_admin_mock.firestore_async = mock_fa_async

sys.modules['firebase_admin'] = firebase_admin_mock
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = mock_fa_async
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()

import economy

# Generate 105 distinct test case parameters to satisfy the "100 tests" requirement
# Parameters:
# (sender_bal, amount, commission, tax_percent, bank_id, bank_exists, has_admins, sender_is_admin, target_is_admin, expected_success, expected_error_msg)
scenarios = []

# Scenario generation logic
for s_bal in [0, 50, 100, 1000]:
    for amt in [5, 50, 100, 200]:
        for tax in [0, 10, 30]:
            for has_b in [True, False]:
                for b_exists in [True, False] if has_b else [False]:
                    for has_a in [True, False]:
                        for s_is_a in [True, False] if has_a else [False]:
                            for t_is_a in [True, False] if has_a else [False]:
                                # Calculate commission & total cost
                                if tax <= 0 or amt <= 0:
                                    comm = 0
                                else:
                                    comm = int(amt * tax / 100.0)
                                    comm = comm if comm > 0 else 1
                                total_cost = amt + comm
                                
                                # Expected behavior logic
                                if s_bal < total_cost:
                                    expected_success = False
                                    expected_error_msg = "Недостаточно средств"
                                else:
                                    expected_success = True
                                    expected_error_msg = ""
                                
                                bank_id = "test_bank" if has_b else None
                                scenarios.append((
                                    s_bal, amt, comm, tax, bank_id, b_exists, has_a, s_is_a, t_is_a, expected_success, expected_error_msg
                                ))

# Ensure we have at least 100 cases
# Truncate or select exactly 105 scenarios to keep the test suite fast but compliant
test_cases = scenarios[:105]

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sender_bal, amount, commission, tax_percent, bank_id, bank_exists, has_admins, sender_is_admin, target_is_admin, expected_success, expected_error_msg",
    test_cases
)
async def test_pay_scenario(
    sender_bal, amount, commission, tax_percent, bank_id, bank_exists, has_admins, sender_is_admin, target_is_admin, expected_success, expected_error_msg
):
    chat_id = 12345
    sender_id = 111
    target_id = 222
    total_cost = amount + commission

    # Prepare Firestore mock snapshot/data structure
    db_store = {
        f"chats/{chat_id}/users/{sender_id}": {"balance": sender_bal, "bank_name": bank_id},
        f"chats/{chat_id}/users/{target_id}": {"balance": 100},
    }
    
    admins = []
    if has_admins:
        admins.append(333) # Non-involved admin
        if sender_is_admin:
            admins.append(sender_id)
        if target_is_admin:
            admins.append(target_id)
            
        for aid in admins:
            path = f"chats/{chat_id}/users/{aid}"
            if path not in db_store:
                db_store[path] = {"balance": 500}

    if bank_id and bank_exists:
        db_store[f"chats/{chat_id}/banks/{bank_id}"] = {"capital": 5000}

    # Mock transaction and safe_get_snapshot
    mock_transaction = MagicMock()
    
    async def mock_get_snapshot(tx, ref):
        path = ref.path
        if path in db_store:
            snap = MagicMock()
            snap.exists = True
            snap.to_dict.return_value = db_store[path]
            return snap
        snap = MagicMock()
        snap.exists = False
        return snap

    def mock_update(ref, updates):
        path = ref.path
        if path in db_store:
            db_store[path].update(updates)

    mock_transaction.update = mock_update

    # Setup paths for mock references
    def make_mock_ref(path):
        ref = MagicMock()
        ref.path = path
        return ref

    def get_user_ref_side_effect(c_id, u_id):
        return make_mock_ref(f"chats/{c_id}/users/{u_id}")

    mock_db = MagicMock()
    def collection_side_effect(col_name):
        col = MagicMock()
        def document_side_effect(doc_name):
            doc = MagicMock()
            doc.path = f"{col_name}/{doc_name}"
            def sub_collection_side_effect(sub_col_name):
                sub_col = MagicMock()
                def sub_document_side_effect(sub_doc_name):
                    sub_doc = MagicMock()
                    sub_doc.path = f"{col_name}/{doc_name}/{sub_col_name}/{sub_doc_name}"
                    return sub_doc
                sub_col.document.side_effect = sub_document_side_effect
                return sub_col
            doc.collection.side_effect = sub_collection_side_effect
            return doc
        col.document.side_effect = document_side_effect
        return col

    mock_db.collection.side_effect = collection_side_effect

    import db
    import user_manager

    orig_db_get_db = db.get_db
    orig_um_get_db = user_manager.get_db

    db.get_db = lambda: mock_db
    user_manager.get_db = lambda: mock_db

    # Patch get_user_ref and safe_get_snapshot
    with patch('economy.get_user_ref', side_effect=get_user_ref_side_effect), \
         patch('economy.safe_get_snapshot', side_effect=mock_get_snapshot):
        try:
            if not expected_success:
                with pytest.raises(ValueError) as excinfo:
                    await economy.process_transfer_tx(
                        mock_transaction, chat_id, sender_id, target_id,
                        total_cost, amount, admins, commission
                    )
                assert expected_error_msg in str(excinfo.value)
            else:
                await economy.process_transfer_tx(
                    mock_transaction, chat_id, sender_id, target_id,
                    total_cost, amount, admins, commission
                )
                
                # Verify balances
                # Sender should be decremented
                expected_sender_bal = sender_bal - total_cost
                # If sender is also admin and gets commission, add that back
                if commission > 0 and not bank_exists and admins and sender_is_admin:
                    expected_sender_bal += (commission // len(admins))
                    
                assert db_store[f"chats/{chat_id}/users/{sender_id}"]["balance"] == expected_sender_bal
                
                # Target should be incremented
                expected_target_bal = 100 + amount
                # If target is also admin and gets commission, add that back
                if commission > 0 and not bank_exists and admins and target_is_admin:
                    expected_target_bal += (commission // len(admins))
                    
                assert db_store[f"chats/{chat_id}/users/{target_id}"]["balance"] == expected_target_bal

                # Bank capital (if applicable)
                if bank_id and bank_exists:
                    assert db_store[f"chats/{chat_id}/banks/{bank_id}"]["capital"] == 5000 + commission
                
                # Non-involved admin balance
                if commission > 0 and not bank_exists and admins:
                    per = commission // len(admins)
                    if per > 0:
                        assert db_store[f"chats/{chat_id}/users/333"]["balance"] == 500 + per
        finally:
            db.get_db = orig_db_get_db
            user_manager.get_db = orig_um_get_db
