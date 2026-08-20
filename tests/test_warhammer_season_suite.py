import pytest
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from seasons import (
    SEASON_TEMPLATES,
    execute_full_economy_wipe,
    perform_season_transition,
    season_rotator_task,
    get_season_config,
    _default_crypto_coins,
)
from chances import get_game_chance, get_user_win_chance, _chances_cache
from utils_pkg.cache_manager import global_cache


# ==============================================================================
#  1. WARHAMMER SEASON TEMPLATE TESTS
# ==============================================================================

def test_warhammer_template_structure():
    assert "warhammer" in SEASON_TEMPLATES
    wh = SEASON_TEMPLATES["warhammer"]
    assert wh["id"] == "warhammer"
    assert "ВАРХАММЕР" in wh["name"]
    assert wh["multiplier"] == 1.0
    assert wh["game_win_chance_boost"] == 15
    assert wh["glitch_chance"] == 0.0
    assert "strings" in wh
    assert "events" in wh
    assert len(wh["events"]) >= 3
    assert wh["strings"]["tax"] == "🦅 Имперская десятина (Налог)"
    assert wh["strings"]["balance"] == "🪙 Имперские кредиты (Баланс)"


# ==============================================================================
#  2. CHANCES & LUCK BONUS TESTS (+15% Win Chance)
# ==============================================================================

@pytest.mark.asyncio
async def test_warhammer_game_chance_boost_default_random(monkeypatch):
    _chances_cache.clear()
    
    async def mock_season_cfg():
        return {
            "active": True,
            "id": "warhammer",
            "game_win_chance_boost": 15
        }
    
    monkeypatch.setattr("seasons.get_season_config", mock_season_cfg)
    monkeypatch.setattr("chances.get_db", lambda: None)
    
    chance = await get_game_chance("slots")
    # Base chance 35 + 15 = 50
    assert chance == 50


@pytest.mark.asyncio
async def test_warhammer_game_chance_boost_custom_chance(monkeypatch):
    _chances_cache["slots"] = 40
    
    async def mock_season_cfg():
        return {
            "active": True,
            "id": "warhammer",
            "game_win_chance_boost": 15
        }
    
    monkeypatch.setattr("seasons.get_season_config", mock_season_cfg)
    monkeypatch.setattr("chances.get_db", lambda: None)
    
    chance = await get_game_chance("slots")
    # Custom chance 40 + 15 = 55
    assert chance == 55


@pytest.mark.asyncio
async def test_warhammer_user_win_chance_integration(monkeypatch):
    _chances_cache.clear()
    
    async def mock_season_cfg():
        return {
            "active": True,
            "id": "warhammer",
            "game_win_chance_boost": 15
        }
    
    async def mock_get_user_data(chat_id, user_id):
        return {"balance": 1000, "prestige_level": 1, "pet": {}}
    
    monkeypatch.setattr("seasons.get_season_config", mock_season_cfg)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    monkeypatch.setattr("chances.get_db", lambda: None)
    
    # Base 35 + 15 (warhammer) + 5 (prestige level 1) = 55
    win_chance = await get_user_win_chance(123, 456, "slots")
    assert win_chance == 55


# ==============================================================================
#  3. ECONOMY WIPE & DICTOR PRESERVATION TESTS
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
        self.data = {}

    async def set(self, data, merge=False):
        if merge and self.doc_id in self.col._docs:
            self.col._docs[self.doc_id].update(data)
        else:
            self.col._docs[self.doc_id] = data

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

    def collection(self, name):
        if name == "users":
            return self.users
        elif name == "clans":
            return self.clans
        return FakeCollection()


@pytest.mark.asyncio
async def test_execute_full_economy_wipe_preserves_dictors(monkeypatch):
    fake_db = FakeDB()
    chat_doc = fake_db.collection("chats").document("100")
    
    # 2 users: one with dictors and regular items, one plain
    chat_doc.users._docs["user1"] = {
        "balance": 500000,
        "bank_deposit": 200000,
        "debts": {"creditor": 5000},
        "skills": {"mining": 5},
        "pet": {"id": "cat"},
        "inventory": {
            "dictor_rare": 2,
            "dictor_legendary": 1,
            "beer": 10,
            "sword": 1,
        }
    }
    chat_doc.users._docs["user2"] = {
        "balance": 100000,
        "bank_deposit": 50000,
        "inventory": {"chips": 5}
    }
    chat_doc.clans._docs["clan1"] = {"name": "TopClan", "treasury": 1000000}

    monkeypatch.setattr("seasons.get_db", lambda: fake_db)
    monkeypatch.setattr("whitelist.get_whitelist", AsyncMock(return_value={"100": "Test Group"}))

    users_wiped, clans_wiped = await execute_full_economy_wipe(preserve_dictors=True)
    assert users_wiped == 2
    assert clans_wiped == 1

    u1 = chat_doc.users._docs["user1"]
    assert u1["balance"] == 500
    assert u1["bank_deposit"] == 0
    assert u1["debts"] == {}
    assert u1["skills"] == {}
    assert u1["pet"] is None
    # Dictors preserved, regular items wiped
    assert u1["inventory"] == {"dictor_rare": 2, "dictor_legendary": 1}

    u2 = chat_doc.users._docs["user2"]
    assert u2["balance"] == 500
    assert u2["bank_deposit"] == 0
    assert u2["inventory"] == {}

    c1 = chat_doc.clans._docs["clan1"]
    assert c1["treasury"] == 0


# ==============================================================================
#  4. SEASON TRANSITION & ONE-TIME WIPE TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_perform_season_transition_success(monkeypatch):
    fake_db = FakeDB()
    bot = AsyncMock()

    monkeypatch.setattr("seasons.get_db", lambda: fake_db)
    monkeypatch.setattr("whitelist.get_whitelist", AsyncMock(return_value={"100": "Test Group"}))

    res = await perform_season_transition(bot, new_season_id="warhammer", do_wipe=True)
    assert res["status"] == "success"
    assert res["season"] == "warhammer"

    season_doc = await fake_db.collection("bot_settings").document("season").get()
    s_data = season_doc.to_dict()
    assert s_data["id"] == "warhammer"
    assert s_data["active"] is True
    assert s_data["last_wiped_season"] == "warhammer"

    # Testing idempotency: second call returns already_executed
    res_second = await perform_season_transition(bot, new_season_id="warhammer", do_wipe=True)
    assert res_second["status"] == "already_executed"


# ==============================================================================
#  5. ROTATOR BACKGROUND TASK TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_season_rotator_task_triggers_on_expired_timer(monkeypatch):
    bot = AsyncMock()

    now = int(time.time())
    # Current active season 3 (tayniy_baniy) with expired timer
    expired_cfg = {
        "active": True,
        "id": "tayniy_baniy",
        "end_time": now - 100, # expired
    }

    async def mock_get_season_config():
        return expired_cfg

    transition_called = []
    async def mock_perform_transition(bot_arg, new_season_id="warhammer", do_wipe=True):
        transition_called.append((new_season_id, do_wipe))
        return {"status": "success", "season": new_season_id}

    monkeypatch.setattr("seasons.get_season_config", mock_get_season_config)
    monkeypatch.setattr("seasons.perform_season_transition", mock_perform_transition)
    
    sleep_count = 0
    async def mock_sleep(seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count > 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr("seasons.asyncio.sleep", mock_sleep)

    try:
        await season_rotator_task(bot)
    except asyncio.CancelledError:
        pass

    assert len(transition_called) >= 1
    assert transition_called[0] == ("warhammer", True)
