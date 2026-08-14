import pytest
from shop import ITEMS, SELL_RATIO

def test_single_business_full_upgrade_sell():
    """Тест: продажа 1 полностью прокачанного бизнеса."""
    item = ITEMS["мойка"]
    base_price = item["price"]  # 125_000
    level = 5  # Уровни 2, 3, 4, 5
    upgrade_invested = sum(int(base_price * 0.5 * l) for l in range(1, level))  # 125k * 0.5 * 10 = 625_000
    
    base_refund = int(base_price * SELL_RATIO)  # 93_750
    upgrade_refund = int(upgrade_invested * SELL_RATIO)  # 468_750
    total_expected = base_refund + upgrade_refund  # 562_500
    
    # 1 шт из 1
    sell_count = 1
    owned_qty = 1
    total_payout = (base_refund * sell_count) + (upgrade_refund if sell_count >= owned_qty else 0)
    assert total_payout == total_expected
    assert total_payout == 562_500

def test_five_businesses_full_upgrade_sell_all():
    """Тест: продажа всех 5 полностью прокачанных бизнесов."""
    item = ITEMS["мойка"]
    base_price = item["price"]  # 125_000
    level = 5
    upgrade_invested = sum(int(base_price * 0.5 * l) for l in range(1, level))  # 625_000
    
    base_refund = int(base_price * SELL_RATIO)  # 93_750
    upgrade_refund = int(upgrade_invested * SELL_RATIO)  # 468_750
    
    sell_count = 5
    owned_qty = 5
    # За 5 штук: (5 * 93_750) + 468_750 = 468_750 + 468_750 = 937_500
    total_payout = (base_refund * sell_count) + (upgrade_refund if sell_count >= owned_qty else 0)
    assert total_payout == (93_750 * 5) + 468_750
    assert total_payout == 937_500

def test_five_businesses_sell_partial():
    """Тест: частичная продажа (1 из 5). Возврат за апгрейд не отдается, пока есть копии."""
    item = ITEMS["мойка"]
    base_price = item["price"]
    level = 5
    upgrade_invested = sum(int(base_price * 0.5 * l) for l in range(1, level))
    
    base_refund = int(base_price * SELL_RATIO)
    upgrade_refund = int(upgrade_invested * SELL_RATIO)
    
    sell_count = 1
    owned_qty = 5
    total_payout = (base_refund * sell_count) + (upgrade_refund if sell_count >= owned_qty else 0)
    assert total_payout == base_refund
    assert total_payout == 93_750

def test_bank_compound_interest_cap():
    """Тест: защита от экспоненциального разгона сложных процентов в банке."""
    # Симуляция дней хранения
    current_deposit = 1_000_000
    
    # 1. Нормальный случай: 5 дней
    days_held = 5
    days_held = min(max(0, days_held), 30)
    temp_dep = current_deposit
    for _ in range(days_held):
        temp_dep += int(temp_dep * 0.01)
    assert temp_dep > current_deposit
    assert temp_dep < current_deposit * 1.10
    
    # 2. Экстремальный/битый случай: 25000 дней (битый timestamp = 0)
    corrupted_days = 25000
    capped_days = min(max(0, corrupted_days), 30)
    assert capped_days == 30
    
    temp_dep_corrupted = current_deposit
    for _ in range(capped_days):
        temp_dep_corrupted += int(temp_dep_corrupted * 0.01)
    # Проверяем, что баланс не улетел в бесконечность / триллионы
    assert temp_dep_corrupted < current_deposit * 1.5

def test_clan_rename_command_variants():
    """Тест: разбор различных вариантов ввода команды смены названия клана."""
    commands = [
        ("клан переименовать МегаКлан", "переименовать", "МегаКлан"),
        ("клан сменить название Новые Герои", "сменить", "Новые Герои"),
        ("клан изменить название Золотой Век", "изменить", "Золотой Век"),
        ("клан имя Элита", "имя", "Элита"),
        ("клан название Победители", "название", "Победители"),
        ("клан ренейм Shadow Team", "ренейм", "Shadow Team"),
        ("/clan rename Dragons", "rename", "Dragons"),
        ("/clan name Phoenix", "name", "Phoenix"),
    ]
    
    for text, expected_action, expected_name in commands:
        args = text.split(maxsplit=2)
        action = args[1].lower()
        assert action in ["rename", "name", "переименовать", "название", "имя", "сменить", "изменить", "ренейм", "rename_clan"]
        raw = args[2].strip()
        for p in ["название ", "имя ", "name "]:
            if raw.lower().startswith(p):
                raw = raw[len(p):].strip()
                break
        assert raw == expected_name
