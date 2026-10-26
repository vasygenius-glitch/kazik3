import pytest
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from seasons import (
    SEASON_TEMPLATES,
    ANALOG_WORK_BOOSTS,
    execute_full_economy_wipe,
    perform_season_transition,
    get_season_config,
    apply_season_logic,
    cmd_vhs_spin,
    cmd_vhs_case,
    cmd_tape,
    execute_batch_vhs_case,
    VHS_CASE_PRICE,
)
from shop import ITEMS, CATEGORY_NAMES, CAT_KEYS, CAT_INDEX_MAP, INDEX_CAT_MAP, ITEM_ALIASES
from diseases import DISEASES, remove_disease
from chances import get_game_chance, get_user_win_chance, _chances_cache
from utils_pkg.cache_manager import global_cache


# ==============================================================================
#  1. ANALOG HORROR TEMPLATE & CONFIG TESTS
# ==============================================================================

def test_analog_horror_template_structure():
    assert "analog_horror" in SEASON_TEMPLATES
    ah = SEASON_TEMPLATES["analog_horror"]
    assert ah["id"] == "analog_horror"
    assert "АНАЛОГОВЫЙ ХОРРОР" in ah["name"]
    assert ah["multiplier"] == 1.20
    assert ah["game_win_chance_boost"] == 5
    assert ah["glitch_chance"] == 0.08

    # Валюта строго сыроежки, как запросил пользователь ("сыроежки и валюту не меняй верни старое")
    assert ah["strings"]["balance"] == "💰 Сыроежки (Баланс)"
    assert ah["strings"]["tax"] == "📼 Эфирный сбор (Налог)"
    assert ah["strings"]["shop"] == "📺 Магазин Аналоговой Электроники"
    assert ah["strings"]["work"] == "📻 Перехват аналогового сигнала"
    assert ah["strings"]["crime"] == "📼 Взлом телеэфира"

    assert "VHS" in ah["strings"]["stocks"]
    assert "CRT" in ah["strings"]["stocks"]

    assert ah["seasonal_disease"]["id"] == "vhs_syndrome"
    assert len(ah["events"]) >= 4


# ==============================================================================
#  2. SHOP & ITEMS VERIFICATION
# ==============================================================================

def test_shop_analog_category_and_items():
    assert "analog" in CATEGORY_NAMES
    assert "analog" in CAT_KEYS
    assert CAT_INDEX_MAP["analog"] == 5
    assert INDEX_CAT_MAP[5] == "analog"

    expected_items = [
        "vhs_tape",
        "vhs_player",
        "crt_tv",
        "anomaly_radio",
        "hi8_camera",
        "forbidden_tape",
    ]
    for it_id in expected_items:
        assert it_id in ITEMS
        assert ITEMS[it_id]["cat"] == "analog"
        assert ITEMS[it_id]["price"] > 0

    # Aliases
    assert ITEM_ALIASES.get("кассета") == "vhs_tape"
    assert ITEM_ALIASES.get("vhs") == "vhs_tape"
    assert ITEM_ALIASES.get("видик") == "vhs_player"
    assert ITEM_ALIASES.get("телик") == "crt_tv"
    assert ITEM_ALIASES.get("радио") == "anomaly_radio"
    assert ITEM_ALIASES.get("камера") == "hi8_camera"
    assert ITEM_ALIASES.get("forbidden_tape") == "forbidden_tape"


# ==============================================================================
#  3. DISEASES VERIFICATION
# ==============================================================================

def test_analog_horror_disease_defined():
    assert "vhs_syndrome" in DISEASES
    assert "Аналоговый синдром" in DISEASES["vhs_syndrome"]["name"]
    assert "autumn_blues" in DISEASES


