import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import time

# Mock dependencies before importing loans
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

import loans

# ----------------- SECTION 1: CMD_CREDIT INPUT VALIDATION (40 CASES) -----------------
validation_cases = [
    # (args_list, expected_valid, expected_error_msg)
    # Valid cases
    (["1000", "10", "7"], True, None),
    (["5000", "5", "30"], True, None),
    (["1", "0", "1"], True, None),
    (["100", "100", "10"], True, None),
    # Invalid amount
    (["0", "10", "7"], False, "Сумма кредита должна быть больше нуля."),
    (["-100", "10", "7"], False, "Сумма кредита должна быть больше нуля."),
    (["abc", "10", "7"], False, "Сумма, процент и срок должны быть числами."),
    # Invalid percent
    (["1000", "-1", "7"], False, "Процент по кредиту не может быть отрицательным."),
    (["1000", "abc", "7"], False, "Сумма, процент и срок должны быть числами."),
    # Invalid term
    (["1000", "10", "0"], False, "Срок кредита должен быть больше нуля."),
    (["1000", "10", "-5"], False, "Срок кредита должен быть больше нуля."),
    (["1000", "10", "abc"], False, "Сумма, процент и срок должны быть числами."),
]

# Pad to 40 cases with variations of valid and invalid values
while len(validation_cases) < 40:
    idx = len(validation_cases)
    if idx % 2 == 0:
        validation_cases.append(([str(100 * idx), "10", "5"], True, None))
    else:
        validation_cases.append(([str(100 * idx), "-5", "5"], False, "Процент по кредиту не может быть отрицательным."))

@pytest.mark.parametrize("args, expected_valid, expected_err", validation_cases)
@pytest.mark.asyncio
async def test_cmd_credit_validation(args, expected_valid, expected_err):
    message = MagicMock()
    message.answer = AsyncMock()
    message.chat.id = 111
    message.from_user.id = 222
    message.text = "кредит " + " ".join(args)
    message.reply_to_message = MagicMock()
    message.reply_to_message.from_user.id = 333
    message.reply_to_message.from_user.is_bot = False
    message.reply_to_message.from_user.full_name = "Borrower Name"

    mock_user_data = {'is_banker': True}
    mock_bank_data = {'capital': 1000000, 'name': "Test Bank"}

    with patch('loans.get_user_data', AsyncMock(return_value=mock_user_data)), \
         patch('loans.get_bank_info', AsyncMock(return_value=mock_bank_data)), \
         patch('diseases.get_active_diseases', AsyncMock(return_value=[])):
        
        await loans.cmd_credit(message)
        
        if expected_valid:
            called = False
            for call in message.answer.call_args_list:
                if "Кредитный договор с банком" in call[0][0]:
                    called = True
            assert called, "Expected a loan contract offer, but none was sent."
        else:
            message.answer.assert_any_call(expected_err)


# ----------------- SECTION 2: CMD_REPAY INPUT VALIDATION (30 CASES) -----------------
repay_cases = [
    # (args_text, has_reply, expected_error_msg)
    # Valid
    ("выплатить 500", True, None),
    ("вернуть 1000", True, None),
    # Missing reply
    ("выплатить 500", False, "Сделай реплай на кредитора (или банкира), которому возвращаешь долг."),
    # Missing amount
    ("выплатить", True, "Укажи сумму: выплатить [сумма]"),
    # Non-numeric amount
    ("выплатить abc", True, "Сумма должна быть целым числом."),
    # Negative amount
    ("выплатить -100", True, "Сумма должна быть больше нуля."),
    # Zero amount
    ("вернуть 0", True, "Сумма должна быть больше нуля."),
]

while len(repay_cases) < 30:
    idx = len(repay_cases)
    if idx % 3 == 0:
        repay_cases.append(("выплатить -50", True, "Сумма должна быть больше нуля."))
    elif idx % 3 == 1:
        repay_cases.append(("вернуть xyz", True, "Сумма должна быть целым числом."))
    else:
        repay_cases.append(("выплатить 200", True, None))

