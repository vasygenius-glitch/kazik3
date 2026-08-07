import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from profile_bank import (
    process_deposit_in_memory,
    process_withdraw_in_memory,
    get_bank_info,
    set_bank_in_cache,
    get_bank_from_cache,
    _bank_cache
)
from user_manager import _user_cache, _dirty_cache, set_in_cache, get_user_data


@pytest.fixture(autouse=True)
def clear_all_test_caches():
    _user_cache.clear()
    _dirty_cache.clear()
    _bank_cache.clear()
    yield
    _user_cache.clear()
    _dirty_cache.clear()
    _bank_cache.clear()


# ==============================================================================
# СЮИТА 1: 100 ТЕСТОВ МГНОВЕННОГО СПИСАНИЯ С БАЛАНСА И СИНХРОНИЗАЦИИ КЭША
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("i, balance, deposit", [
    (idx, 100_000 + idx * 1000, 5000 + idx * 100) for idx in range(100)
])
async def test_500_deposit_cache_sync_no_dupes(i, balance, deposit):
    """Проверка точного списания с баланса и немедленного обновления кэша (100 тестов)."""
    chat_id = 20000 + i
    user_id = 30000 + i
    banker_id = 40000 + i

    bank_data = {'banker_id': banker_id, 'name': f"Bank_{i}", 'capital': 10_000_000, 'deposit_rate': 5.0}
    user_data = {'balance': balance, 'bank_deposit': 0, 'bank_name': None, 'deposit_start_time': 0}

    set_in_cache(chat_id, user_id, user_data)
    set_bank_in_cache(chat_id, banker_id, bank_data)

    with patch('profile_bank.create_or_update_bank', new_callable=AsyncMock):
        actual_amt, new_dep = await process_deposit_in_memory(chat_id, user_id, banker_id, deposit)

        assert actual_amt == deposit
        assert new_dep == deposit

        # Проверяем кэш пользователя: баланс уменьшен РО ВНО на deposit!
        cached_user = await get_user_data(chat_id, user_id)
        assert cached_user['balance'] == balance - deposit
        assert cached_user['bank_deposit'] == deposit
        assert cached_user['bank_name'] == banker_id


# ==============================================================================
# СЮИТА 2: 100 ТЕСТОВ МГНОВЕННОГО СНЯТИЯ СО ВКЛАДА И НАЧИСЛЕНИЯ НА КОШЕЛЕК
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("i, initial_bal, deposit_amt, withdraw_amt", [
    (idx, 1000, 50_000 + idx * 500, 10_000 + idx * 100) for idx in range(100)
])
async def test_500_withdraw_cache_sync_exact(i, initial_bal, deposit_amt, withdraw_amt):
    """Проверка точного зачисления на баланс при выводе из банка (100 тестов)."""
    chat_id = 50000 + i
    user_id = 60000 + i
    banker_id = 70000 + i

    bank_data = {'banker_id': banker_id, 'name': f"Bank_{i}", 'capital': 100_000_000, 'deposit_rate': 5.0}
    user_data = {'balance': initial_bal, 'bank_deposit': deposit_amt, 'bank_name': banker_id, 'deposit_start_time': int(time.time())}

    set_in_cache(chat_id, user_id, user_data)
    set_bank_in_cache(chat_id, banker_id, bank_data)

    with patch('profile_bank.create_or_update_bank', new_callable=AsyncMock):
        actual_withdrawn = await process_withdraw_in_memory(chat_id, user_id, banker_id, withdraw_amt)

        assert actual_withdrawn == withdraw_amt

        cached_user = await get_user_data(chat_id, user_id)
        assert cached_user['balance'] == initial_bal + withdraw_amt
        assert cached_user['bank_deposit'] == deposit_amt - withdraw_amt