@pytest.mark.asyncio
async def test_remove_disease_helper(monkeypatch):
    user_state = {"diseases": {"vhs_syndrome": time.time() + 1000, "hiv": time.time() + 500}}

    async def mock_get_user_data(chat_id, user_id):
        return user_state

    async def mock_update_user_field(chat_id, user_id, field, val):
        user_state[field] = val

    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    monkeypatch.setattr("user_manager.update_user_field", mock_update_user_field)

    res = await remove_disease(123, 456, "vhs_syndrome")
    assert res is True
    assert "vhs_syndrome" not in user_state["diseases"]
    assert "hiv" in user_state["diseases"]

    # Trying to remove again returns False
    res2 = await remove_disease(123, 456, "vhs_syndrome")
    assert res2 is False


# ==============================================================================
#  4. WORK SPECIAL ITEMS BOOST IN apply_season_logic
# ==============================================================================

@pytest.mark.asyncio
async def test_apply_season_logic_analog_no_items(monkeypatch):
    async def mock_cfg():
        return {
            "active": True,
            "id": "analog_horror",
            "multiplier": 1.20,
            "glitch_chance": 0.0,
            "events": []
        }

    async def mock_get_user_data(chat_id, user_id):
        return {"inventory": {}}

    monkeypatch.setattr("seasons.get_season_config", mock_cfg)
    monkeypatch.setattr("seasons.get_user_data", mock_get_user_data)
    monkeypatch.setattr("random.random", lambda: 0.99)  # no events, no drops

    final_val, msg = await apply_season_logic(100, 200, 1000)
    # Base 1000 * 1.20 = 1200
    assert final_val == 1200
    assert "АНАЛОГОВЫЙ БУСТ" not in msg


@pytest.mark.asyncio
async def test_apply_season_logic_analog_with_items_boost(monkeypatch):
    async def mock_cfg():
        return {
            "active": True,
            "id": "analog_horror",
            "multiplier": 1.20,
            "glitch_chance": 0.0,
            "events": []
        }

    # User owns vhs_tape (+15%) and crt_tv (+25%) -> Total +40%
    async def mock_get_user_data(chat_id, user_id):
        return {"inventory": {"vhs_tape": 1, "crt_tv": 1}}

    monkeypatch.setattr("seasons.get_season_config", mock_cfg)
    monkeypatch.setattr("seasons.get_user_data", mock_get_user_data)
    monkeypatch.setattr("random.random", lambda: 0.99)  # no random drops

    final_val, msg = await apply_season_logic(100, 200, 1000)
    # Base value = 1000 * 1.20 (season mult) = 1200
    # Extra boost = 1000 * (0.15 + 0.25) = 400
    # Final = 1200 + 400 = 1600
    assert final_val == 1600
    assert "АНАЛОГОВЫЙ БУСТ ОБОРУДОВАНИЯ (+40%)" in msg
    assert "Плёнка VHS" in msg
    assert "ЭЛТ-телевизор «Рубин»" in msg


@pytest.mark.asyncio
async def test_apply_season_logic_all_analog_equipment_boost(monkeypatch):
    async def mock_cfg():
        return {
            "active": True,
            "id": "analog_horror",
            "multiplier": 1.20,
            "glitch_chance": 0.0,
            "events": []
        }

    # User owns ALL 6 items: 15% + 20% + 25% + 30% + 35% + 50% = +175%
    async def mock_get_user_data(chat_id, user_id):
        return {
            "inventory": {
                "vhs_tape": 2,
                "vhs_player": 1,
                "crt_tv": 1,
                "anomaly_radio": 1,
                "hi8_camera": 1,
                "forbidden_tape": 1,
            }
        }

    monkeypatch.setattr("seasons.get_season_config", mock_cfg)
    monkeypatch.setattr("seasons.get_user_data", mock_get_user_data)
    monkeypatch.setattr("random.random", lambda: 0.99)

    final_val, msg = await apply_season_logic(100, 200, 1000)
    # 1200 (base season) + 1750 (175% of 1000) = 2950
    assert final_val == 2950
    assert "+175%" in msg


# ==============================================================================
#  5. COMMANDS (/vhs_spin, /vhs_case, /tape)
# ==============================================================================