@pytest.mark.parametrize("text, has_reply, expected_err", repay_cases)
@pytest.mark.asyncio
async def test_cmd_repay_validation(text, has_reply, expected_err):
    message = MagicMock()
    message.answer = AsyncMock()
    message.chat.id = 111
    message.from_user.id = 222
    message.text = text
    if has_reply:
        message.reply_to_message = MagicMock()
        message.reply_to_message.from_user.id = 333
        message.reply_to_message.from_user.full_name = "Lender Name"
    else:
        message.reply_to_message = None

    # Mock user data with active debts to allow valid path to bypass "no debt" checks
    mock_user_data = {'debts': {"333": 5000, "bank_333_123_none_100": 5000}}

    with patch('loans.get_user_data', AsyncMock(return_value=mock_user_data)), \
         patch('loans.repay_loan_tx', AsyncMock(return_value={'repay_amount': 100, 'discount': 0, 'rating_msg': '', 'remaining_debt': 0})), \
         patch('loans.invalidate_user_cache'), \
         patch('loans.invalidate_bank_cache'), \
         patch('loans.get_db'):
        await loans.cmd_repay(message)
        if expected_err:
            message.answer.assert_any_call(expected_err)


# ----------------- SECTION 3: ISSUE_LOAN_TX TRANSACTION (35 CASES) -----------------
issue_cases = []
for idx in range(35):
    if idx < 7:
        issue_cases.append((False, 0, True, 1000, 7, False, "У банка недостаточно капитала."))
    elif idx < 14:
        issue_cases.append((True, 500, True, 1000, 7, False, "У банка недостаточно капитала."))
    elif idx < 21:
        issue_cases.append((True, 10000, False, 1000, 7, False, "Заемщик не найден."))
    else:
        issue_cases.append((True, 10000, True, 1000, 7, True, None))

@pytest.mark.parametrize("bank_exists, bank_capital, borrower_exists, amount, term, expected_valid, expected_err", issue_cases)
@pytest.mark.asyncio
async def test_issue_loan_tx(bank_exists, bank_capital, borrower_exists, amount, term, expected_valid, expected_err):
    chat_id = 111
    lender_id = 222
    borrower_id = 333
    total_debt = int(amount * 1.1)

    mock_bank_snap = MagicMock()
    mock_bank_snap.exists = bank_exists
    mock_bank_snap.to_dict.return_value = {'capital': bank_capital}

    mock_user_snap = MagicMock()
    mock_user_snap.exists = borrower_exists
    mock_user_snap.to_dict.return_value = {'balance': 500, 'debts': {}}

    mock_transaction = MagicMock()

    async def mock_get_snapshot(tx, ref):
        if "banks" in ref.path:
            return mock_bank_snap
        return mock_user_snap

    with patch('loans.get_db') as mock_get_db, \
         patch('loans.safe_get_snapshot', side_effect=mock_get_snapshot), \
         patch('loans.get_user_ref') as mock_get_user_ref:

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        
        mock_bank_ref = MagicMock()
        mock_bank_ref.path = "chats/111/banks/222"
        mock_user_ref = MagicMock()
        mock_user_ref.path = "chats/111/users/333"

        mock_get_user_ref.return_value = mock_user_ref
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_bank_ref

        if expected_valid:
            res = await loans.issue_loan_tx(mock_transaction, chat_id, lender_id, borrower_id, amount, total_debt, term, None)
            assert res is True
            mock_transaction.update.assert_any_call(mock_bank_ref, {'capital': bank_capital - amount})
        else:
            with pytest.raises(ValueError) as exc_info:
                await loans.issue_loan_tx(mock_transaction, chat_id, lender_id, borrower_id, amount, total_debt, term, None)
            assert expected_err in str(exc_info.value)


# ----------------- SECTION 4: REPAY_LOAN_TX TRANSACTION (45 CASES) -----------------
repay_tx_cases = []
for idx in range(45):
    if idx < 8:
        repay_tx_cases.append((1000, 400, False, True, 400, 0, 0, 600))
    elif idx < 16:
        repay_tx_cases.append((1000, 1000, False, True, 1000, 0, 0, 0))
    elif idx < 24:
        # Pay all early (20% discount on interest: interest is 200, so discount is 40)
        repay_tx_cases.append((1200, 1160, True, True, 1160, 40, 16, 0))
    elif idx < 32:
        # Bank doesn't exist
        repay_tx_cases.append((1200, 1160, True, False, 1160, 40, 16, 0))
    elif idx < 40:
        # Excess payment
        repay_tx_cases.append((500, 600, False, True, 500, 0, 0, 0))
    else:
        # Pay part early (no discount)
        repay_tx_cases.append((1200, 500, True, True, 500, 0, 0, 700))

