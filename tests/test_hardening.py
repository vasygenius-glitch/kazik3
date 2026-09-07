"""Regression tests for audited defects; no live service calls."""
import asyncio
import json
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import battle_pass as bp
import duels
from db import MockDB
from security_logging import RedactingFormatter, redact_secrets


def callback(data="bp:claim_all", uid=102):
    message = NS(chat=NS(id=-900001), message_id=77, edit_text=AsyncMock(),
                 edit_reply_markup=AsyncMock(), answer=AsyncMock())
    return NS(data=data, from_user=NS(id=uid, full_name="Player"),
              message=message, answer=AsyncMock())


@pytest.fixture
def clean_bp(monkeypatch, tmp_path):
    monkeypatch.setattr(bp, "_bp_data", {})
    monkeypatch.setattr(bp, "_save_lock", asyncio.Lock())
    monkeypatch.setattr(bp, "BP_FILE", tmp_path / "bp.json")
    locks = {}
    monkeypatch.setattr(bp, "get_user_lock", lambda c, u: locks.setdefault((c, u), asyncio.Lock()))


@pytest.mark.asyncio
async def test_premium_exact_price_and_concurrent_clicks(clean_bp, monkeypatch):
    balance = bp.PREMIUM_PRICE
    debits = []
    async def change(c, u, delta, min_balance=0, **kw):
        nonlocal balance
        await asyncio.sleep(0)
        if balance + delta < min_balance:
            return None
        debits.append(delta)
        balance += delta
        return balance
    monkeypatch.setattr(bp, "update_user_balance", change)
    cb = callback()
    await asyncio.gather(*(bp._process_buy_premium(cb.message, -900001, 102) for _ in range(10)))
    assert debits == [-bp.PREMIUM_PRICE]
    assert balance == 0
    assert bp._get_user_bp(-900001, 102)["premium"] is True


@pytest.mark.asyncio
async def test_claim_all_paid_once_and_alert_within_limit(clean_bp, monkeypatch):
    cb = callback()
    state = bp._get_user_bp(-900001, 102)
    state.update(xp=10**9, level=bp.MAX_LEVEL, premium=True)
    async def credit(*args, **kw):
        await asyncio.sleep(0)
        return 999999
    change = AsyncMock(side_effect=credit)
    monkeypatch.setattr(bp, "update_user_balance", change)
    await asyncio.gather(*(bp.cb_claim_all(cb) for _ in range(10)))
    assert change.await_count == 1
    assert len(state["claimed_free"]) == len(set(state["claimed_free"]))
    assert all(len(call.args[0]) <= 200 and "<b>" not in call.args[0]
               for call in cb.answer.await_args_list if call.args)


@pytest.mark.asyncio
async def test_claim_failure_does_not_consume_rewards(clean_bp, monkeypatch):
    state = bp._get_user_bp(-900001, 102)
    state.update(xp=10**9, level=bp.MAX_LEVEL)
    monkeypatch.setattr(bp, "update_user_balance", AsyncMock(side_effect=OSError("storage failure")))
    with pytest.raises(OSError):
        await bp.cb_claim_all(callback())
    assert not state["claimed_free"]


@pytest.mark.asyncio
async def test_quest_concurrent_claim_is_paid_once(clean_bp, monkeypatch):
    quest = bp.QUEST_POOL[0]
    entry = bp._get_user_quests(-900001, 102)["quests"][quest["id"]]
    entry["progress"] = quest["goal"]
    async def credit(*args, **kw):
        await asyncio.sleep(0)
        return 999999
    change = AsyncMock(side_effect=credit)
    monkeypatch.setattr(bp, "update_user_balance", change)
    cb = callback("bp:claim_quest:" + quest["id"])
    await asyncio.gather(*(bp.cb_claim_quest(cb) for _ in range(10)))
    assert change.await_count == 1
    assert entry["claimed"]


@pytest.mark.parametrize("contents", ["{broken", "[]", "null"])
def test_corrupt_bp_is_not_silently_overwritten(clean_bp, contents):
    bp.BP_FILE.write_text(contents, encoding="utf-8")
    with pytest.raises((RuntimeError, ValueError)):
        bp._load_bp_data_sync()
    assert bp.BP_FILE.read_text(encoding="utf-8") == contents


@pytest.mark.asyncio
async def test_bp_serialization_failure_preserves_previous_file(clean_bp):
    bp.BP_FILE.write_text('{"old": true}', encoding="utf-8")
    bp._bp_data["invalid"] = float("nan")
    with pytest.raises(ValueError):
        await bp._save_bp_data()
    assert json.loads(bp.BP_FILE.read_text()) == {"old": True}


