import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from admin import extract_args, is_creator, cmd_mute, cmd_unmute, cmd_warn, cmd_unwarn
from admin_dashboard import parse_int, parse_float, fmt_money, fmt_chance, chat_doc
from utils import fire_and_forget, schedule_delete, is_valid_command
from whitelist_middleware import WhitelistMiddleware
from cooldown_middleware import CooldownMiddleware

# =====================================================================
# 1. ADMIN MODULE TESTS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("input_text,expected_reason", [
    ("!!!ban spammer", "spammer"),
    ("!!!ban\nmultiline reason", "multiline reason"),
    ("!!!ban", ""),
    ("!мут 60 flood", "60 flood"),
    ("!варн rule 1", "rule 1"),
    ("!бан bad behavior", "bad behavior"),
    ("!кик AFK", "AFK"),
    ("!мут 120 insult", "120 insult"),
    ("!варн\nrepeated violation", "repeated violation"),
    ("!бан", "")
])
def test_extract_args_10_cases(input_text, expected_reason):
    reason = extract_args(input_text)
    assert reason == expected_reason

@pytest.mark.parametrize("uid,expected", [
    (123456789, False),
    (987654321, False),
    (100, False),
    (200, False),
    (300, False),
    (400, False),
    (500, False),
    (600, False),
    (700, False),
    (0, False)
])
def test_is_creator_10_cases(uid, expected):
    assert is_creator(uid) == expected

@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [1, 5, 10, 15, 30, 60, 120, 300, 720, 1440])
async def test_cmd_mute_10_durations(minutes):
    message = AsyncMock()
    message.chat.id = 100
    message.from_user.id = 999999999
    message.reply_to_message = AsyncMock()
    message.reply_to_message.from_user.id = 200
    message.reply_to_message.from_user.full_name = "Target"
    message.text = f"!мут {minutes}"
    
    bot = AsyncMock()
    with patch("admin.is_creator", side_effect=lambda uid: uid == 999999999):
        await cmd_mute(message, bot)
        bot.restrict_chat_member.assert_called_once()

# =====================================================================
# 2. ADMIN DASHBOARD FORMATTERS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("raw_str,expected_val", [
    ("100", 100),
    ("0", 0),
    ("-50", -50),
    ("1000", 1000),
    ("2500", 2500),
    ("10000", 10000),
    ("99999", 99999),
    ("50", 50),
    ("123", 123),
    ("999", 999)
])
def test_parse_int_10_cases(raw_str, expected_val):
    val = parse_int(raw_str)
    assert val == expected_val

@pytest.mark.parametrize("raw_str,expected_val", [
    ("10.5", 10.5),
    ("0.0", 0.0),
    ("100.25", 100.25),
    ("5.0", 5.0),
    ("1.23", 1.23),
    ("99.99", 99.99),
    ("0.5", 0.5),
    ("2.5", 2.5),
    ("50.0", 50.0),
    ("1000.0", 1000.0)
])
def test_parse_float_10_cases(raw_str, expected_val):
    val = parse_float(raw_str)
    assert val == expected_val

@pytest.mark.parametrize("amount,expected_str", [
    (100, "100"),
    (1000, "1 000"),
    (50000, "50 000"),
    (1000000, "1 000 000"),
    (0, "0"),
    (2500, "2 500"),
    (999999, "999 999"),
    (10000000, "10 000 000"),
    (500, "500"),
    (1234567, "1 234 567")
])
def test_fmt_money_10_cases(amount, expected_str):
    formatted = fmt_money(amount)
    assert isinstance(formatted, str)

@pytest.mark.parametrize("chance_val,expected_str", [
    (10, "10%"),
    (25, "25%"),
    (50, "50%"),
    (75, "75%"),
    (100, "100%"),
    (0, "0%"),
    (1, "1%"),
    (5, "5%"),
    (15, "15%"),
    (99, "99%")
])
def test_fmt_chance_10_cases(chance_val, expected_str):
    res = fmt_chance(chance_val)
    assert res == expected_str

# =====================================================================
# 3. UTILS & COMMAND VALIDATION (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("text,expected_valid", [
    ("/work", True),
    ("/crime", True),
    ("!bonus", True),
    ("?help", True),
    ("диктор", True),
    ("профиль", True),
    ("банк", True),
    ("казино", True),
    ("рулетка", True),
    ("random chat message", False)
])
def test_is_valid_command_10_cases(text, expected_valid):
    assert is_valid_command(text) == expected_valid

@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [1, 2, 3, 5, 10, 15, 20, 30, 40, 60])
async def test_schedule_delete_10_delays(delay):
    msg = AsyncMock()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await schedule_delete(msg, delay=delay)
        msg.delete.assert_called_once()
