import time
import pytest
from prestige import (
    PRESTIGE_TIERS,
    get_user_prestige,
    get_prestige_perks,
    calculate_user_net_worth,
    get_unsettled_transfers_24h,
    get_required_business_count,
    count_user_businesses,
)
from user_manager import record_unsettled_transfer
from shop import ITEMS
from rp_clans import get_clan_lock

def test_prestige_tiers_data():
    """Проверка целостности таблицы рангов престижа."""
    assert len(PRESTIGE_TIERS) == 6
    for tier, info in PRESTIGE_TIERS.items():
        assert info["cost"] > 0
        assert info["income_multiplier"] > 1.0
        assert info["starting_bonus"] > 0
        assert "name" in info
        assert "desc" in info

def test_user_net_worth_calculation():
    """Проверка подсчета суммарного капитала пользователя."""
    user_data = {
        "balance": 10_000_000,
        "bank_deposit": 15_000_000,
        "inventory": {
            "мойка": 2,          # 125_000 * 2 = 250_000
            "бугатти": 1,        # 1_250_000
            "prestige_mine": 1,  # 5_000_000
        },
        "biz_levels": {
            "мойка": 3,          # Уровни 2, 3: 125k * 0.5 * 1 + 125k * 0.5 * 2 = 62.5k + 125k = 187.5k
        }
    }
    net_worth = calculate_user_net_worth(user_data)
    assert net_worth >= 25_000_000
    assert net_worth == 10_000_000 + 15_000_000 + (125_000 * 2 + 187_500) + 1_250_000 + 5_000_000

def test_prestige_perks_calculation():
    """Проверка корректного извлечения бонусов престижа."""
    # Уровень 0
    p0 = get_prestige_perks({"prestige_level": 0})
    assert p0["level"] == 0
    assert p0["income_multiplier"] == 1.0
    assert p0["tax_discount"] == 0

    # Уровень 1 (Барон)
    p1 = get_prestige_perks({"prestige_level": 1})
    assert p1["level"] == 1
    assert p1["name"] == "Барон"
    assert p1["income_multiplier"] == 1.15
    assert p1["tax_discount"] == 5

    # Уровень 6 (Абсолют)
    p6 = get_prestige_perks({"prestige_level": 6})
    assert p6["level"] == 6
    assert p6["name"] == "Абсолют"
    assert p6["income_multiplier"] == 2.50
    assert p6["tax_discount"] == 35

def test_prestige_shop_items_requirement():
    """Проверка требований к рангу престижа у эксклюзивных товаров."""
    for item_id, info in ITEMS.items():
        if info.get("cat") == "prestige":
            req_tier = info.get("req_prestige")
            assert req_tier is not None
            assert 1 <= req_tier <= 6

def test_prestige_reset_inventory_filtering():
    """Проверка фильтрации инвентаря: сброс обычных и сохранение престиж-предметов."""
    old_inv = {
        "мойка": 5,
        "бугатти": 2,
        "prestige_mine": 1,
        "prestige_kopter": 1,
    }
    new_inv = {}
    for item_id, count in old_inv.items():
        item = ITEMS.get(item_id)
        if item and item.get("cat") == "prestige":
            new_inv[item_id] = count

    assert "мойка" not in new_inv
    assert "бугатти" not in new_inv
    assert new_inv["prestige_mine"] == 1
    assert new_inv["prestige_kopter"] == 1

def test_unsettled_transfers_quarantine():
    """Проверка 24-часового карантина на входящие переводы для защиты от перелива."""
    user = {"unsettled_transfers": []}
    
    # Записываем перевод 50M
    record_unsettled_transfer(user, 50_000_000)
    assert get_unsettled_transfers_24h(user) == 50_000_000

    # Проверяем устаревание через 25 часов
    old_ts = time.time() - 90000
    user["unsettled_transfers"] = [{"amount": 50_000_000, "ts": old_ts}]
    assert get_unsettled_transfers_24h(user) == 0

def test_prestige_infrastructure_business_requirements():
    """Проверка требований к реальной инфраструктуре бизнеса перед получением Престижа."""
    assert get_required_business_count(1) == 3
    assert get_required_business_count(2) == 5
    assert get_required_business_count(6) == 15

    user_empty = {"inventory": {}}
    assert count_user_businesses(user_empty) == 0

    user_rich_with_biz = {
        "inventory": {
            "мойка": 2,
            "бугатти": 1,
            "prestige_mine": 1,
            "condom": 50,  # "other" не считается бизнесом/машиной
        }
    }
    # 2 мойки + 1 бугатти + 1 квантовый майнер = 4 предприятия
    assert count_user_businesses(user_rich_with_biz) == 4

def test_clan_locking_concurrency():
    """Проверка генерации локов для кланов для защиты от гонок и дюпов."""
    lock1 = get_clan_lock(123, "Alpha")
    lock2 = get_clan_lock(123, "alpha ")
    assert lock1 is lock2
