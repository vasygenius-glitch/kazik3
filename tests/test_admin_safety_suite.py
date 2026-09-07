"""Admin authorization, state-machine and financial/backup regression coverage."""
import asyncio
import base64
import gzip
import inspect
import json
from collections import OrderedDict
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
import admin_dashboard as admin
import admin_safety
import backup_system as backup
import user_manager as users
from db import MockDB


def message(text="100", user=None):
    return NS(text=text, from_user=NS(id=admin.CREATOR_ID if user is None else user, full_name="Operator"),
              chat=NS(id=-501, type="supergroup"), message_id=17, bot=NS(id=123),
              answer=AsyncMock(), delete=AsyncMock())


def callback(data="db_pv_-501_777", user=None):
    msg = message()
    msg.edit_text, msg.edit_reply_markup = AsyncMock(), AsyncMock()
    return NS(data=data, from_user=NS(id=admin.CREATOR_ID if user is None else user),
              message=msg, bot=NS(id=123), answer=AsyncMock())


def state_for(uid=None, cid=-501, storage=None):
    return FSMContext(storage=storage or MemoryStorage(), key=StorageKey(
        bot_id=123, chat_id=cid, user_id=admin.CREATOR_ID if uid is None else uid))


GUARDED = sorted(name for name, value in vars(admin).items()
                 if name.startswith(("cb_", "process_", "cmd_")) and inspect.iscoroutinefunction(value)
                 and hasattr(value, "__wrapped__"))


@pytest.mark.asyncio
@pytest.mark.parametrize("name", GUARDED)
async def test_every_guarded_panel_handler_rejects_non_creator(name, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Unauthorized database access"))
    monkeypatch.setattr(admin, "get_db", forbidden)
    event = callback(user=-999) if name.startswith("cb_") else message(user=-999)
    await getattr(admin, name)(event)
    forbidden.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,expected", sorted(admin._ADMIN_INPUT_STATES.items()))
async def test_every_panel_input_rejects_non_text(name, expected, monkeypatch):
    state = state_for()
    await state.set_state(expected)
    forbidden = Mock(side_effect=AssertionError("Non-text input reached database"))
    monkeypatch.setattr(admin, "get_db", forbidden)
    msg = message(None)
    await getattr(admin, name)(msg, state)
    assert await state.get_state() == expected
    msg.answer.assert_awaited_once()
    forbidden.assert_not_called()


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "1e999", None, 12, True])
def test_float_parser_rejects_invalid_or_nonfinite_values(value):
    assert admin.parse_float(value, minimum=0, maximum=100) is None


@pytest.mark.parametrize("value", [None, 12, True, "x", "9223372036854775808", "-9223372036854775808"])
def test_integer_parser_rejects_invalid_values(value):
    assert admin.parse_int(value) is None


@pytest.mark.asyncio
async def test_panel_cash_submission_is_applied_once(monkeypatch):
    state = state_for()
    await state.set_state(admin.AdminPanelState.waiting_for_player_money_add)
    await state.update_data(chat_id=-501, target_user_id=777)
    async def credit(*args, **kwargs):
        await asyncio.sleep(0)
        return 1100
    change = AsyncMock(side_effect=credit)
    monkeypatch.setattr(admin, "update_user_balance", change)
    monkeypatch.setattr(admin, "flush_user_cache_immediately", AsyncMock())
    monkeypatch.setattr(admin, "show_player_details_screen", AsyncMock())
    await asyncio.gather(*(admin.process_player_money_add(message(), state) for _ in range(10)))
    assert change.await_count == 1


@pytest.mark.asyncio
async def test_cancel_navigation_disarms_old_input(monkeypatch):
    state = state_for()
    await state.set_state(admin.AdminPanelState.waiting_for_player_money_add)
    await state.update_data(chat_id=-501, target_user_id=777)
    monkeypatch.setattr(admin, "show_player_details_screen", AsyncMock())
    change = AsyncMock()
    monkeypatch.setattr(admin, "update_user_balance", change)
    await admin.cb_player_details_view(callback(), state)
    assert await state.get_state() is None
    await admin.process_player_money_add(message(), state)
    change.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_notification_does_not_leave_repeatable_cash_dialog(monkeypatch):
    state = state_for()
    await state.set_state(admin.AdminPanelState.waiting_for_player_money_add)
    await state.update_data(chat_id=-501, target_user_id=777)
    change = AsyncMock(return_value=1100)
    monkeypatch.setattr(admin, "update_user_balance", change)
    monkeypatch.setattr(admin, "flush_user_cache_immediately", AsyncMock())
    msg = message()
    msg.answer = AsyncMock(side_effect=OSError("Telegram unavailable"))
    await admin.process_player_money_add(msg, state)
    assert await state.get_state() is None
    await admin.process_player_money_add(message(), state)
    change.assert_awaited_once()


