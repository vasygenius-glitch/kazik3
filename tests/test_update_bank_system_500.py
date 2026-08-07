import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# --- 500 ТЕСТОВ БАНКОВСКОЙ СИСТЕМЫ И ИНВЕНТАРНО-КЭШЕВОЙ ЦЕЛОСТНОСТИ ---

from profile_bank import process_deposit_in_memory, process_withdraw_in_memory
from user_manager import _user_cache, _dirty_cache, set_in_cache, get_user_data, invalidate_user_cache


@pytest.fixture(autouse=True)
def clear_caches():
    _user_cache.clear()
    _dirty_cache.clear()
    yield
    _user_cache.clear()
    _dirty_cache.clear()


# ==============================================================================
# БЛОК 1: 100 ТЕСТОВ ПОПОЛНЕНИЯ ВКЛАДА (/bank deposit)
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("test_id, initial_balance, deposit_amount", [
    (i, 1000 + i * 500, 100 + i * 50) for i in range(100)
])
async def test_bank_deposit_in_memory_exact_balance_deduction(test_id, initial_balance, deposit_amount):
    """Проверка точного списания средств с баланса и добавления во вклад (100 тестов)."""
    chat_id = 1000 + test_id
    user_id = 2000 + test_id
    banker_id = 3000 + test_id

    bank_data = {
        'banker_id': banker_id,
        'name': f"Bank_{test_id}",
        'capital': 1_000_000,
        'deposit_rate': 5.0
    }

    user_data = {
        'balance': initial_balance,
        'bank_deposit': 0,
        'bank_name': None,
        'deposit_start_time': 0
    }

    with patch('profile_bank.get_bank_info', new_callable=AsyncMock) as mock_get_bank, \
         patch('profile_bank.get_user_data', new_callable=AsyncMock) as mock_get_user, \
         patch('profile_bank.create_or_update_bank', new_callable=AsyncMock) as mock_update_bank:

        mock_get_bank.return_value = bank_data
        mock_get_user.return_value = user_data.copy()

        # Первичная вставка в кэш
        set_in_cache(chat_id, user_id, user_data)

        actual_amt, new_dep = await process_deposit_in_memory(chat_id, user_id, banker_id, deposit_amount)

        assert actual_amt == deposit_amount
        assert new_dep == deposit_amount

        # Читаем данные из кэша — баланс ДОЛЖЕН БЫТЬ УМЕНЬШЕН ровно на deposit_amount!
        updated_user = await get_user_data(chat_id, user_id)
        assert updated_user['balance'] == initial_balance - deposit_amount
        assert updated_user['bank_deposit'] == deposit_amount
        assert updated_user['bank_name'] == banker_id
        assert (chat_id, user_id) in _dirty_cache


# ==============================================================================
# БЛОК 2: 100 ТЕСТОВ СНЯТИЯ СО ВКЛАДА (/bank withdraw)
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("test_id, initial_balance, initial_deposit, withdraw_amount", [
    (i, 500, 1000 + i * 200, 100 + i * 20) for i in range(100)
])
async def test_bank_withdraw_in_memory_exact_balance_addition(test_id, initial_balance, initial_deposit, withdraw_amount):
    """Проверка точного зачисления средств на баланс при снятии со вклада (100 тестов)."""
    chat_id = 5000 + test_id
    user_id = 6000 + test_id
    banker_id = 7000 + test_id

    bank_data = {
        'banker_id': banker_id,
        'name': f"Bank_{test_id}",
        'capital': 10_000_000,
        'deposit_rate': 5.0
    }

    user_data = {
        'balance': initial_balance,
        'bank_deposit': initial_deposit,
        'bank_name': banker_id,
        'deposit_start_time': int(time.time())
    }

    with patch('profile_bank.get_bank_info', new_callable=AsyncMock) as mock_get_bank, \
         patch('profile_bank.get_user_data', new_callable=AsyncMock) as mock_get_user, \
         patch('profile_bank.create_or_update_bank', new_callable=AsyncMock) as mock_update_bank:

        mock_get_bank.return_value = bank_data
        mock_get_user.return_value = user_data.copy()

        set_in_cache(chat_id, user_id, user_data)

        actual_withdrawn = await process_withdraw_in_memory(chat_id, user_id, banker_id, withdraw_amount)

        assert actual_withdrawn == withdraw_amount

        updated_user = await get_user_data(chat_id, user_id)
        assert updated_user['balance'] == initial_balance + withdraw_amount
        assert updated_user['bank_deposit'] == initial_deposit - withdraw_amount
        assert (chat_id, user_id) in _dirty_cache