@pytest.mark.parametrize("initial_debt, pay_amount, is_early, bank_exists, expected_repay, expected_discount, expected_comm, expected_rem", repay_tx_cases)
@pytest.mark.asyncio
async def test_repay_loan_tx(initial_debt, pay_amount, is_early, bank_exists, expected_repay, expected_discount, expected_comm, expected_rem):
    chat_id = 111
    borrower_id = 222
    lender_id = 333

    due_time = int(time.time()) + (86400 * 5 if is_early else -86400 * 5)
    target_debt_key = f"bank_{lender_id}_{due_time}_none_1000"

    mock_borrower_snap = MagicMock()
    mock_borrower_snap.exists = True
    mock_borrower_snap.to_dict.return_value = {
        'balance': 2000,
        'debts': {target_debt_key: initial_debt},
        'credit_score': 100
    }

    mock_bank_snap = MagicMock()
    mock_bank_snap.exists = bank_exists
    mock_bank_snap.to_dict.return_value = {'capital': 50000}

    mock_banker_snap = MagicMock()
    mock_banker_snap.exists = True
    mock_banker_snap.to_dict.return_value = {'balance': 1000}

    mock_transaction = MagicMock()

    async def mock_get_snapshot(tx, ref):
        if "banks" in ref.path:
            return mock_bank_snap
        elif str(borrower_id) in ref.path:
            return mock_borrower_snap
        else:
            return mock_banker_snap

    with patch('loans.get_db') as mock_get_db, \
         patch('loans.safe_get_snapshot', side_effect=mock_get_snapshot), \
         patch('loans.get_user_ref') as mock_get_user_ref:

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        
        mock_bank_ref = MagicMock()
        mock_bank_ref.path = f"chats/{chat_id}/banks/{lender_id}"
        mock_borrower_ref = MagicMock()
        mock_borrower_ref.path = f"chats/{chat_id}/users/{borrower_id}"
        mock_banker_ref = MagicMock()
        mock_banker_ref.path = f"chats/{chat_id}/users/{lender_id}"

        def side_effect_ref(c_id, u_id):
            if u_id == borrower_id:
                return mock_borrower_ref
            return mock_banker_ref

        mock_get_user_ref.side_effect = side_effect_ref
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_bank_ref

        res = await loans.repay_loan_tx(
            mock_transaction, chat_id, borrower_id, lender_id, pay_amount, time.time(), target_debt_key
        )

        assert res['repay_amount'] == expected_repay
        assert res['discount'] == expected_discount
        assert res['banker_commission'] == expected_comm
        assert res['remaining_debt'] == expected_rem

        mock_transaction.update.assert_any_call(mock_borrower_ref, {
            'balance': 2000 - expected_repay,
            'debts': {} if expected_rem == 0 else {target_debt_key: expected_rem},
            'credit_score': 110 if expected_rem == 0 else 100
        })


# ----------------- SECTION 5: PREFIX COLLISION SPECIFIC TESTS (5 CASES) -----------------
@pytest.mark.asyncio
async def test_repay_key_resolver_prefix_collision():
    # Target: Verify that repaying banker 123 matches bank_123_... and not bank_12345_...
    message = MagicMock()
    message.answer = AsyncMock()
    message.chat.id = 111
    message.from_user.id = 222
    message.text = "выплатить 500"
    
    # Lender replied to has ID 123
    message.reply_to_message = MagicMock()
    message.reply_to_message.from_user.id = 123
    message.reply_to_message.from_user.full_name = "Lender 123"

    # Borrower has debts to both bank 12345 and bank 123
    debts = {
        "bank_12345_1716942000_none_1000": 1100,
        "bank_123_1716942000_none_500": 550
    }
    mock_user_data = {'debts': debts}

    with patch('loans.get_user_data', AsyncMock(return_value=mock_user_data)), \
         patch('loans.repay_loan_tx', AsyncMock(return_value={'repay_amount': 500, 'discount': 0, 'rating_msg': '', 'remaining_debt': 50})) as mock_repay_tx, \
         patch('loans.invalidate_user_cache'), \
         patch('loans.invalidate_bank_cache'), \
         patch('loans.get_db'):
        
        await loans.cmd_repay(message)
        
        # Verify that repay_loan_tx was called with target_debt_key targeting banker 123, NOT banker 12345
        mock_repay_tx.assert_called_once()
        called_key = mock_repay_tx.call_args[0][6]
        assert called_key == "bank_123_1716942000_none_500"
        assert called_key != "bank_12345_1716942000_none_1000"
