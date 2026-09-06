import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta

# 1. Imports from duels
from duels import (
    DuelSession,
    active_duels,
    pending_for_target,
    _session_key,
    _cleanup_session,
    _accept_keyboard,
    _mention,
    DUEL_TAX_PERCENT,
    MIN_DUEL_BET,
    DUEL_TIMEOUT_SECONDS,
)

# 2. Imports from battle_pass
from battle_pass import (
    _get_user_bp,
    _get_user_quests,
    _calc_xp_boost,
    _make_progress_bar,
    _compose_bp_message,
    _compose_quests_message,
    _compose_levels_table,
    _bp_main_keyboard,
    _quests_keyboard,
    _levels_keyboard,
    add_bp_xp,
    record_quest_progress,
    _bp_data,
    FREE_REWARDS,
    PREMIUM_REWARDS,
    QUEST_POOL,
    MAX_LEVEL,
    XP_PER_LEVEL,
    PREMIUM_PRICE,
)

# 3. Imports from user_manager
from user_manager import (
    user_lock_context,
    _extract_chat_user_ids,
    user_action_locked,
    get_user_lock,
)


# ============================================================
#  1. DUELS SYSTEM TESTS
# ============================================================

def test_duel_session_creation_and_expiry():
    session = DuelSession(
        chat_id=-1001234567,
        challenger_id=111,
        challenger_name="Alice",
        target_id=222,
        target_name="Bob",
        bet=500,
    )
    assert session.chat_id == -1001234567
    assert session.challenger_id == 111
    assert session.target_id == 222
    assert session.bet == 500
    assert not session.is_expired

    # Simulate expired session
    session.created_at = datetime.now(timezone.utc) - timedelta(seconds=DUEL_TIMEOUT_SECONDS + 5)
    assert session.is_expired


def test_duel_session_cleanup():
    chat_id = -100999
    challenger_id = 101
    target_id = 202

    session = DuelSession(
        chat_id=chat_id,
        challenger_id=challenger_id,
        challenger_name="PlayerA",
        target_id=target_id,
        target_name="PlayerB",
        bet=100,
    )
    key = _session_key(chat_id, challenger_id)
    active_duels[key] = session
    pending_for_target[(chat_id, target_id)] = key

    assert key in active_duels
    assert (chat_id, target_id) in pending_for_target

    _cleanup_session(session)

    assert key not in active_duels
    assert (chat_id, target_id) not in pending_for_target


def test_duel_accept_keyboard():
    kb = _accept_keyboard(555)
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 2
    assert buttons[0].text == "⚔️ Принять вызов"
    assert buttons[0].callback_data == "duel_accept:555"
    assert buttons[1].text == "❌ Отклонить"
    assert buttons[1].callback_data == "duel_decline:555"


def test_duel_mention_html_escaping():
    mention = _mention(12345, "<b>Hacker</b> & Pro")
    assert "tg://user?id=12345" in mention
    assert "&lt;b&gt;Hacker&lt;/b&gt; &amp; Pro" in mention


def test_duel_pot_and_tax_calculation():
    bet = 1000
    total_pot = bet * 2
    tax = int(total_pot * DUEL_TAX_PERCENT)
    winner_payout = total_pot - tax

    assert total_pot == 2000
    assert tax == 40  # 2% of 2000
    assert winner_payout == 1960


# ============================================================
#  2. BATTLE PASS & QUESTS TESTS
# ============================================================

def test_battle_pass_constants_and_tables():
    assert MAX_LEVEL == 20
    assert XP_PER_LEVEL == 1000
    assert PREMIUM_PRICE == 25000
    assert len(FREE_REWARDS) == MAX_LEVEL
    assert len(PREMIUM_REWARDS) == MAX_LEVEL
    assert len(QUEST_POOL) >= 3

    # Check that all rewards have coins
    for r in FREE_REWARDS:
        assert "coins" in r and r["coins"] > 0
    for r in PREMIUM_REWARDS:
        assert "coins" in r and r["coins"] > 0


def test_progress_bar_rendering():
    bar0 = _make_progress_bar(0, 1000, 10)
    assert bar0 == "░" * 10

    bar50 = _make_progress_bar(500, 1000, 10)
    assert bar50 == "█████░░░░░"

    bar100 = _make_progress_bar(1000, 1000, 10)
    assert bar100 == "██████████"