# ==============================================================================
# БЛОК 3: 100 ТЕСТОВ ПОЛНОГО СНЯТИЯ ВСЕХ СРЕДСТВ (/bank withdraw all)
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("test_id, initial_deposit", [
    (i, 5000 + i * 1000) for i in range(100)
])
async def test_bank_withdraw_all_resets_bank_name(test_id, initial_deposit):
    """Проверка обнуления банковского счёта и отвязки банка при полном снятии (100 тестов)."""
    chat_id = 8000 + test_id
    user_id = 9000 + test_id
    banker_id = 9500 + test_id

    bank_data = {
        'banker_id': banker_id,
        'name': f"Bank_{test_id}",
        'capital': 50_000_000,
        'deposit_rate': 5.0
    }

    user_data = {
        'balance': 0,
        'bank_deposit': initial_deposit,
        'bank_name': banker_id,
        'deposit_start_time': int(time.time())
    }

    with patch('profile_bank.get_bank_info', new_callable=AsyncMock) as mock_get_bank, \
         patch('profile_bank.get_user_data', new_callable=AsyncMock) as mock_get_user, \
         patch('profile_bank.create_or_update_bank', new_callable=AsyncMock) as mock_update_bank:

        mock_get_bank.return_value = bank_data
        mock_get_user.return_value = user_data.copy()

        set_in_cache(chat_id, user_id, user_data)

        # -1 означает 'all'
        actual_withdrawn = await process_withdraw_in_memory(chat_id, user_id, banker_id, -1)

        assert actual_withdrawn == initial_deposit

        updated_user = await get_user_data(chat_id, user_id)
        assert updated_user['balance'] == initial_deposit
        assert updated_user['bank_deposit'] == 0
        assert updated_user['bank_name'] is None
        assert updated_user['deposit_start_time'] == 0


# ==============================================================================
# БЛОК 4: 100 ТЕСТОВ НАЧИСЛЕНИЯ ПРОЦЕНТОВ ПО ВКЛАДАМ
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("test_id, days_held, deposit_rate", [
    (i, (i % 10) + 1, 1.0 + (i % 5)) for i in range(100)
])
async def test_bank_interest_accrual_on_withdraw(test_id, days_held, deposit_rate):
    """Проверка корректности расчета ежедневного процента при снятии (100 тестов)."""
    chat_id = 11000 + test_id
    user_id = 12000 + test_id
    banker_id = 13000 + test_id
    base_deposit = 100_000

    start_time = int(time.time()) - (days_held * 86400)

    bank_data = {
        'banker_id': banker_id,
        'name': f"Bank_{test_id}",
        'capital': 1_000_000_000,
        'deposit_rate': deposit_rate
    }

    user_data = {
        'balance': 0,
        'bank_deposit': base_deposit,
        'bank_name': banker_id,
        'deposit_start_time': start_time
    }

    with patch('profile_bank.get_bank_info', new_callable=AsyncMock) as mock_get_bank, \
         patch('profile_bank.get_user_data', new_callable=AsyncMock) as mock_get_user, \
         patch('profile_bank.create_or_update_bank', new_callable=AsyncMock) as mock_update_bank:

        mock_get_bank.return_value = bank_data
        mock_get_user.return_value = user_data.copy()

        set_in_cache(chat_id, user_id, user_data)

        # Снимаем всё с процентами
        actual_withdrawn = await process_withdraw_in_memory(chat_id, user_id, banker_id, -1)

        # Расчет ожидаемых процентов
        loyalty_bonus = min(5.0, days_held * 0.5)
        final_rate = deposit_rate + loyalty_bonus
        expected_interest = int(base_deposit * (final_rate / 100) * days_held)
        expected_total = base_deposit + expected_interest

        assert actual_withdrawn == expected_total

        updated_user = await get_user_data(chat_id, user_id)
        assert updated_user['balance'] == expected_total
        assert updated_user['bank_deposit'] == 0


# ==============================================================================
# БЛОК 5: 100 ТЕСТОВ ИСКЛЮЧЕНИЙ И ЗАЩИТЫ ОТ ОШИБОК И ДЮПА
# ==============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("test_id, err_type", [
    (i, i % 5) for i in range(100)
])
async def test_bank_error_handling_and_no_duplication(test_id, err_type):
    """Проверка выброса ошибок при некорректных аргументах и ликвидности (100 тестов)."""
    chat_id = 14000 + test_id
    user_id = 15000 + test_id
    banker_id = 16000 + test_id

    bank_data = {
        'banker_id': banker_id,
        'name': f"Bank_{test_id}",
        'capital': 500,  # маленькая ликвидность
        'deposit_rate': 5.0
    }

    user_data = {
        'balance': 1000,
        'bank_deposit': 5000,
        'bank_name': banker_id,
        'deposit_start_time': int(time.time())
    }

    with patch('profile_bank.get_bank_info', new_callable=AsyncMock) as mock_get_bank, \
         patch('profile_bank.get_user_data', new_callable=AsyncMock) as mock_get_user, \
         patch('profile_bank.create_or_update_bank', new_callable=AsyncMock) as mock_update_bank:

        mock_get_bank.return_value = bank_data
        mock_get_user.return_value = user_data.copy()
        set_in_cache(chat_id, user_id, user_data)

        if err_type == 0:
            # Отрицательный депозит
            with pytest.raises(ValueError, match="Сумма должна быть положительной"):
                await process_deposit_in_memory(chat_id, user_id, banker_id, -100)
        elif err_type == 1:
            # Депозит превышает баланс
            with pytest.raises(ValueError, match="Недостаточно средств на балансе"):
                await process_deposit_in_memory(chat_id, user_id, banker_id, 2000)
        elif err_type == 2:
            # Отрицательное снятие
            with pytest.raises(ValueError, match="Сумма должна быть положительной"):
                await process_withdraw_in_memory(chat_id, user_id, banker_id, -500)
        elif err_type == 3:
            # Снятие превышает вклад
            with pytest.raises(ValueError, match="На вашем вкладе только"):
                await process_withdraw_in_memory(chat_id, user_id, banker_id, 10000)
        elif err_type == 4:
            # Снятие превышает капитал (ликвидность) банка
            with pytest.raises(ValueError, match="У банка недостаточно ликвидности"):
                await process_withdraw_in_memory(chat_id, user_id, banker_id, 4000)