@pytest.mark.asyncio
async def test_bp_executor_receives_deep_snapshot(clean_bp, monkeypatch):
    bp._bp_data["entry"] = {"value": 1}
    original = bp._write_json_sync
    def write(path, data):
        bp._bp_data["entry"]["value"] = 2
        original(path, data)
    monkeypatch.setattr(bp, "_write_json_sync", write)
    await bp._save_bp_data()
    assert json.loads(bp.BP_FILE.read_text())["entry"]["value"] == 1


def test_bp_normalizes_linked_private_identity(monkeypatch):
    monkeypatch.setattr(bp, "resolve_chat_id", lambda c, u: -901)
    assert bp._user_key(102, 102) == bp._user_key(-901, 102)


@pytest.fixture
def duel_session(monkeypatch):
    monkeypatch.setattr(duels, "active_duels", {})
    monkeypatch.setattr(duels, "pending_for_target", {})
    monkeypatch.setattr(duels, "_creation_lock", asyncio.Lock())
    s = duels.DuelSession(-900001, 101, "A", 102, "B", 100, message_id=77)
    key = (s.chat_id, s.challenger_id)
    duels.active_duels[key] = s
    duels.pending_for_target[(s.chat_id, s.target_id)] = key
    return s


@pytest.mark.asyncio
async def test_duel_timeout_does_not_cancel_its_own_refund(duel_session, monkeypatch):
    monkeypatch.setattr(duels, "DUEL_TIMEOUT_SECONDS", 0)
    async def credit(*args, **kw):
        await asyncio.sleep(0)
        return 1000
    change = AsyncMock(side_effect=credit)
    monkeypatch.setattr(duels, "update_user_balance", change)
    task = asyncio.create_task(duels._auto_cancel_duel(NS(edit_message_text=AsyncMock()), duel_session, 77))
    duel_session.timeout_task = task
    await task
    assert not task.cancelled()
    assert change.await_count == 1
    assert not duels.active_duels


def test_stale_cleanup_cannot_delete_new_duel(duel_session):
    old = duels.DuelSession(-900001, 101, "A", 102, "B", 100)
    duels._cleanup_session(old)
    assert duels.active_duels[(-900001, 101)] is duel_session
    assert duels.pending_for_target[(-900001, 102)] == (-900001, 101)


@pytest.mark.asyncio
async def test_accept_spam_debits_once(duel_session, monkeypatch):
    monkeypatch.setattr(duels, "get_user_data", AsyncMock(return_value={"balance": 1000}))
    async def debit(*args, **kw):
        await asyncio.sleep(0)
        return 900
    change = AsyncMock(side_effect=debit)
    run = AsyncMock()
    monkeypatch.setattr(duels, "update_user_balance", change)
    monkeypatch.setattr(duels, "_run_duel", run)
    cb = callback("duel_accept:101")
    await asyncio.gather(*(duels.cb_duel_accept(cb, NS()) for _ in range(10)))
    assert change.await_count == 1
    assert run.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("data,message_id", [("duel_accept:x",77), ("duel_accept:101",76)])
async def test_invalid_or_old_duel_button_does_not_debit(duel_session, monkeypatch, data, message_id):
    change = AsyncMock()
    monkeypatch.setattr(duels, "update_user_balance", change)
    cb = callback(data)
    cb.message.message_id = message_id
    await duels.cb_duel_accept(cb, NS())
    change.assert_not_awaited()


@pytest.mark.asyncio
async def test_duel_telegram_failure_refunds_both_stakes(duel_session, monkeypatch):
    duel_session.state = "running"
    duel_session.target_debited = True
    change = AsyncMock(return_value=1000)
    monkeypatch.setattr(duels, "update_user_balance", change)
    bot = NS(send_message=AsyncMock(side_effect=OSError("network")))
    with pytest.raises(OSError):
        await duels._run_duel(bot, duel_session)
    assert [x.args[1:3] for x in change.await_args_list] == [(101, 100), (102, 100)]
    assert not duels.active_duels


@pytest.mark.asyncio
async def test_uncertain_settlement_is_not_compensated_twice(duel_session, monkeypatch):
    async def fail(bot, session):
        session.state = "settling"
        raise OSError("uncertain storage outcome")
    change = AsyncMock()
    monkeypatch.setattr(duels, "_run_duel_impl", fail)
    monkeypatch.setattr(duels, "update_user_balance", change)
    with pytest.raises(OSError):
        await duels._run_duel(NS(), duel_session)
    change.assert_not_awaited()
    assert duel_session.state == "settling"