@pytest.mark.asyncio
async def test_battle_pass_xp_and_leveling():
    chat_id = -100555
    user_id = 99901
    key = f"{chat_id}:{user_id}"
    _bp_data.pop(key, None)

    # Initially Level 1, 0 XP
    bp = _get_user_bp(chat_id, user_id)
    assert bp["level"] == 1
    assert bp["xp"] == 0

    # Add 400 XP -> still level 1
    lvl, leveled_up = await add_bp_xp(chat_id, user_id, 400)
    assert lvl == 1
    assert not leveled_up
    assert bp["xp"] == 400

    # Add 600 XP -> reaches 1000 XP -> level 2
    lvl, leveled_up = await add_bp_xp(chat_id, user_id, 600)
    assert lvl == 2
    assert leveled_up
    assert bp["level"] == 2
    assert bp["xp"] == 0  # 1000 consumed for level 1 -> 2

    # Add enough XP to reach level 5
    lvl, leveled_up = await add_bp_xp(chat_id, user_id, 10000)
    assert lvl >= 5
    assert bp["level"] == lvl


def test_battle_pass_xp_boost_calculation():
    bp = {
        "claimed_free": [3],        # Level 4 has 5% boost
        "claimed_premium": [0],     # Level 1 has 10% boost
        "premium": True,
    }
    boost = _calc_xp_boost(bp)
    assert boost == 15  # 5 + 10


@pytest.mark.asyncio
async def test_daily_quests_lifecycle_and_progress():
    chat_id = -100777
    user_id = 88801
    key = f"{chat_id}:{user_id}"
    _bp_data.pop(key, None)

    q_data = _get_user_quests(chat_id, user_id)
    assert "quests" in q_data
    assert "play_games" in q_data["quests"]
    assert q_data["quests"]["play_games"]["progress"] == 0

    # Advance quest progress
    await record_quest_progress(chat_id, user_id, "play_games", 2)
    assert q_data["quests"]["play_games"]["progress"] == 2

    # Advance past goal (goal is 5)
    await record_quest_progress(chat_id, user_id, "play_games", 10)
    assert q_data["quests"]["play_games"]["progress"] == 5  # Clamped to goal


def test_battle_pass_messages_and_keyboards():
    chat_id = -100888
    user_id = 77701
    key = f"{chat_id}:{user_id}"
    _bp_data.pop(key, None)

    msg = _compose_bp_message(chat_id, user_id)
    assert "Боевой пропуск" in msg
    assert "Уровень: <b>1</b>" in msg

    kb = _bp_main_keyboard(has_premium=False, has_claimable=True)
    assert len(kb.inline_keyboard) >= 3

    quests_msg, quests_state = _compose_quests_message(chat_id, user_id)
    assert "Ежедневные задания" in quests_msg
    assert len(quests_state) >= 3

    levels_msg = _compose_levels_table()
    assert "Таблица уровней" in levels_msg
    assert "Premium" in levels_msg


# ============================================================
#  3. CONCURRENCY LOCK TESTS (Designed by GPT-6 Astra)
# ============================================================

def test_extract_chat_user_ids():
    # 1. Explicit tuple
    cid, uid = _extract_chat_user_ids((123, 456), {})
    assert (cid, uid) == (123, 456)

    # 2. Kwargs
    cid, uid = _extract_chat_user_ids((), {"chat_id": 999, "user_id": 888})
    assert (cid, uid) == (999, 888)

    # 3. Mock Message
    mock_msg = MagicMock(spec=["chat", "from_user"])
    mock_msg.chat.id = -100111
    mock_msg.from_user.id = 222
    cid, uid = _extract_chat_user_ids((mock_msg,), {})
    assert (cid, uid) == (-100111, 222)

    # 4. Mock CallbackQuery
    mock_cb = MagicMock(spec=["message", "from_user"])
    mock_cb.message.chat.id = -100333
    mock_cb.from_user.id = 444
    cid, uid = _extract_chat_user_ids((mock_cb,), {})
    assert (cid, uid) == (-100333, 444)

    # 5. Invalid arguments
    with pytest.raises(TypeError):
        _extract_chat_user_ids((None,), {})


@pytest.mark.asyncio
async def test_user_lock_context_and_decorator():
    chat_id = -100123
    user_id = 99988

    # Test context manager
    async with user_lock_context(chat_id, user_id) as lock:
        assert lock.locked()
    assert not lock.locked()

    # Test decorator
    call_log = []

    @user_action_locked
    async def sample_action(chat_id: int, user_id: int, val: int):
        call_log.append(f"start:{val}")
        await asyncio.sleep(0.01)
        call_log.append(f"end:{val}")
        return val * 2

    res = await sample_action(chat_id, user_id, 10)
    assert res == 20
    assert call_log == ["start:10", "end:10"]

    # Test that concurrent calls for the same user are serialized
    call_log.clear()
    t1 = asyncio.create_task(sample_action(chat_id, user_id, 1))
    t2 = asyncio.create_task(sample_action(chat_id, user_id, 2))
    await asyncio.gather(t1, t2)

    # Should serialize: start:1 -> end:1 -> start:2 -> end:2 (or 2 then 1)
    assert (call_log == ["start:1", "end:1", "start:2", "end:2"] or
            call_log == ["start:2", "end:2", "start:1", "end:1"])
