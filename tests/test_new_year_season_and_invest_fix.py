import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from seasons import (
    SEASON_TEMPLATES,
    perform_season_transition,
    cmd_ny_spin,
    cmd_mandarin,
)
from diseases import DISEASES
from profile_bank import (
    cb_bank_stats,
    INVEST_COOLDOWN,
    INVEST_MAX_STAKE,
)
from tests.test_analog_horror_season import FakeDB


def test_new_year_prep_template_and_disease():
    assert "new_year_prep" in SEASON_TEMPLATES
    ny = SEASON_TEMPLATES["new_year_prep"]
    assert ny["id"] == "new_year_prep"
    assert "ПОДГОТОВКА К НОВОМУ ГОДУ" in ny["name"]
    assert ny["multiplier"] == 1.25
    assert ny["game_win_chance_boost"] == 10
    assert "tangerine_allergy" in DISEASES


@pytest.mark.asyncio
async def test_perform_season_transition_new_year_full_wipe(monkeypatch):
    fake_db = FakeDB()
    bot = AsyncMock()

    chat_doc = fake_db.collection("chats").document("999")
    chat_doc.users._docs["u1"] = {
        "balance": 999_999_999_999,
        "bank_deposit": 500_000_000,
        "bank_name": 6896326008,
        "is_banker": True,
        "co_banker_of": 6896326008,
        "inventory": {"dictor_supernova": 1, "chips": 100},
        "crypto_portfolio": {"chsyr": 500},
        "meme_cards": {"c1": 3},
        "card_shards": 2500,
        "prestige_level": 5,
        "prestige_coins": 900,
        "v2": {"xp": 1200},
        "diseases": {"aids": time.time() + 1000},
    }
    chat_doc.banks._docs["6896326008"] = {"name": "Вадия VIP", "capital": 22_000_000_000_000}
    chat_doc.clans._docs["clan1"] = {"treasury": 5_000_000}

    monkeypatch.setattr("seasons.get_db", lambda: fake_db)
    monkeypatch.setattr("whitelist.get_whitelist", AsyncMock(return_value={"999": "Puxxzz chat"}))

    bp_reset_mock = AsyncMock()
    monkeypatch.setattr("battle_pass.reset_all_battle_pass", bp_reset_mock)

    res = await perform_season_transition(bot, new_season_id="new_year_prep", do_wipe=True)
    assert res["status"] == "success"
    assert res["season"] == "new_year_prep"
    assert res["banks_wiped"] == 1
    assert res["clans_wiped"] == 1
    bp_reset_mock.assert_awaited_once()

    season_doc = await fake_db.collection("bot_settings").document("season").get()
    s_data = season_doc.to_dict()
    assert s_data["id"] == "new_year_prep"
    assert s_data["active"] is True

    # Verify total user + bank + clan reset (while preserving old dictors!)
    u1 = chat_doc.users._docs["u1"]
    assert u1["balance"] == 500
    assert u1["bank_deposit"] == 0
    assert u1["bank_name"] is None
    assert u1["is_banker"] is False
    assert u1["co_banker_of"] is None
    assert u1["inventory"] == {"dictor_supernova": 1}
    assert u1["crypto_portfolio"] == {}
    assert u1["meme_cards"] == {}
    assert u1["card_shards"] == 0
    assert u1["prestige_level"] == 0
    assert u1["prestige_coins"] == 0
    assert u1["v2"] == {}
    assert u1["diseases"] == {}
    assert "6896326008" not in chat_doc.banks._docs
    assert chat_doc.clans._docs["clan1"]["treasury"] == 0