@pytest.mark.asyncio
async def test_local_db_does_not_alias_input_or_snapshot(tmp_path):
    db = MockDB(str(tmp_path / "db.json"))
    ref = db.collection("test").document("one")
    data = {"nested": {"value": 1}}
    await ref.set(data)
    data["nested"]["value"] = 9
    snap = await ref.get()
    detached = snap.to_dict()
    assert detached["nested"]["value"] == 1
    detached["nested"]["value"] = 8
    assert (await ref.get()).to_dict()["nested"]["value"] == 1


@pytest.mark.parametrize("secret", ["hf_"+"x"*30, "ghp_"+"x"*36, "123456789:"+"x"*35,
                                    "redis://name:password@host:6379", "https://name:password@host/path"])
def test_log_redaction(secret):
    result = redact_secrets("failure " + secret)
    assert "[REDACTED]" in result
    assert "password" not in result
    assert secret not in result


def test_exception_traceback_redaction():
    token = "123456789:" + "x"*35
    try:
        raise ValueError(token)
    except ValueError:
        import sys
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "request failed", (), sys.exc_info())
    text = RedactingFormatter().format(record)
    assert token not in text
    assert "ValueError" in text


@pytest.mark.asyncio
async def test_admin_eval_disabled_without_executing_code(monkeypatch):
    import config
    import admin_dashboard as admin
    monkeypatch.setattr(config, "ENABLE_ADMIN_EVAL", False)
    msg = NS(from_user=NS(id=config.CREATOR_ID, username=config.CREATOR_USERNAME), answer=AsyncMock(), text="raise RuntimeError('must not run')")
    state = NS(clear=AsyncMock())
    await admin.process_eval_code_input(msg, state)
    state.clear.assert_awaited_once()
    msg.answer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["cr_do_buy_-1_coin", "cr_do_sell_0_coin", "cr_do_invalid_10_coin", "cr_do_buy_foo_coin"])
async def test_crypto_rejects_invalid_trade_before_debit(monkeypatch, data):
    import crypto
    monkeypatch.setattr(crypto, "check_ban", AsyncMock(return_value=False))
    change = AsyncMock()
    import user_manager
    monkeypatch.setattr(user_manager, "update_user_balance", change)
    await crypto.cb_trade_execute(callback(data))
    change.assert_not_awaited()


@pytest.mark.asyncio
async def test_crypto_persists_before_notification_and_rounds_debit_up(monkeypatch):
    import crypto
    import user_manager as um
    monkeypatch.setattr(crypto, "check_ban", AsyncMock(return_value=False))
    monkeypatch.setattr(crypto, "get_all_coins", AsyncMock(return_value={"coin": {"prices": [0.05], "ticker": "C"}}))
    monkeypatch.setattr(um, "get_user_lock", lambda *args: asyncio.Lock())
    monkeypatch.setattr(um, "flush_user_cache_immediately", AsyncMock())
    monkeypatch.setattr(um, "get_user_data", AsyncMock(return_value={"balance": 100, "crypto_portfolio": {}}))
    debit = AsyncMock(return_value=99)
    persist = AsyncMock()
    monkeypatch.setattr(um, "update_user_balance", debit)
    monkeypatch.setattr(um, "update_user_field", persist)
    cb = callback("cr_do_buy_10_coin")
    cb.answer = AsyncMock(side_effect=RuntimeError("Telegram unavailable"))
    with pytest.raises(RuntimeError):
        await crypto.cb_trade_execute(cb)
    debit.assert_awaited_once_with(-900001, 102, -1, min_balance=0)
    persist.assert_awaited_once_with(-900001, 102, "crypto_portfolio", {"coin": 10})


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf"), "broken"])
async def test_crypto_invalid_price_never_changes_balance(monkeypatch, price):
    import crypto
    import user_manager as um
    monkeypatch.setattr(crypto, "check_ban", AsyncMock(return_value=False))
    monkeypatch.setattr(crypto, "get_all_coins", AsyncMock(return_value={"coin": {"prices": [price]}}))
    debit = AsyncMock()
    monkeypatch.setattr(um, "update_user_balance", debit)
    await crypto.cb_trade_execute(callback("cr_do_buy_10_coin"))
    debit.assert_not_awaited()


def test_all_routers_register_in_isolated_process():
    import subprocess
    import sys
    from pathlib import Path
    result = subprocess.run([sys.executable, "-c", "import tests.conftest; import main; from aiogram import Dispatcher; from handlers_init import register_all_handlers; dp=Dispatcher(); register_all_handlers(dp); assert len(dp.sub_routers) >= 40"], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
