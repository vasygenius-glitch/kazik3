# tests/test_cards_concurrency.py
"""
Comprehensive Concurrency & Anti-Duplication Unit Test Suite for Card Opening.
Simulates high-concurrency async spam (10+ parallel requests) for both free
and paid cases to verify race condition protections, balance accuracy,
cooldown enforcement, and card award precision.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock

from db import init_db, get_db
from config import CREATOR_ID
from user_manager import (
    get_user_data,
    update_user_field,
    invalidate_user_cache,
    flush_user_cache_immediately,
    open_free_case_tr,
    buy_and_open_case_tr,
    get_user_lock,
    _user_cache,
    _dirty_cache,
    _user_locks,
)
from cards_system import (
    cmd_free_case,
    callback_open_free_case,
    callback_buy_case,
    cmd_reset_free_case,
    CASES,
    CARDS,
)

# Initialize database (MockDB if no Firebase credentials)
init_db("key.json")


# ─────────────────────────────────────────────────────────────
#  HELPER FIXTURES & UTILITIES
# ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_fast_tests(monkeypatch):
    """Disable UI animation delays and Telegram API calls for rapid execution."""
    monkeypatch.setattr("cards_system.ANIMATION_DELAY", 0)
    monkeypatch.setattr("cards_system.send_card_message", AsyncMock())


async def setup_test_user(chat_id: int, user_id: int, initial_balance: int = 500, initial_ts: float = 0):
    """Cleanly initializes user state in MockDB and invalidates cache."""
    invalidate_user_cache(chat_id, user_id)
    _user_locks.pop((chat_id, user_id), None)

    db_inst = get_db()
    ref = db_inst.collection('chats').document(str(chat_id)).collection('users').document(str(user_id))
    user_data = {
        'balance': initial_balance,
        'bank_deposit': 0,
        'last_free_card_case_ts': initial_ts,
        'inventory': {},
        'meme_cards': {},
        'opened_cases_count': 0,
        'is_banned': False,
        'full_name': f"User_{user_id}",
    }
    await ref.set(user_data, merge=True)
    invalidate_user_cache(chat_id, user_id)
    return user_data


def make_mock_message(chat_id: int, user_id: int, full_name: str = "Test User", text: str = "/free_case"):
    """Creates a mock Telegram Message object."""
    msg = AsyncMock()
    msg.chat.id = chat_id
    msg.from_user.id = user_id
    msg.from_user.full_name = full_name
    msg.text = text

    ans_msg = AsyncMock()
    ans_msg.edit_text = AsyncMock()
    ans_msg.delete = AsyncMock()

    msg.answer = AsyncMock(return_value=ans_msg)
    msg.answer_photo = AsyncMock()
    return msg


def make_mock_callback(chat_id: int, user_id: int, data: str = "card_buy_common_case", full_name: str = "Test User"):
    """Creates a mock Telegram CallbackQuery object."""
    cb = AsyncMock()
    cb.data = data
    cb.from_user.id = user_id
    cb.from_user.full_name = full_name

    msg = AsyncMock()
    msg.chat.id = chat_id
    msg.from_user.id = user_id
    msg.from_user.full_name = full_name
    msg.edit_text = AsyncMock()
    msg.delete = AsyncMock()
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()

    cb.message = msg
    cb.answer = AsyncMock()
    return cb


# ─────────────────────────────────────────────────────────────
#  1. FREE CASE CONCURRENCY TESTS (/free_case & open_free_case_cb)
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_free_case_cmd_concurrency_spam():
    """Verify 15 concurrent /free_case command requests result in EXACTLY 1 card awarded."""
    chat_id, user_id = 900001, 800001
    await setup_test_user(chat_id, user_id, initial_balance=500, initial_ts=0)

    # Prepare 15 concurrent command invocations
    tasks = [cmd_free_case(make_mock_message(chat_id, user_id)) for _ in range(15)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verify database state
    data = await get_user_data(chat_id, user_id)
    meme_cards = data.get("meme_cards", {})
    total_cards = sum(meme_cards.values())

    assert total_cards == 1, f"Expected exactly 1 card awarded, got {total_cards}"
    assert data.get("opened_cases_count") == 1, f"Expected opened_cases_count == 1, got {data.get('opened_cases_count')}"
    assert data.get("last_free_card_case_ts", 0) > 0, "Cooldown timestamp was not updated"


@pytest.mark.asyncio
async def test_free_case_callback_concurrency_spam():
    """Verify 15 concurrent open_free_case_cb callback requests result in EXACTLY 1 card awarded."""
    chat_id, user_id = 900002, 800002
    await setup_test_user(chat_id, user_id, initial_balance=500, initial_ts=0)

    callbacks = [make_mock_callback(chat_id, user_id, data="open_free_case_cb") for _ in range(15)]
    tasks = [callback_open_free_case(cb) for cb in callbacks]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verify database state
    data = await get_user_data(chat_id, user_id)
    meme_cards = data.get("meme_cards", {})
    total_cards = sum(meme_cards.values())

    assert total_cards == 1, f"Expected exactly 1 card awarded, got {total_cards}"
    assert data.get("opened_cases_count") == 1

    # Verify callbacks: 1 success answer, 14 cooldown alert answers
    cooldown_alerts = 0
    success_answers = 0
    for cb in callbacks:
        for call_args in cb.answer.call_args_list:
            arg_str = str(call_args)
            if "доступен через" in arg_str:
                cooldown_alerts += 1
            elif "Открываем бесплатный кейс" in arg_str:
                success_answers += 1

    assert success_answers == 1, f"Expected 1 success callback answer, got {success_answers}"
    assert cooldown_alerts == 14, f"Expected 14 cooldown alert callback answers, got {cooldown_alerts}"


@pytest.mark.asyncio
async def test_free_case_tr_direct_concurrency_spam():
    """Verify low-level open_free_case_tr transaction function under 20 concurrent tasks."""
    chat_id, user_id = 900003, 800003
    await setup_test_user(chat_id, user_id, initial_balance=500, initial_ts=0)

    db_inst = get_db()

    async def run_tr():
        async with get_user_lock(chat_id, user_id):
            res = await open_free_case_tr(db_inst.transaction(), chat_id, user_id, "meme_1")
            if res[0]:
                invalidate_user_cache(chat_id, user_id)
            return res

    results = await asyncio.gather(*[run_tr() for _ in range(20)])
    successes = [r for r in results if r[0] is True]
    failures = [r for r in results if r[0] is False]

    assert len(successes) == 1, f"Expected 1 successful transaction, got {len(successes)}"
    assert len(failures) == 19, f"Expected 19 rejected transactions, got {len(failures)}"

    data = await get_user_data(chat_id, user_id)
    assert data.get("meme_cards", {}).get("meme_1", 0) == 1


@pytest.mark.asyncio
async def test_free_case_concurrency_cooldown_expiry_repetition():
    """Verify two sequential concurrency bursts separated by cooldown expiry award 1 card per burst (2 total)."""
    chat_id, user_id = 900004, 800004
    await setup_test_user(chat_id, user_id, initial_balance=500, initial_ts=0)

    # Burst 1: 10 concurrent requests
    tasks_burst1 = [cmd_free_case(make_mock_message(chat_id, user_id)) for _ in range(10)]
    await asyncio.gather(*tasks_burst1, return_exceptions=True)

    data1 = await get_user_data(chat_id, user_id)
    assert sum(data1.get("meme_cards", {}).values()) == 1

    # Simulate 12 hours passing (cooldown reset)
    await update_user_field(chat_id, user_id, "last_free_card_case_ts", 0)
    await flush_user_cache_immediately(chat_id, user_id)
    invalidate_user_cache(chat_id, user_id)

    # Burst 2: 10 concurrent requests
    tasks_burst2 = [cmd_free_case(make_mock_message(chat_id, user_id)) for _ in range(10)]
    await asyncio.gather(*tasks_burst2, return_exceptions=True)

    data2 = await get_user_data(chat_id, user_id)
    total_cards = sum(data2.get("meme_cards", {}).values())
    assert total_cards == 2, f"Expected 2 cards awarded after 2 bursts + reset, got {total_cards}"
    assert data2.get("opened_cases_count") == 2


@pytest.mark.asyncio
async def test_free_case_concurrency_multi_users():
    """Verify simultaneous free case spam for multiple distinct users operates independently."""
    chat_id = 900005
    user_a, user_b = 800005, 800006
    await setup_test_user(chat_id, user_a, initial_balance=500, initial_ts=0)
    await setup_test_user(chat_id, user_b, initial_balance=500, initial_ts=0)

    tasks_a = [cmd_free_case(make_mock_message(chat_id, user_a)) for _ in range(10)]
    tasks_b = [cmd_free_case(make_mock_message(chat_id, user_b)) for _ in range(10)]

    await asyncio.gather(*(tasks_a + tasks_b), return_exceptions=True)

    data_a = await get_user_data(chat_id, user_a)
    data_b = await get_user_data(chat_id, user_b)

    assert sum(data_a.get("meme_cards", {}).values()) == 1, "User A should have exactly 1 card"
    assert sum(data_b.get("meme_cards", {}).values()) == 1, "User B should have exactly 1 card"


# ─────────────────────────────────────────────────────────────
#  2. PAID CASE CONCURRENCY TESTS (card_buy_ & buy_and_open_case_tr)
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paid_case_exact_balance_concurrency_spam():
    """Verify 15 concurrent paid case requests with balance for 1 case result in 1 purchase, 14 rejections."""
    chat_id, user_id = 900010, 800010
    case_price = CASES["common_case"]["price"]  # 10,000
    await setup_test_user(chat_id, user_id, initial_balance=case_price, initial_ts=0)

    callbacks = [make_mock_callback(chat_id, user_id, data="card_buy_common_case") for _ in range(15)]
    tasks = [callback_buy_case(cb) for cb in callbacks]
    await asyncio.gather(*tasks, return_exceptions=True)

    data = await get_user_data(chat_id, user_id)
    final_balance = data.get("balance", 0)
    total_cards = sum(data.get("meme_cards", {}).values())

    assert final_balance == 0, f"Expected final balance 0, got {final_balance}"
    assert total_cards == 1, f"Expected exactly 1 card awarded, got {total_cards}"
    assert data.get("opened_cases_count") == 1

    insufficient_funds_alerts = 0
    success_answers = 0
    for cb in callbacks:
        for call_args in cb.answer.call_args_list:
            arg_str = str(call_args)
            if "Недостаточно" in arg_str:
                insufficient_funds_alerts += 1
            elif "Открываем кейс" in arg_str:
                success_answers += 1

    assert success_answers == 1, f"Expected 1 success purchase answer, got {success_answers}"
    assert insufficient_funds_alerts == 14, f"Expected 14 insufficient funds answers, got {insufficient_funds_alerts}"


@pytest.mark.asyncio
async def test_paid_case_partial_balance_concurrency_spam():
    """Verify 15 concurrent requests with balance for 3 cases (35,000 / 10,000) award 3 cards and leave 5,000."""
    chat_id, user_id = 900011, 800011
    case_price = CASES["common_case"]["price"]  # 10,000
    initial_bal = 35_000
    await setup_test_user(chat_id, user_id, initial_balance=initial_bal, initial_ts=0)

    callbacks = [make_mock_callback(chat_id, user_id, data="card_buy_common_case") for _ in range(15)]
    tasks = [callback_buy_case(cb) for cb in callbacks]
    await asyncio.gather(*tasks, return_exceptions=True)

    data = await get_user_data(chat_id, user_id)
    final_balance = data.get("balance", 0)
    total_cards = sum(data.get("meme_cards", {}).values())

    assert final_balance == 5000, f"Expected final balance 5000, got {final_balance}"
    assert final_balance >= 0, "Balance must never go negative"
    assert total_cards == 3, f"Expected exactly 3 cards awarded, got {total_cards}"
    assert data.get("opened_cases_count") == 3


@pytest.mark.asyncio
async def test_paid_case_insufficient_balance_concurrency_spam():
    """Verify 12 concurrent requests with balance lower than case price (5,000 < 10,000) all fail cleanly."""
    chat_id, user_id = 900012, 800012
    initial_bal = 5000
    await setup_test_user(chat_id, user_id, initial_balance=initial_bal, initial_ts=0)

    callbacks = [make_mock_callback(chat_id, user_id, data="card_buy_common_case") for _ in range(12)]
    tasks = [callback_buy_case(cb) for cb in callbacks]
    await asyncio.gather(*tasks, return_exceptions=True)

    data = await get_user_data(chat_id, user_id)
    final_balance = data.get("balance", 0)
    total_cards = sum(data.get("meme_cards", {}).values())

    assert final_balance == 5000, f"Balance should remain untouched at 5000, got {final_balance}"
    assert total_cards == 0, f"Expected 0 cards awarded, got {total_cards}"
    assert data.get("opened_cases_count") == 0


@pytest.mark.asyncio
async def test_paid_case_abundant_balance_concurrency_spam():
    """Verify 10 concurrent requests with exact balance for 10 cases (100,000 / 10,000) all succeed (10 cards)."""
    chat_id, user_id = 900013, 800013
    initial_bal = 100_000
    await setup_test_user(chat_id, user_id, initial_balance=initial_bal, initial_ts=0)

    callbacks = [make_mock_callback(chat_id, user_id, data="card_buy_common_case") for _ in range(10)]
    tasks = [callback_buy_case(cb) for cb in callbacks]
    await asyncio.gather(*tasks, return_exceptions=True)

    data = await get_user_data(chat_id, user_id)
    final_balance = data.get("balance", 0)
    total_cards = sum(data.get("meme_cards", {}).values())

    assert final_balance == 0, f"Expected final balance 0, got {final_balance}"
    assert total_cards == 10, f"Expected exactly 10 cards awarded, got {total_cards}"
    assert data.get("opened_cases_count") == 10


@pytest.mark.asyncio
async def test_paid_case_epic_case_concurrency_spam():
    """Verify 10 concurrent requests for epic_case (50,000 each) with 120,000 balance award 2 cards, leave 20,000."""
    chat_id, user_id = 900014, 800014
    initial_bal = 120_000
    await setup_test_user(chat_id, user_id, initial_balance=initial_bal, initial_ts=0)

    callbacks = [make_mock_callback(chat_id, user_id, data="card_buy_epic_case") for _ in range(10)]
    tasks = [callback_buy_case(cb) for cb in callbacks]
    await asyncio.gather(*tasks, return_exceptions=True)

    data = await get_user_data(chat_id, user_id)
    final_balance = data.get("balance", 0)
    total_cards = sum(data.get("meme_cards", {}).values())

    assert final_balance == 20000, f"Expected final balance 20000, got {final_balance}"
    assert total_cards == 2, f"Expected exactly 2 cards awarded, got {total_cards}"
    assert data.get("opened_cases_count") == 2


@pytest.mark.asyncio
async def test_paid_case_tr_direct_concurrency_spam():
    """Verify low-level buy_and_open_case_tr function directly with 20 concurrent tasks."""
    chat_id, user_id = 900015, 800015
    initial_bal = 30_000
    case_price = 10_000
    await setup_test_user(chat_id, user_id, initial_balance=initial_bal, initial_ts=0)

    db_inst = get_db()

    async def run_tr():
        async with get_user_lock(chat_id, user_id):
            res = await buy_and_open_case_tr(db_inst.transaction(), chat_id, user_id, case_price, "meme_1")
            if res[0]:
                invalidate_user_cache(chat_id, user_id)
            return res

    results = await asyncio.gather(*[run_tr() for _ in range(20)])
    successes = [r for r in results if r[0] is True]
    failures = [r for r in results if r[0] is False]

    assert len(successes) == 3, f"Expected 3 successful purchases, got {len(successes)}"
    assert len(failures) == 17, f"Expected 17 rejections, got {len(failures)}"

    data = await get_user_data(chat_id, user_id)
    assert data.get("balance") == 0
    assert data.get("meme_cards", {}).get("meme_1", 0) == 3


@pytest.mark.asyncio
async def test_paid_case_concurrency_multi_users():
    """Verify simultaneous paid case spam across distinct users deducts respective balances accurately."""
    chat_id = 900016
    user_1, user_2 = 800016, 800017
    await setup_test_user(chat_id, user_1, initial_balance=20_000, initial_ts=0)
    await setup_test_user(chat_id, user_2, initial_balance=50_000, initial_ts=0)

    callbacks_1 = [make_mock_callback(chat_id, user_1, data="card_buy_common_case") for _ in range(10)]
    callbacks_2 = [make_mock_callback(chat_id, user_2, data="card_buy_common_case") for _ in range(10)]

    tasks_1 = [callback_buy_case(cb) for cb in callbacks_1]
    tasks_2 = [callback_buy_case(cb) for cb in callbacks_2]

    await asyncio.gather(*(tasks_1 + tasks_2), return_exceptions=True)

    data_1 = await get_user_data(chat_id, user_1)
    data_2 = await get_user_data(chat_id, user_2)

    assert data_1.get("balance") == 0
    assert sum(data_1.get("meme_cards", {}).values()) == 2

    assert data_2.get("balance") == 0
    assert sum(data_2.get("meme_cards", {}).values()) == 5


# ─────────────────────────────────────────────────────────────
#  3. ADVERSARIAL & EDGE CASE CONCURRENCY TESTS
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mixed_free_and_paid_case_concurrency_spam():
    """Verify simultaneous spam of 10 free case requests + 10 paid case requests (20 total concurrent tasks)."""
    chat_id, user_id = 900020, 800020
    initial_bal = 20_000
    await setup_test_user(chat_id, user_id, initial_balance=initial_bal, initial_ts=0)

    free_tasks = [cmd_free_case(make_mock_message(chat_id, user_id)) for _ in range(10)]
    paid_callbacks = [make_mock_callback(chat_id, user_id, data="card_buy_common_case") for _ in range(10)]
    paid_tasks = [callback_buy_case(cb) for cb in paid_callbacks]

    await asyncio.gather(*(free_tasks + paid_tasks), return_exceptions=True)

    data = await get_user_data(chat_id, user_id)
    final_balance = data.get("balance", 0)
    total_cards = sum(data.get("meme_cards", {}).values())

    # 1 free card + 2 paid cards = 3 cards total
    assert final_balance == 0, f"Expected final balance 0, got {final_balance}"
    assert total_cards == 3, f"Expected 3 cards total (1 free + 2 paid), got {total_cards}"
    assert data.get("opened_cases_count") == 3
    assert data.get("last_free_card_case_ts", 0) > 0


@pytest.mark.asyncio
async def test_zero_balance_paid_case_concurrency():
    """Verify 15 concurrent paid case requests on 0 balance leave balance at 0 and award 0 cards."""
    chat_id, user_id = 900021, 800021
    await setup_test_user(chat_id, user_id, initial_balance=0, initial_ts=0)

    callbacks = [make_mock_callback(chat_id, user_id, data="card_buy_common_case") for _ in range(15)]
    tasks = [callback_buy_case(cb) for cb in callbacks]
    await asyncio.gather(*tasks, return_exceptions=True)

    data = await get_user_data(chat_id, user_id)
    assert data.get("balance") == 0
    assert sum(data.get("meme_cards", {}).values()) == 0


@pytest.mark.asyncio
async def test_creator_free_case_concurrency_cooldown():
    """Verify Creator account free case requests still obey concurrency atomicity (1 card per burst)."""
    chat_id = 900022
    creator_user_id = CREATOR_ID
    await setup_test_user(chat_id, creator_user_id, initial_balance=500, initial_ts=0)

    tasks = [cmd_free_case(make_mock_message(chat_id, creator_user_id)) for _ in range(10)]
    await asyncio.gather(*tasks, return_exceptions=True)

    data = await get_user_data(chat_id, creator_user_id)
    total_cards = sum(data.get("meme_cards", {}).values())
    assert total_cards == 1, f"Expected Creator to receive exactly 1 card per free case burst, got {total_cards}"
