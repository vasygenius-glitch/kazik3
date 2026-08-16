import pytest
from shop import ITEMS
from creator import DICTORS_LIST, resolve_dictor_id
from user_manager import is_dictor_item, preserve_protected_inventory, add_item_to_inventory, get_user_data, update_user_field
from inventory import get_inventory_main_kb

# 70 отдельных тестов для каждого ранга Дикторов
@pytest.mark.parametrize("index,item_tuple", enumerate(DICTORS_LIST, start=1))
def test_each_of_70_dictors(index, item_tuple):
    dictor_id, title = item_tuple
    
    # 1. Проверка наличия в ITEMS
    assert dictor_id in ITEMS, f"Диктор {dictor_id} отсутствует в shop.ITEMS!"
    item_cfg = ITEMS[dictor_id]
    
    # 2. Проверка категории
    assert item_cfg.get("cat") == "tayniy_baniy", f"Диктор {dictor_id} имеет неверную категорию {item_cfg.get('cat')}!"
    
    # 3. Проверка действия
    assert item_cfg.get("action") in ("other", "dictor"), f"Диктор {dictor_id} имеет неверный action {item_cfg.get('action')}!"
    
    # 4. Проверка имени и описания
    assert "name" in item_cfg and len(item_cfg["name"]) > 0
    assert "desc" in item_cfg and len(item_cfg["desc"]) > 0
    
    # 5. Проверка резолвера по номеру (1..70)
    resolved_by_num = resolve_dictor_id(str(index))
    assert resolved_by_num == dictor_id, f"resolve_dictor_id('{index}') вернул {resolved_by_num}, ожидалось {dictor_id}"
    
    # 6. Проверка резолвера по ID
    resolved_by_id = resolve_dictor_id(dictor_id)
    assert resolved_by_id == dictor_id
    
    # 7. Проверка функции иммунитета к сбросам
    assert is_dictor_item(dictor_id) is True, f"is_dictor_item({dictor_id}) вернул False!"
    
    # 8. Проверка сохранения в preserve_protected_inventory
    raw_inv = {
        dictor_id: 3,
        "shaurma": 10,
        "bmw_m5": 2
    }
    preserved = preserve_protected_inventory(raw_inv)
    assert dictor_id in preserved, f"Диктор {dictor_id} не сохранился в инвентаре после сброса!"
    assert preserved[dictor_id] == 3
    assert "shaurma" not in preserved
    assert "bmw_m5" not in preserved

@pytest.mark.asyncio
async def test_antigravity_dictor_grant_and_inventory():
    """Тест добавления #70 Антигравитационного диктора и отображения в инвентаре."""
    from user_manager import set_in_cache
    chat_id = -100999888
    user_id = 777123
    
    # Инициализируем в кэше
    set_in_cache(chat_id, user_id, {"inventory": {}, "balance": 1000, "full_name": "Тестер"})
    
    # Добавляем 70-го диктора
    top_id = "dictor_antigravity"
    success = await add_item_to_inventory(chat_id, user_id, top_id, count=1)
    assert success is True
    
    u_data = await get_user_data(chat_id, user_id)
    inv = u_data.get("inventory", {})
    assert inv.get(top_id) == 1
    
    # Проверяем генерацию инлайн клавиатуры инвентаря
    kb = get_inventory_main_kb(inv, {})
    assert kb is not None
    # Проверяем, что кнопка с диктором создана
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any(ITEMS[top_id]["name"] in t for t in button_texts)
