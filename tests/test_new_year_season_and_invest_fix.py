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

    # Verify total user + bank + clan reset
    u1 = chat_doc.users._docs["u1"]
    assert u1["balance"] == 500
    assert u1["bank_deposit"] == 0
    assert u1["bank_name"] is None
    assert u1["is_banker"] is False
    assert u1["co_banker_of"] is None
    assert u1["inventory"] == {}
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
