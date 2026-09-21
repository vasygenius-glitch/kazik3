import pytest
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from seasons import (
    SEASON_TEMPLATES,
    execute_full_economy_wipe,
    perform_season_transition,
    get_season_config,
    apply_season_logic,
)
from chances import get_game_chance, get_user_win_chance, _chances_cache
from utils_pkg.cache_manager import global_cache


# ==============================================================================
#  1. COZY AUTUMN TEMPLATE TESTS
# ==============================================================================

def test_cozy_autumn_template_structure():
    assert "cozy_autumn" in SEASON_TEMPLATES
    ca = SEASON_TEMPLATES["cozy_autumn"]
    assert ca["id"] == "cozy_autumn"
    assert "УЮТНАЯ ОСЕНЬ" in ca["name"]
    assert ca["multiplier"] == 1.15
    assert ca["game_win_chance_boost"] == 10
    assert ca["glitch_chance"] == 0.0
    assert "strings" in ca
    assert "events" in ca
    assert len(ca["events"]) >= 3
    assert ca["strings"]["tax"] == "🍂 Листопадный сбор (Налог)"
    assert ca["strings"]["balance"] == "🍁 Осенние сыроежки (Баланс)"
    assert ca["strings"]["bonus"] == "☕ Горячий чай с корицей"
    assert "TEA" in ca["strings"]["stocks"]
    assert "PLD" in ca["strings"]["stocks"]


# ==============================================================================
#  2. CHANCES & WIN CHANCE BOOST TESTS (+10% Win Chance)
# ==============================================================================

@pytest.mark.asyncio
async def test_cozy_autumn_game_chance_boost(monkeypatch):
    _chances_cache.clear()

    async def mock_season_cfg():
        return {
            "active": True,
            "id": "cozy_autumn",
            "game_win_chance_boost": 10
        }

    monkeypatch.setattr("seasons.get_season_config", mock_season_cfg)
    monkeypatch.setattr("chances.get_db", lambda: None)

    chance = await get_game_chance("slots")
    # Base chance 35 + 10 = 45
    assert chance == 45


@pytest.mark.asyncio
async def test_cozy_autumn_user_win_chance_integration(monkeypatch):
    _chances_cache.clear()

    async def mock_season_cfg():
        return {
            "active": True,
            "id": "cozy_autumn",
            "game_win_chance_boost": 10
        }

    async def mock_get_user_data(chat_id, user_id):
        return {"balance": 1000, "prestige_level": 2, "pet": {}}

    monkeypatch.setattr("seasons.get_season_config", mock_season_cfg)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    monkeypatch.setattr("chances.get_db", lambda: None)

    # Base 35 + 10 (cozy autumn) + 10 (prestige level 2: 5 * 2) = 55
    win_chance = await get_user_win_chance(123, 456, "slots")
    assert win_chance == 55


# ==============================================================================
#  3. ECONOMY MEDIUM WIPE (BANKS PRESERVED, BALANCES & INVENTORY WIPED)
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
        self.ops = []


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


class FakeChatsCollection:
    def __init__(self):
        self.chats = {}

    def document(self, chat_id):
        cid = str(chat_id)
        if cid not in self.chats:
            self.chats[cid] = FakeChatDoc(cid)
        return self.chats[cid]


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


@pytest.mark.asyncio
async def test_execute_medium_wipe_preserves_banks_and_dictors(monkeypatch):
    fake_db = FakeDB()
    chat_doc = fake_db.collection("chats").document("100")

    chat_doc.users._docs["user1"] = {
        "balance": 999999,
        "bank_deposit": 500000,
        "bank_name": "CozyBank",
        "is_banker": True,
        "inventory": {
            "dictor_rare": 3,
            "chips": 50,
            "autumn_scarf": 1,
        }
    }
    chat_doc.clans._docs["clan1"] = {"name": "TopClan", "treasury": 1000000}
    chat_doc.banks._docs["bank1"] = {"name": "CozyBank", "capital": 5000000}

    monkeypatch.setattr("seasons.get_db", lambda: fake_db)
    monkeypatch.setattr("whitelist.get_whitelist", AsyncMock(return_value={"100": "Test Group"}))

    # Средний вайп: wipe_banks=False, preserve_dictors=True
    users_wiped, banks_wiped, clans_wiped = await execute_full_economy_wipe(preserve_dictors=True, wipe_banks=False)
    assert users_wiped == 1
    assert banks_wiped == 0
    assert clans_wiped == 0

    u1 = chat_doc.users._docs["user1"]
    # Баланс сброшен до 500
    assert u1["balance"] == 500
    # Банк и вклад НЕ тронуты!
    assert u1["bank_deposit"] == 500000
    assert u1["bank_name"] == "CozyBank"
    assert u1["is_banker"] is True
    # Дикторы сохранены, обычные предметы очищены
    assert u1["inventory"] == {"dictor_rare": 3}

    # Банк в коллекции остался
    assert "bank1" in chat_doc.banks._docs
    assert chat_doc.banks._docs["bank1"]["capital"] == 5000000

    # Клан остался
    assert chat_doc.clans._docs["clan1"]["treasury"] == 1000000


# ==============================================================================
#  4. SEASON TRANSITION TO COZY AUTUMN
# ==============================================================================

@pytest.mark.asyncio
async def test_perform_season_transition_cozy_autumn(monkeypatch):
    fake_db = FakeDB()
    bot = AsyncMock()

    monkeypatch.setattr("seasons.get_db", lambda: fake_db)
    monkeypatch.setattr("whitelist.get_whitelist", AsyncMock(return_value={"100": "Test Group"}))

    res = await perform_season_transition(bot, new_season_id="cozy_autumn", do_wipe=True, wipe_banks=False)
    assert res["status"] == "success"
    assert res["season"] == "cozy_autumn"

    season_doc = await fake_db.collection("bot_settings").document("season").get()
    s_data = season_doc.to_dict()
    assert s_data["id"] == "cozy_autumn"
    assert s_data["active"] is True
    assert s_data["multiplier"] == 1.15
    assert s_data["game_win_chance_boost"] == 10