@pytest.mark.asyncio
async def test_cmd_vhs_spin(monkeypatch):
    user_state = {"balance": 10000, "is_banned": False}

    async def mock_cfg():
        return {"active": True, "id": "analog_horror"}

    async def mock_get_user_data(chat_id, user_id):
        return user_state

    async def mock_update_user_balance(chat_id, user_id, amount, action=""):
        user_state["balance"] += amount

    monkeypatch.setattr("seasons.get_season_config", mock_cfg)
    monkeypatch.setattr("seasons.get_user_data", mock_get_user_data)
    monkeypatch.setattr("seasons.update_user_balance", mock_update_user_balance)
    monkeypatch.setattr("random.random", lambda: 0.99)  # 5x jackpot!
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    message = AsyncMock()
    message.chat.id = 111
    message.from_user.id = 222
    message.text = "/vhs_spin 1000"
    status_msg = AsyncMock()
    message.answer = AsyncMock(return_value=status_msg)

    await cmd_vhs_spin(message)

    # 10000 - 1000 + 5000 = 14000
    assert user_state["balance"] == 14000
    status_msg.edit_text.assert_called_once()
    assert "ИСТИННЫЙ АНАЛОГОВЫЙ СИГНАЛ" in status_msg.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_tape(monkeypatch):
    user_state = {
        "balance": 5000,
        "is_banned": False,
        "last_tape_time": 0,
        "diseases": {"vhs_syndrome": time.time() + 1000}
    }

    async def mock_cfg():
        return {"active": True, "id": "analog_horror"}

    async def mock_get_user_data(chat_id, user_id):
        return user_state

    async def mock_update_user_balance(chat_id, user_id, amount, action=""):
        user_state["balance"] += amount

    async def mock_update_user_field(chat_id, user_id, field, val):
        user_state[field] = val

    monkeypatch.setattr("seasons.get_season_config", mock_cfg)
    monkeypatch.setattr("seasons.get_user_data", mock_get_user_data)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    monkeypatch.setattr("seasons.update_user_balance", mock_update_user_balance)
    monkeypatch.setattr("seasons.update_user_field", mock_update_user_field)
    monkeypatch.setattr("user_manager.update_user_field", mock_update_user_field)

    message = AsyncMock()
    message.chat.id = 111
    message.from_user.id = 222
    message.answer = AsyncMock()

    await cmd_tape(message)

    assert user_state["balance"] > 5000
    assert user_state["last_tape_time"] > 0
    # VHS syndrome cured!
    assert "vhs_syndrome" not in user_state.get("diseases", {})
    message.answer.assert_called_once()
    assert "ПРОСМОТР АНАЛОГОВОЙ ЗАПИСИ" in message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_vhs_case_execution(monkeypatch):
    user_state = {"balance": 50000, "inventory": {}}

    async def mock_get_user_data(chat_id, user_id):
        return user_state

    async def mock_update_user_balance(chat_id, user_id, amount, action=""):
        user_state["balance"] += amount

    async def mock_add_item_to_inventory(chat_id, user_id, item_id, count=1):
        user_state["inventory"][item_id] = user_state["inventory"].get(item_id, 0) + count
        return True

    monkeypatch.setattr("seasons.get_user_data", mock_get_user_data)
    monkeypatch.setattr("seasons.update_user_balance", mock_update_user_balance)
    monkeypatch.setattr("user_manager.add_item_to_inventory", mock_add_item_to_inventory)

    status_msg = AsyncMock()
    await execute_batch_vhs_case(111, 222, count=2, msg=status_msg)

    # Cost: 2 * 15000 = 30000. Balance was 50000 -> + cash drops
    assert user_state["balance"] > 10000
    # Two items awarded to inventory
    total_items = sum(user_state["inventory"].values())
    assert total_items == 2


# ==============================================================================
#  6. SEASON TRANSITION TO ANALOG HORROR
# ==============================================================================

class FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class FakeCollection:
    def __init__(self, docs=None):
        self._docs = docs or {}

    async def get(self):
        return [FakeDoc(k, v) for k, v in self._docs.items()]

    def document(self, name):
        return FakeDocRef(self, str(name))


class FakeDocRef:
    def __init__(self, col, doc_id):
        self.col = col
        self.doc_id = doc_id

    async def set(self, data, merge=False):
        if merge and self.doc_id in self.col._docs:
            self.col._docs[self.doc_id].update(data)
        else:
            self.col._docs[self.doc_id] = data

    async def delete(self):
        self.col._docs.pop(self.doc_id, None)

    async def get(self):
        d = self.col._docs.get(self.doc_id, {})
        class DocRes:
            exists = bool(d)
            def to_dict(self_inner): return d
        return DocRes()


class FakeBatch:
    def __init__(self):
        self.ops = []

    def set(self, doc_ref, data, merge=False):
        self.ops.append((doc_ref, data, merge))

    async def commit(self):
        for ref, data, merge in self.ops:
            await ref.set(data, merge=merge)
        self.ops.clear()


class FakeChatDoc:
    def __init__(self, cid):
        self.cid = cid
        self.users = FakeCollection()
        self.clans = FakeCollection()
        self.banks = FakeCollection()

    def collection(self, name):
        if name == "users":
            return self.users
        elif name == "clans":
            return self.clans
        elif name == "banks":
            return self.banks
        return FakeCollection()


class FakeChatsCollection:
    def __init__(self):
        self.chats = {}

    def document(self, chat_id):
        cid = str(chat_id)
        if cid not in self.chats:
            self.chats[cid] = FakeChatDoc(cid)
        return self.chats[cid]

    async def get(self):
        return [FakeDoc(cid, {}) for cid in self.chats]


class FakeDB:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        if name not in self.collections:
            if name == "chats":
                self.collections[name] = FakeChatsCollection()
            else:
                self.collections[name] = FakeCollection()
        return self.collections[name]

    def batch(self):
        return FakeBatch()


@pytest.mark.asyncio
async def test_perform_season_transition_analog_horror(monkeypatch):
    fake_db = FakeDB()
    bot = AsyncMock()

    # Pre-populate chat, user, bank
    chat_doc = fake_db.collection("chats").document("999")
    chat_doc.users._docs["u1"] = {
        "balance": 888888,
        "bank_deposit": 300000,
        "bank_name": "TestDinoBank",
        "is_banker": True,
        "inventory": {"dictor_supernova": 1, "chips": 100}
    }
    chat_doc.banks._docs["bank1"] = {"name": "TestDinoBank", "capital": 10000000}

    monkeypatch.setattr("seasons.get_db", lambda: fake_db)
    monkeypatch.setattr("whitelist.get_whitelist", AsyncMock(return_value={"999": "Test Group"}))

    # Perform transition to analog_horror (wipe_banks defaults to False!)
    res = await perform_season_transition(bot, new_season_id="analog_horror", do_wipe=True)
    assert res["status"] == "success"
    assert res["season"] == "analog_horror"
    assert res["banks_wiped"] == 0

    season_doc = await fake_db.collection("bot_settings").document("season").get()
    s_data = season_doc.to_dict()
    assert s_data["id"] == "analog_horror"
    assert s_data["active"] is True
    assert s_data["multiplier"] == 1.20
    assert s_data["game_win_chance_boost"] == 5
    # Currency stays standard сыроежки
    assert s_data["strings"]["balance"] == "💰 Сыроежки (Баланс)"

    # Check that bank survived and user's dictor survived
    u1 = chat_doc.users._docs["u1"]
    assert u1["balance"] == 500
    assert u1["bank_deposit"] == 300000
    assert u1["bank_name"] == "TestDinoBank"
    assert u1["inventory"] == {"dictor_supernova": 1}
    assert "bank1" in chat_doc.banks._docs
