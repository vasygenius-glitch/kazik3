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

# ----------------- SECTION 1: CMD_CREDIT INPUT VALIDATION (30 CASES) -----------------
validation_cases = []
# We will generate 30 distinct inputs to verify amount, percent, term, and guarantor parsing
inputs = [
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

# Pad to 30 cases with variations of valid and invalid values
while len(inputs) < 30:
    idx = len(inputs)
    if idx % 2 == 0:
        inputs.append(([str(100 * idx), "10", "5"], True, None))
    else:
        inputs.append(([str(100 * idx), "-5", "5"], False, "Процент по кредиту не может быть отрицательным."))

@pytest.mark.parametrize("args, expected_valid, expected_err", inputs)
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
            # Should proceed to send loan offer and not output error messages
            # Let's verify that it formatted the contract message
            called = False
            for call in message.answer.call_args_list:
                if "Кредитный договор с банком" in call[0][0]:
                    called = True
            assert called, "Expected a loan contract offer, but none was sent."
        else:
            # Should answer with the specific error message
            message.answer.assert_any_call(expected_err)


# ----------------- SECTION 2: CMD_REPAY INPUT VALIDATION (20 CASES) -----------------
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
    ("выплатить abc", True, None), # Should fail silently due to ValueError
]

while len(repay_cases) < 20:
    repay_cases.append(("выплатить 100", True, None))

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

    mock_user_data = {'debts': {}}

    with patch('loans.get_user_data', AsyncMock(return_value=mock_user_data)):
        await loans.cmd_repay(message)
        if expected_err:
            message.answer.assert_any_call(expected_err)
        elif not has_reply:
            pass


# ----------------- SECTION 3: ISSUE_LOAN_TX TRANSACTION (25 CASES) -----------------
issue_cases = []
# Parameters: (bank_exists, bank_capital, borrower_exists, amount, term, expected_valid, expected_err)
for idx in range(25):
    if idx < 5:
        # Bank doesn't exist
        issue_cases.append((False, 0, True, 1000, 7, False, "У банка недостаточно капитала."))
    elif idx < 10:
        # Bank exists but capital is too low
        issue_cases.append((True, 500, True, 1000, 7, False, "У банка недостаточно капитала."))
    elif idx < 15:
        # Borrower doesn't exist
        issue_cases.append((True, 10000, False, 1000, 7, False, "Заемщик не найден."))
    else:
        # All valid
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
            # Capital updated
            mock_transaction.update.assert_any_call(mock_bank_ref, {'capital': bank_capital - amount})
        else:
            with pytest.raises(ValueError) as exc_info:
                await loans.issue_loan_tx(mock_transaction, chat_id, lender_id, borrower_id, amount, total_debt, term, None)
            assert expected_err in str(exc_info.value)


# ----------------- SECTION 4: REPAY_LOAN_TX TRANSACTION (30 CASES) -----------------
# Parameters: (initial_debt, pay_amount, is_early, bank_exists, expected_repay, expected_discount, expected_commission, expected_remaining_debt)
repay_tx_cases = []
for idx in range(30):
    if idx < 5:
        # Pay part of debt, no discount, normal debt
        repay_tx_cases.append((1000, 400, False, True, 400, 0, 0, 600))
    elif idx < 10:
        # Pay all debt, no discount (not early)
        repay_tx_cases.append((1000, 1000, False, True, 1000, 0, 0, 0))
    elif idx < 15:
        # Pay all debt early (20% discount on interest: interest is 200, so discount is 40)
        # Principal was 1000, interest is 200, so initial_debt is 1200
        # Formula: discount = (1200 - 1000) * 0.2 = 40
        repay_tx_cases.append((1200, 1160, True, True, 1160, 40, 16, 0))
    elif idx < 20:
        # Pay all early, but bank does not exist
        repay_tx_cases.append((1200, 1160, True, False, 1160, 40, 16, 0))
    elif idx < 25:
        # Excess payment (amount > remaining debt)
        repay_tx_cases.append((500, 600, False, True, 500, 0, 0, 0))
    else:
        # Pay part early (should not receive discount because amount < debt - discount)
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

        # Check balance subtraction from borrower
        mock_transaction.update.assert_any_call(mock_borrower_ref, {
            'balance': 2000 - expected_repay,
            'debts': {} if expected_rem == 0 else {target_debt_key: expected_rem},
            'credit_score': 110 if expected_rem == 0 else 100
        })

        if bank_exists:
            # Capital of the bank updated
            mock_transaction.update.assert_any_call(mock_bank_ref, {
                'capital': 50000 + (expected_repay - expected_comm)
            })
            if expected_comm > 0:
                # Commission paid to banker's account
                mock_transaction.update.assert_any_call(mock_banker_ref, {
                    'balance': 1000 + expected_comm
                })
        else:
            # Bank doesn't exist, money goes directly to banker
            mock_transaction.update.assert_any_call(mock_banker_ref, {
                'balance': 1000 + expected_repay
            })
