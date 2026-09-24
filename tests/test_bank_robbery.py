import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from economy import cmd_rob_bank, MAX_BANK_ROB_LOOT, BANK_ROB_IMMUNITY_TIME, ROB_BANK_COOLDOWN


@pytest.mark.asyncio
async def test_rob_own_bank_blocked(monkeypatch):
    message = AsyncMock()
    message.chat.id = 123
    message.from_user.id = 456
    message.from_user.full_name = "Banker Bob"
    message.text = "ограбить банк MyBank"

    async def mock_get_user_data(cid, uid, name):
        return {"balance": 1000, "is_banker": False, "is_banned": False}

    async def mock_get_bank_info(cid, name):
        return {"name": "MyBank", "banker_id": 456, "capital": 1_000_000_000}

    monkeypatch.setattr("economy.get_user_data", mock_get_user_data)
    monkeypatch.setattr("profile_bank.get_bank_info", mock_get_bank_info)

    await cmd_rob_bank(message)
    message.answer.assert_called_once()
    assert "собственный банк" in message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_rob_bank_immunity_cooldown(monkeypatch):
    message = AsyncMock()
    message.chat.id = 123
    message.from_user.id = 789
    message.from_user.full_name = "Robber"
    message.text = "ограбить банк TargetBank"

    now = 1000000
    async def mock_get_user_data(cid, uid, name):
        return {"balance": 1000, "is_banker": False, "is_banned": False, "last_bank_rob_time": 0}

    async def mock_get_bank_info(cid, name):
        # Was robbed 1 hour ago (within 4-hour immunity)
        return {"name": "TargetBank", "banker_id": 456, "capital": 100_000_000, "last_robbed_time": now - 3600}

    monkeypatch.setattr("time.time", lambda: now)
    monkeypatch.setattr("economy.get_user_data", mock_get_user_data)
    monkeypatch.setattr("profile_bank.get_bank_info", mock_get_bank_info)

    await cmd_rob_bank(message)
    message.answer.assert_called_once()
    assert "СИСТЕМА БЕЗОПАСНОСТИ АКТИВИРОВАНА" in message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_rob_bank_loot_cap_and_security_integration(monkeypatch):
    message = AsyncMock()
    message.chat.id = 123
    message.from_user.id = 789
    message.from_user.full_name = "Robber"
    message.text = "ограбить банк HugeBank"

    now = 1000000
    # Bank has 500 BILLION capital!
    huge_capital = 500_000_000_000

    async def mock_get_user_data(cid, uid, name):
        return {
            "balance": 10000,
            "is_banker": False,
            "is_banned": False,
            "last_bank_rob_time": 0,
            "skills": {"stealth": 5}
        }

    async def mock_get_bank_info(cid, name):
        return {
            "name": "HugeBank",
            "banker_id": 456,
            "capital": huge_capital,
            "last_robbed_time": 0,
            "upgrade_security": 5
        }

    updated_bank = []
    async def mock_create_or_update_bank(cid, bid, data):
        updated_bank.append((bid, data))

    updated_balances = []
    async def mock_update_user_balance(cid, uid, amount, **kwargs):
        updated_balances.append((uid, amount))

    monkeypatch.setattr("time.time", lambda: now)
    monkeypatch.setattr("economy.get_user_data", mock_get_user_data)
    monkeypatch.setattr("profile_bank.get_bank_info", mock_get_bank_info)
    monkeypatch.setattr("profile_bank.create_or_update_bank", mock_create_or_update_bank)
    monkeypatch.setattr("economy.update_user_balance", mock_update_user_balance)
    monkeypatch.setattr("economy.update_user_field", AsyncMock())

    # Force success by mocking random() to 0.0001 (less than success_chance)
    with patch("secrets.SystemRandom.random", return_value=0.0001):
        await cmd_rob_bank(message)

    message.answer.assert_called_once()
    assert "НЕВЕРОЯТНОЕ ОГРАБЛЕНИЕ ВЕКА" in message.answer.call_args[0][0]

    # Stolen amount MUST be capped at MAX_BANK_ROB_LOOT (15_000_000)
    assert len(updated_balances) == 1
    stolen_amount = updated_balances[0][1]
    assert stolen_amount <= MAX_BANK_ROB_LOOT
    assert stolen_amount > 0


@pytest.mark.asyncio
async def test_rob_bank_failure_applies_fine_and_mute(monkeypatch):
    message = AsyncMock()
    message.chat.id = 123
    message.from_user.id = 789
    message.from_user.full_name = "Robber"
    message.text = "ограбить банк HugeBank"

    now = 1000000
    async def mock_get_user_data(cid, uid, name):
        return {
            "balance": 10_000_000,
            "is_banker": False,
            "is_banned": False,
            "last_bank_rob_time": 0,
            "skills": {"stealth": 0}
        }

    async def mock_get_bank_info(cid, name):
        return {
            "name": "HugeBank",
            "banker_id": 456,
            "capital": 10_000_000,
            "last_robbed_time": 0,
            "upgrade_security": 3
        }

    updated_balances = []
    async def mock_update_user_balance(cid, uid, amount, **kwargs):
        updated_balances.append((uid, amount))

    monkeypatch.setattr("time.time", lambda: now)
    monkeypatch.setattr("economy.get_user_data", mock_get_user_data)
    monkeypatch.setattr("profile_bank.get_bank_info", mock_get_bank_info)
    monkeypatch.setattr("profile_bank.create_or_update_bank", AsyncMock())
    monkeypatch.setattr("economy.update_user_balance", mock_update_user_balance)
    monkeypatch.setattr("economy.update_user_field", AsyncMock())

    # Force failure by mocking random() to 0.99
    with patch("secrets.SystemRandom.random", return_value=0.99):
        await cmd_rob_bank(message)

    message.answer.assert_called_once()
    assert "ОБЛАВА И ПРОВАЛ ОГРАБЛЕНИЯ" in message.answer.call_args[0][0]

    # Penalty should be 10% of balance (1_000_000)
    assert len(updated_balances) == 1
    penalty = updated_balances[0][1]
    assert penalty == -1_000_000
    message.bot.restrict_chat_member.assert_called_once()