@pytest.mark.asyncio
async def test_bank_invest_cooldown_and_stake_cap():
    now = int(time.time())
    huge_bank = {
        "banker_id": 6896326008,
        "name": "Вадия VIP",
        "capital": 10_000_000_000_000,
        "last_invest_time": 0,
    }

    cb = MagicMock()
    cb.data = "bstat_doinv_safe_6896326008"
    cb.from_user = MagicMock(id=6896326008)
    cb.message = MagicMock()
    cb.message.chat = MagicMock(id=-1002321279920)
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()

    saved_updates = {}

    async def mock_update_bank(chat_id, banker_id, upd):
        saved_updates.update(upd)
        huge_bank.update(upd)

    with patch("profile_bank.get_bank_info", AsyncMock(return_value=huge_bank)), \
         patch("profile_bank.create_or_update_bank", side_effect=mock_update_bank), \
         patch("profile_bank.show_bank_schemes", AsyncMock()), \
         patch("random.random", return_value=0.0):
        await cb_bank_stats(cb)

    # Profit on safe (+7%) is capped at 7% of INVEST_MAX_STAKE (25M * 0.07 = 1.75M), NOT trillions!
    profit = saved_updates["capital"] - 10_000_000_000_000
    assert profit == int(INVEST_MAX_STAKE * 0.07)
    assert saved_updates["last_invest_time"] >= now

    # Immediate second click is blocked by cooldown
    cb.answer.reset_mock()
    with patch("profile_bank.get_bank_info", AsyncMock(return_value=huge_bank)):
        await cb_bank_stats(cb)

    cb.answer.assert_awaited_once()
    assert "перерыве" in cb.answer.call_args[0][0]
    assert INVEST_COOLDOWN == 900