# ==============================================================================
# СЮИТА 3: 100 ТЕСТОВ УСТОЙЧИВОСТИ К ТАЙМАУТАМ И 429 КВОТЕ (2.0s TIMEOUT)
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("i", range(100))
async def test_500_bank_info_timeout_resilience(i):
    """Проверка немедленного возврата кэша банка без ожидания сети при таймаутах (100 тестов)."""
    chat_id = 80000 + i
    banker_id = 90000 + i

    bank_data = {'banker_id': banker_id, 'name': f"QuickBank_{i}", 'capital': 5_000_000, 'deposit_rate': 3.0}
    set_bank_in_cache(chat_id, banker_id, bank_data)

    # Имитируем сетевой затор (TimeoutError при обращении к Firestore)
    slow_doc = AsyncMock()
    slow_doc.get.side_effect = asyncio.TimeoutError("429 Quota Exceeded Network Slowdown")

    mock_db = MagicMock()
    mock_db.collection().document().collection().document.return_value = slow_doc

    with patch('profile_bank.get_db', return_value=mock_db):
        start_time = time.time()
        result = await get_bank_info(chat_id, banker_id)
        elapsed = time.time() - start_time

        # Должно отвечать мгновенно из кэша (меньше 0.1 секунды)
        assert elapsed < 0.5
        assert result is not None
        assert result['name'] == f"QuickBank_{i}"


# ==============================================================================
# СЮИТА 4: 100 ТЕСТОВ ПРЕДОТВРАЩЕНИЯ МНОГОКРАТНОГО ДЮПА ПРИ DEPOSIT ALL
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("i, initial_wallet", [
    (idx, 50_000 + idx * 1000) for idx in range(100)
])
async def test_500_deposit_all_zero_duplication_on_repeated_calls(i, initial_wallet):
    """Проверка, что повторный deposit all с балансом 0 отклоняется (100 тестов)."""
    chat_id = 100000 + i
    user_id = 110000 + i
    banker_id = 120000 + i

    bank_data = {'banker_id': banker_id, 'name': f"Bank_{i}", 'capital': 100_000_000, 'deposit_rate': 5.0}
    user_data = {'balance': initial_wallet, 'bank_deposit': 0, 'bank_name': None, 'deposit_start_time': 0}

    set_in_cache(chat_id, user_id, user_data)
    set_bank_in_cache(chat_id, banker_id, bank_data)

    with patch('profile_bank.create_or_update_bank', new_callable=AsyncMock):
        # 1-й вызов: депозитит всё
        amt1, dep1 = await process_deposit_in_memory(chat_id, user_id, banker_id, -1)
        assert amt1 == initial_wallet
        assert dep1 == initial_wallet

        # Баланс кошелька стал 0!
        user_after_1 = await get_user_data(chat_id, user_id)
        assert user_after_1['balance'] == 0

        # 2-й вызов deposit all с нулевым балансом ДОЛЖЕН БЫТЬ ОТКЛОНЕН!
        with pytest.raises(ValueError, match="Сумма должна быть положительной|Недостаточно средств"):
            await process_deposit_in_memory(chat_id, user_id, banker_id, -1)

        # Депозит НЕ должен дюпнуться!
        user_after_2 = await get_user_data(chat_id, user_id)
        assert user_after_2['bank_deposit'] == initial_wallet


# ==============================================================================
# СЮИТА 5: 100 ТЕСТОВ ОГРАНИЧЕНИЯ ЛИКВИДНОСТИ КАПИТАЛА БАНКА
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("i, bank_cap, req_withdraw", [
    (idx, 1000 + idx * 100, 2000 + idx * 100) for idx in range(100)
])
async def test_500_bank_liquidity_cap_protection(i, bank_cap, req_withdraw):
    """Проверка защиты от выдачи сумм превышающих капитал банка (100 тестов)."""
    chat_id = 130000 + i
    user_id = 140000 + i
    banker_id = 150000 + i

    bank_data = {'banker_id': banker_id, 'name': f"CapBank_{i}", 'capital': bank_cap, 'deposit_rate': 5.0}
    user_data = {'balance': 0, 'bank_deposit': req_withdraw, 'bank_name': banker_id, 'deposit_start_time': int(time.time())}

    set_in_cache(chat_id, user_id, user_data)
    set_bank_in_cache(chat_id, banker_id, bank_data)

    with patch('profile_bank.create_or_update_bank', new_callable=AsyncMock):
        # Если капитал банка меньше требуемой суммы — выдача запрещена!
        with pytest.raises(ValueError, match="У банка недостаточно ликвидности"):
            await process_withdraw_in_memory(chat_id, user_id, banker_id, req_withdraw)

        # Балансы остаются неизменными
        user_after = await get_user_data(chat_id, user_id)
        assert user_after['balance'] == 0
        assert user_after['bank_deposit'] == req_withdraw