@pytest.mark.asyncio
async def test_wipe_confirmation_is_single_use(monkeypatch):
    state = state_for()
    cb = callback("db_pwic_-501_777")
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Confirm", callback_data=cb.data)]])
    await admin_safety.arm_confirmation(state, cb, markup)
    wipe = AsyncMock(return_value=True)
    monkeypatch.setattr(users, "wipe_user_data", wipe)
    monkeypatch.setattr(admin, "show_player_details_screen", AsyncMock())
    await asyncio.gather(*(admin.cb_perform_player_wipe(cb, state) for _ in range(5)))
    wipe.assert_awaited_once_with(-501, 777)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["expired", "message", "actor", "action"])
async def test_confirmation_is_bound_to_context(change):
    state = state_for()
    cb = callback("db_pwic_-501_777")
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Confirm", callback_data=cb.data)]])
    await admin_safety.arm_confirmation(state, cb, markup)
    if change == "expired":
        data = await state.get_data()
        data["admin_confirmation"]["expires"] = 0
        await state.set_data(data)
    elif change == "message": cb.message.message_id += 1
    elif change == "actor": cb.from_user.id += 1
    else: cb.data = "db_pwic_-501_778"
    assert not await admin_safety.consume_confirmation(state, cb)


@pytest.mark.asyncio
async def test_fsm_reset_uses_injected_storage_not_bot_dispatcher(monkeypatch):
    state = state_for()
    target = state_for(777, storage=state.storage)
    await target.set_state("Game:waiting")
    monkeypatch.setattr(admin, "show_player_details_screen", AsyncMock())
    await admin.cb_player_fsm_reset(callback("db_pfsm_reset_-501_777"), state)
    assert await target.get_state() is None


@pytest.mark.asyncio
async def test_safe_answer_respects_telegram_limit():
    cb = callback()
    await admin.safe_answer(cb, "<b>" + "x"*500 + "</b>", show_alert=True)
    value = cb.answer.await_args.kwargs["text"]
    assert len(value) == 200 and "<b>" not in value


@pytest.mark.asyncio
async def test_unmute_preserves_group_default_permissions():
    permissions = ChatPermissions(can_send_messages=True, can_send_photos=False)
    bot = NS(get_chat=AsyncMock(return_value=NS(permissions=permissions)))
    assert await admin_safety.default_chat_permissions(bot, -501) is permissions


@pytest.mark.asyncio
async def test_cache_flush_failure_preserves_dirty_entry(monkeypatch):
    entries = OrderedDict({(-501, 777): {"data": {"balance": 100}, "timestamp": 0}})
    monkeypatch.setattr(users, "_user_cache", entries)
    monkeypatch.setattr(users, "_dirty_cache", {(-501, 777)})
    monkeypatch.setattr(users, "flush_user_cache_immediately", AsyncMock(side_effect=OSError("disk")))
    with pytest.raises(OSError):
        await users.clear_user_cache_safely()
    assert (-501, 777) in users._user_cache and (-501, 777) in users._dirty_cache


@pytest.mark.asyncio
async def test_bank_refund_and_deposit_clear_are_idempotent(tmp_path, monkeypatch):
    db = MockDB(str(tmp_path / "db.json"))
    ref = db.collection("chats").document("-501").collection("users").document("777")
    await ref.set({"balance": 20, "bank_name": "99", "bank_deposit": 100})
    monkeypatch.setattr(admin, "get_user_ref", lambda *args: ref)
    monkeypatch.setattr(admin, "flush_user_cache_immediately", AsyncMock())
    monkeypatch.setattr(admin, "invalidate_user_cache", Mock())
    assert await admin._settle_bank_deposit(-501, 99, 777, True) == (100, True)
    assert await admin._settle_bank_deposit(-501, 99, 777, True) == (0, False)
    data = (await ref.get()).to_dict()
    assert data["balance"] == 120 and data["bank_deposit"] == 0 and data["bank_name"] is None


def pack(data):
    return base64.b64encode(gzip.compress(json.dumps(data).encode())).decode()


def valid_backup():
    return {"chats": {"-501": {"users": {"777": {"balance": 10}}, "banks": {}, "clans": {}}}}


@pytest.mark.parametrize("data", [{}, {"chats": {}}, {"chats": []}, {"chats": {"-501": {"users": {}}}},
                                   {"chats": {"bad": {"users": {}, "banks": {}, "clans": {}}}}])
def test_incomplete_backup_is_rejected(data):
    with pytest.raises(ValueError): backup.decode_backup(pack(data))


def test_compressed_backup_size_limit(monkeypatch):
    monkeypatch.setattr(backup, "MAX_JSON_BYTES", 16)
    with pytest.raises(ValueError): backup.decode_backup(pack(valid_backup()))


@pytest.fixture
def backup_db(tmp_path, monkeypatch):
    db = MockDB(str(tmp_path / "db.json"))
    monkeypatch.setattr(backup, "get_db", lambda: db)
    monkeypatch.setattr(backup, "get_whitelist", AsyncMock(return_value={-501: "Test"}))
    monkeypatch.setattr(backup, "flush_all_user_data", AsyncMock())
    monkeypatch.setattr(backup, "invalidate_user_cache", Mock())
    monkeypatch.setattr(backup, "invalidate_bank_cache", Mock())
    monkeypatch.setattr(backup, "_backup_lock", asyncio.Lock())
    monkeypatch.setattr(backup, "_restore_lock", asyncio.Lock())
    return db


