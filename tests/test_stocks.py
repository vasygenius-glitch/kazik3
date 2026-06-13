import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_get_stocks_db_injects_ticker():
    # Mock database
    mock_db = MagicMock()
    mock_doc = MagicMock() # Use MagicMock for the document result
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        'prices': {
            'chzp': [1000],
            'MWTR': [2000],
        },
        'news': 'Test news'
    }
    
    # get() must be an AsyncMock that returns mock_doc
    mock_get = AsyncMock(return_value=mock_doc)
    mock_db.collection.return_value.document.return_value.get = mock_get
    
    # Mock season config returning stocks without 'ticker'
    mock_season_config = {
        "active": True,
        "strings": {
            "stocks": {
                "MWTR": {"name": "MandelWater Inc (MWTR)", "desc": "Главный поставщик миндальной воды в Закулисье."},
            }
        }
    }
    
    with patch('stocks.get_db', return_value=mock_db), \
         patch('seasons.get_season_config', return_value=mock_season_config):
         
         import stocks
         data, ALL_COMPANIES = await stocks.get_stocks_db()
         
         assert "MWTR" in ALL_COMPANIES
         assert ALL_COMPANIES["MWTR"]["ticker"] == "MWTR"
         assert ALL_COMPANIES["chzp"]["ticker"] == "CHZP"

@pytest.mark.asyncio
async def test_update_stocks_task_no_keyerror():
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        'prices': {
            'chzp': [1000],
            'MWTR': [2000],
        },
        'news': 'Test news'
    }
    
    mock_get = AsyncMock(return_value=mock_doc)
    mock_db.collection.return_value.document.return_value.get = mock_get
    
    mock_season_config = {
        "active": True,
        "strings": {
            "stocks": {
                "MWTR": {"name": "MandelWater Inc (MWTR)", "desc": "Главный поставщик миндальной воды в Закулисье."},
            }
        }
    }
    
    # We patch asyncio.sleep to raise a CancelledError to break the infinite loop in update_stocks_task.
    async def mock_sleep(delay):
        raise asyncio.CancelledError()
        
    with patch('stocks.get_db', return_value=mock_db), \
         patch('seasons.get_season_config', return_value=mock_season_config), \
         patch('asyncio.sleep', side_effect=mock_sleep), \
         patch('logging.error') as mock_log_error:
         
         import stocks
         try:
             await stocks.update_stocks_task()
         except asyncio.CancelledError:
             pass
             
         # Verify that logging.error was not called with KeyError
         for call in mock_log_error.call_args_list:
             assert 'ticker' not in str(call)
             assert 'KeyError' not in str(call)
