import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from diseases import DISEASES, get_active_diseases, infect_user, infect_full_house, cmd_std, cmd_heal
from rp_clans import cmd_clan, cmd_marry, cmd_divorce, cmd_duel
from court import cmd_sue, cmd_judge, set_chat_judge, get_chat_judge
from escort import cmd_top_escort

# =====================================================================
# 1. DISEASES MODULE TESTS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("disease_key", ["hiv", "syphilis", "gonorrhea", "chlamydia", "herpes", "hpv", "lice", "trichomoniasis", "hepatitis", "aids"])
def test_diseases_dict_10_diseases(disease_key):
    assert disease_key in DISEASES
    d_info = DISEASES[disease_key]
    assert "name" in d_info
    assert "desc" in d_info

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_get_active_diseases_empty(idx):
    user_data = {"diseases": {}}
    with patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("diseases.is_top_1_hooker", new_callable=AsyncMock, return_value=False):
        active = await get_active_diseases(100, 200 + idx)
        assert len(active) == 0

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_infect_full_house_10_runs(idx):
    user_data = {"diseases": {}}
    with patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("user_manager.update_user_field", new_callable=AsyncMock):
        infected = await infect_full_house(100, 300 + idx)
        assert len(infected) == len(DISEASES)

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_std_healthy(idx):
    message = AsyncMock()
    message.chat.id = 500 + idx
    message.from_user.id = 600 + idx
    message.from_user.full_name = f"HealthyPlayer_{idx}"
    message.text = "/зппп"
    
    user_data = {"diseases": {}}
    with patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("diseases.is_top_1_hooker", new_callable=AsyncMock, return_value=False):
        await cmd_std(message)
        message.answer.assert_called_once()

# =====================================================================
# 2. CLANS & COURT & ESCORT (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_clan_view(idx):
    message = AsyncMock()
    message.chat.id = 1000 + idx
    message.from_user.id = 2000 + idx
    message.text = "/clan"
    
    user_data = {"clan_id": "clan_1", "balance": 5000}
    with patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("rp_clans.get_clan_ref"):
        await cmd_clan(message)
        message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_sue_cases(idx):
    message = AsyncMock()
    message.chat.id = 1500 + idx
    message.from_user.id = 2500 + idx
    message.from_user.full_name = f"Plaintiff_{idx}"
    message.reply_to_message = AsyncMock()
    message.reply_to_message.from_user.id = 3500 + idx
    message.reply_to_message.from_user.full_name = f"Defendant_{idx}"
    message.reply_to_message.from_user.is_bot = False
    message.text = f"подать иск Причина №{idx}"
    
    await cmd_sue(message)
    message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_top_escort_view(idx):
    message = AsyncMock()
    message.chat.id = 3000 + idx
    message.from_user.id = 4000 + idx
    message.text = "/top_escort"
    
    with patch("escort.get_db"):
        await cmd_top_escort(message)
        message.answer.assert_called_once()