@pytest.mark.asyncio
async def test_ny_mandarin_cures_allergy(monkeypatch):
    user_state = {
        "balance": 500,
        "is_banned": False,
        "last_mandarin_time": 0,
        "diseases": {"tangerine_allergy": time.time() + 1000},
    }

    async def mock_cfg():
        return {"active": True, "id": "new_year_prep"}

    async def mock_get_user_data(chat_id, user_id):
        return user_state

    async def mock_update_bal(chat_id, user_id, amount, action=""):
        user_state["balance"] += amount

    async def mock_update_field(chat_id, user_id, field, val):
        user_state[field] = val

    monkeypatch.setattr("seasons.get_season_config", mock_cfg)
    monkeypatch.setattr("seasons.get_user_data", mock_get_user_data)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    monkeypatch.setattr("seasons.update_user_balance", mock_update_bal)
    monkeypatch.setattr("seasons.update_user_field", mock_update_field)
    monkeypatch.setattr("user_manager.update_user_field", mock_update_field)

    msg = AsyncMock()
    msg.chat.id = 111
    msg.from_user.id = 222
    msg.answer = AsyncMock()

    await cmd_mandarin(msg)
    assert user_state["balance"] > 500
    assert "tangerine_allergy" not in user_state["diseases"]
    assert "НОВОГОДНИЙ ПЕРЕКУС" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_restore_banks_and_dictors_from_pre_wipe_backup():
    import base64
    import gzip
    import json
    import creator

    pre_wipe_payload_raw = json.dumps({
        "version": 2,
        "chats": {
            "-1002321279920": {
                "users": {
                    "6896326008": {"balance": 99999999, "inventory": {"dictor_emperor": 2, "chips": 500}},
                    "7553529465": {"balance": 88888888, "inventory": {"dictor_common": 1}},
                },
                "banks": {
                    "6896326008": {
                        "name": "Доисторический VIP-банк",
                        "banker_id": 6896326008,
                        "banker_name": "🦖",
                        "co_bankers": [7081184095],
                        "capital": 22_000_000_000_000_000,
                        "deposit_rate": 13.0,
                        "oil_barrels": 2700,
                    },
                    "7553529465": {
                        "name": "Банк младшего диктора",
                        "banker_id": 7553529465,
                        "capital": 500_000_000,
                        "deposit_rate": 5.0,
                    },
                },
                "clans": {},
            }
        }
    }).encode("utf-8")
    pre_wipe_b64 = base64.b64encode(gzip.compress(pre_wipe_payload_raw)).decode("ascii")

    post_wipe_payload_raw = json.dumps({
        "version": 2,
        "chats": {"-1002321279920": {"users": {"6896326008": {"balance": 500, "inventory": {}}}, "banks": {}, "clans": {}}}
    }).encode("utf-8")
    post_wipe_b64 = base64.b64encode(gzip.compress(post_wipe_payload_raw)).decode("ascii")

    wipe_ts = 2000000000.0
    b_pre = MagicMock(id="backup_pre")
    b_pre.to_dict.return_value = {"timestamp": wipe_ts - 600, "payload": pre_wipe_b64}
    b_post = MagicMock(id="backup_post")
    b_post.to_dict.return_value = {"timestamp": wipe_ts + 60, "payload": post_wipe_b64}

    backups_col = MagicMock()
    backups_col.get = AsyncMock(return_value=[b_post, b_pre])

    saved_users = {}
    saved_banks = {}

    def _make_user_ref(uid):
        ref = MagicMock()
        cur = {"inventory": {"ny_gift": 1}} if uid == "6896326008" else {"inventory": {}}
        snap = MagicMock(exists=True)
        snap.to_dict.return_value = cur
        ref.get = AsyncMock(return_value=snap)
        async def _set(data, merge=False):
            saved_users.setdefault(uid, {}).update(data)
        ref.set = AsyncMock(side_effect=_set)
        return ref

    def _make_bank_ref(bid):
        ref = MagicMock()
        async def _set(data, merge=False):
            saved_banks[bid] = data
        ref.set = AsyncMock(side_effect=_set)
        return ref

    users_col = MagicMock()
    users_col.document.side_effect = _make_user_ref
    banks_col = MagicMock()
    banks_col.document.side_effect = _make_bank_ref

    chat_doc = MagicMock()
    chat_doc.collection.side_effect = lambda name: users_col if name == "users" else banks_col

    chats_col = MagicMock()
    chats_col.document.return_value = chat_doc

    ref_restore = MagicMock()
    ref_restore.get = AsyncMock(return_value=MagicMock(exists=False, to_dict=lambda: {}))
    ref_restore.set = AsyncMock()

    ref_ny = MagicMock()
    ref_ny.get = AsyncMock(return_value=MagicMock(exists=True, to_dict=lambda: {"sent": True, "timestamp": wipe_ts}))

    ref_done = MagicMock()
    ref_done.get = AsyncMock(return_value=MagicMock(exists=True, to_dict=lambda: {"sent": True}))

    def _sys_doc(name):
        if name == "restore_banks_and_dictors_v1":
            return ref_restore
        if name == "new_year_prep_reset_v1":
            return ref_ny
        return ref_done

    sys_col = MagicMock()
    sys_col.document.side_effect = _sys_doc

    mock_db = MagicMock()
    mock_db.collection.side_effect = lambda name: backups_col if name == "backups" else (sys_col if name == "system_actions" else chats_col)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch("db.get_db", return_value=mock_db):
        await creator.check_and_send_pending_actions(bot)

    # Both banks restored with capital reset to 1,000,000 (not 22 quintillion!)
    assert saved_banks["6896326008"]["capital"] == 1_000_000
    assert saved_banks["6896326008"]["oil_barrels"] == 2700
    assert saved_banks["7553529465"]["capital"] == 1_000_000
    assert saved_banks["7553529465"]["name"] == "Банк младшего диктора"

    # Dictors restored without wiping post-wipe items, chips NOT restored
    assert saved_users["6896326008"]["inventory"] == {"ny_gift": 1, "dictor_emperor": 2}
    assert saved_users["6896326008"]["is_banker"] is True
    assert saved_users["7081184095"]["co_banker_of"] == 6896326008
    assert saved_users["7553529465"]["inventory"] == {"dictor_common": 1}
    assert saved_users["7553529465"]["is_banker"] is True
    ref_restore.set.assert_awaited_once()
