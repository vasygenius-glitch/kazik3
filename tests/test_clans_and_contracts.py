import pytest
from rp_clans import get_clan_lock
from user_manager import preserve_protected_inventory, is_dictor_item

def test_clan_locks_identity():
    """Проверка генерации единого локов для одного клана независимо от регистра."""
    lock_a = get_clan_lock(100, "Sparta")
    lock_b = get_clan_lock(100, "sparta")
    lock_c = get_clan_lock(100, "  SPARTA  ")
    assert lock_a is lock_b
    assert lock_b is lock_c

    # Разные кланы получают разные локи
    lock_other = get_clan_lock(100, "Vikings")
    assert lock_a is not lock_other

def test_inheritance_dictor_preservation():
    """Проверка сохранения Дикторов при передаче наследства."""
    sender_inventory = {
        "dictor_godlike": 1,
        "мойка": 5,
        "бугатти": 2,
    }
    
    # Дикторы должны остаться у завещателя
    preserved = preserve_protected_inventory(sender_inventory)
    assert "dictor_godlike" in preserved
    assert "мойка" not in preserved
    assert "бугатти" not in preserved