@pytest.mark.asyncio
async def test_backup_restore_validates_before_mutation(backup_db):
    users_ref = backup_db.collection("chats").document("-501").collection("users")
    await users_ref.document("777").set({"balance": 99})
    await backup_db.collection("backups").document("backup_1").set({"payload": pack({"chats": {"-501": {"users": {}}}})})
    ok, _ = await backup.restore_database("backup_1")
    assert not ok
    assert (await users_ref.document("777").get()).to_dict()["balance"] == 99


@pytest.mark.asyncio
async def test_backup_restore_requires_maintenance(backup_db):
    await backup_db.collection("backups").document("backup_1").set({"payload": pack(valid_backup())})
    ok, error = await backup.restore_database("backup_1")
    assert not ok and "техрежим" in error


@pytest.mark.asyncio
async def test_restore_creates_rollback_and_replaces_records(backup_db):
    ref = backup_db.collection("chats").document("-501").collection("users")
    await ref.document("777").set({"balance": 99})
    await ref.document("888").set({"balance": 50})
    await backup_db.collection("bot_settings").document("maintenance").set({"active": True})
    await backup_db.collection("backups").document("backup_1").set({"payload": pack(valid_backup())})
    ok, error = await backup.restore_database("backup_1")
    assert ok, error
    assert (await ref.document("777").get()).to_dict()["balance"] == 10
    assert not (await ref.document("888").get()).exists
    docs = await backup_db.collection("backups").get()
    safety = [doc.to_dict() for doc in docs if doc.to_dict().get("reason") == "pre-restore"]
    assert len(safety) == 1
    assert backup.decode_backup(safety[0]["payload"])["chats"]["-501"]["users"]["777"]["balance"] == 99


@pytest.mark.asyncio
async def test_restore_write_failure_does_not_delete_old_users(backup_db, monkeypatch):
    ref = backup_db.collection("chats").document("-501").collection("users")
    await ref.document("888").set({"balance": 50})
    await backup_db.collection("bot_settings").document("maintenance").set({"active": True})
    await backup_db.collection("backups").document("backup_1").set({"payload": pack(valid_backup())})
    monkeypatch.setattr(backup_db, "batch", lambda: NS(set=Mock(), commit=AsyncMock(side_effect=OSError("storage"))))
    ok, error = await backup.restore_database("backup_1")
    assert not ok and "Защитная копия" in error
    assert (await ref.document("888").get()).to_dict()["balance"] == 50


@pytest.mark.parametrize("fields", [{"balance": 2**80}, {"items": [[1]]}, {"balance": float("nan")}])
def test_backup_rejects_unrestorable_document_values(fields):
    data = valid_backup()
    data["chats"]["-501"]["users"]["777"] = fields
    with pytest.raises(ValueError):
        backup.decode_backup(pack(data))


@pytest.mark.asyncio
async def test_restore_aborts_if_safety_snapshot_fails(backup_db, monkeypatch):
    ref = backup_db.collection("chats").document("-501").collection("users").document("777")
    await ref.set({"balance": 99})
    await backup_db.collection("bot_settings").document("maintenance").set({"active": True})
    await backup_db.collection("backups").document("backup_1").set({"payload": pack(valid_backup())})
    monkeypatch.setattr(backup, "backup_database", AsyncMock(return_value=(False, "offline")))
    assert not (await backup.restore_database("backup_1"))[0]
    assert (await ref.get()).to_dict()["balance"] == 99


@pytest.mark.asyncio
async def test_backup_ids_do_not_collide_in_same_second(backup_db, monkeypatch):
    monkeypatch.setattr(backup.time, "time", lambda: 1_700_000_000)
    first = await backup.backup_database()
    second = await backup.backup_database()
    assert first[0] and second[0] and first[1] != second[1]


@pytest.mark.asyncio
async def test_retention_failure_does_not_hide_created_backup(backup_db, monkeypatch):
    original = backup_db.collection
    collection = original("backups")
    broken = NS(document=collection.document, get=AsyncMock(side_effect=OSError("cleanup")))
    monkeypatch.setattr(backup_db, "collection", lambda name: broken if name == "backups" else original(name))
    ok, backup_id = await backup.backup_database()
    assert ok and (await collection.document(backup_id).get()).exists


@pytest.mark.asyncio
async def test_cancel_does_not_erase_other_game_state():
    from aiogram.dispatcher.event.bases import SkipHandler
    state = state_for()
    await state.set_state("Blackjack:playing")
    with pytest.raises(SkipHandler):
        await admin.cmd_cancel(message("/cancel"), state)
    assert await state.get_state() == "Blackjack:playing"


@pytest.mark.asyncio
async def test_backup_worker_does_not_wait_full_day_before_first_copy(monkeypatch):
    create = AsyncMock(return_value=(True, "backup_1"))
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    monkeypatch.setattr(backup, "backup_database", create)
    monkeypatch.setattr(backup.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await backup.backup_database_task()
    assert [call.args[0] for call in sleep.await_args_list] == [60, 86400]
    create.assert_awaited_once()
