import pytest
import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Настраиваем моки до импорта тестируемых модулей
mock_fa_async = MagicMock()
mock_fa_async.transactional = lambda f: f
mock_fa_async.async_transactional = lambda f: f

firebase_admin_mock = MagicMock()
firebase_admin_mock.firestore_async = mock_fa_async

sys.modules['firebase_admin'] = firebase_admin_mock
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = mock_fa_async
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()
sys.modules['config'].CREATOR_ID = 999
import economy_utils

import court
import rp_clans

def create_mock_message(text, user_id=111, chat_id=123, is_reply=False, target_id=222):
    msg = AsyncMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.from_user.id = user_id
    msg.from_user.full_name = "User"
    if is_reply:
        msg.reply_to_message = AsyncMock()
        msg.reply_to_message.from_user.id = target_id
        msg.reply_to_message.from_user.full_name = "Target"
        msg.reply_to_message.from_user.is_bot = False
    else:
        msg.reply_to_message = None
    return msg

# --- Группа 1: Атака клана Создателя (20 тестов) ---
# Будем проверять 20 комбинаций участников, казны и ролла кубика.
# В каждом случае клан лидера 999 (Создатель) должен победить,
# даже если ролл кубика равен 100 (что обычно означает поражение).

attack_test_cases = [
    # (my_members, enemy_members, my_treasury, enemy_treasury, random_roll)
    (1, 10, 5000, 8000, 100),
    (2, 5, 2000, 4000, 95),
    (3, 3, 1000, 1000, 80),
    (5, 1, 1500, 3000, 99),
    (10, 10, 9000, 15000, 75),
    (1, 1, 1200, 1200, 90),
    (20, 2, 5000, 20000, 85),
    (4, 8, 3000, 6000, 92),
    (6, 6, 2500, 3500, 97),
    (12, 15, 8000, 12000, 88),
    (1, 20, 1000, 50000, 100),
    (8, 2, 4500, 1500, 91),
    (5, 5, 6000, 6000, 94),
    (7, 3, 7200, 8800, 93),
    (9, 11, 4000, 5000, 96),
    (11, 9, 5300, 6400, 89),
    (2, 15, 3000, 10000, 98),
    (15, 2, 10000, 3000, 87),
    (14, 14, 5500, 5500, 79),
    (10, 30, 20000, 20000, 100),
]

@pytest.mark.parametrize("my_members, enemy_members, my_treasury, enemy_treasury, random_roll", attack_test_cases)
@pytest.mark.asyncio
async def test_creator_clan_attack_always_wins(my_members, enemy_members, my_treasury, enemy_treasury, random_roll):
    msg = create_mock_message("/clan raid Enemy", user_id=999) # 999 - Лидер и Создатель
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {
        'leader_id': 999,  # Клан создателя
        'treasury': my_treasury,
        'members': [999] * my_members
    }
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    enemy_doc = MagicMock()
    enemy_doc.exists = True
    enemy_doc.to_dict.return_value = {
        'leader_id': 111,
        'treasury': enemy_treasury,
        'members': [111] * enemy_members
    }
    enemy_ref = AsyncMock()
    enemy_ref.get.return_value = enemy_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'MyClan': return my_ref
        return enemy_ref

    rp_clans.active_clan_raids.clear()

    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect), \
         patch("random.randint", side_effect=[random_roll, 15]): # 15 = 15% украдено
         
        await rp_clans.cmd_clan(msg)
        
        # Проверяем, что набег завершился успехом: казна врага уменьшилась, наша увеличилась
        enemy_ref.update.assert_called_once()
        my_ref.update.assert_called_once()
        
        # Получаем аргументы обновления
        enemy_update = enemy_ref.update.call_args[0][0]
        my_update = my_ref.update.call_args[0][0]
        
        # Должно быть украдено 15%
        expected_stolen = int(enemy_treasury * 0.15)
        assert enemy_update['treasury'] == enemy_treasury - expected_stolen
        assert my_update['treasury'] == my_treasury + expected_stolen
        assert "УСПЕШНЫЙ НАБЕГ" in msg.answer.call_args[0][0]


# --- Группа 2: Оборона клана Создателя (20 тестов) ---
# Будем проверять 20 комбинаций, где обычный клан нападает на клан Создателя (лидер 999).
# Атакующий должен ВСЕГДА проигрывать и "получать по лицу", даже если ролл равен 1 (что обычно победа).

defense_test_cases = [
    # (attacker_members, my_members, attacker_treasury, my_treasury, random_roll)
    (10, 1, 8000, 5000, 1),
    (5, 2, 4000, 2000, 2),
    (3, 3, 1000, 1000, 5),
    (1, 5, 3000, 1500, 10),
    (10, 10, 15000, 9000, 3),
    (1, 1, 1200, 1200, 1),
    (2, 20, 20000, 5000, 8),
    (8, 4, 6000, 3000, 4),
    (6, 6, 3500, 2500, 6),
    (15, 12, 12000, 8000, 7),
    (20, 1, 50000, 1000, 1),
    (2, 8, 1500, 4500, 9),
    (5, 5, 6000, 6000, 10),
    (3, 7, 8800, 7200, 2),
    (11, 9, 5000, 4000, 5),
    (9, 11, 6400, 5300, 3),
    (15, 2, 10000, 3000, 4),
    (2, 15, 3000, 10000, 1),
    (14, 14, 5500, 5500, 2),
    (30, 10, 20000, 20000, 1),
]

@pytest.mark.parametrize("attacker_members, my_members, attacker_treasury, my_treasury, random_roll", defense_test_cases)
@pytest.mark.asyncio
async def test_creator_clan_defense_always_wins(attacker_members, my_members, attacker_treasury, my_treasury, random_roll):
    msg = create_mock_message("/clan raid CreatorClan", user_id=111) # Обычный юзер нападает
    
    attacker_doc = MagicMock()
    attacker_doc.exists = True
    attacker_doc.to_dict.return_value = {
        'leader_id': 111,
        'treasury': attacker_treasury,
        'members': [111] * attacker_members
    }
    attacker_ref = AsyncMock()
    attacker_ref.get.return_value = attacker_doc
    
    creator_doc = MagicMock()
    creator_doc.exists = True
    creator_doc.to_dict.return_value = {
        'leader_id': 999,  # Клан создателя
        'treasury': my_treasury,
        'members': [999] * my_members
    }
    creator_ref = AsyncMock()
    creator_ref.get.return_value = creator_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'AttackerClan': return attacker_ref
        return creator_ref

    rp_clans.active_clan_raids.clear()

    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'AttackerClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect), \
         patch("random.randint", side_effect=[random_roll, 20]): # 20 = 20% штраф
         
        await rp_clans.cmd_clan(msg)
        
        # Проверяем, что набег провалился: казна атакующего уменьшилась, а создателя НЕ изменилась
        attacker_ref.update.assert_called_once()
        creator_ref.update.assert_not_called()
        
        # Получаем аргументы обновления
        attacker_update = attacker_ref.update.call_args[0][0]
        expected_lost = int(attacker_treasury * 0.20)
        assert attacker_update['treasury'] == attacker_treasury - expected_lost
        
        # Проверяем, что вывелся текст о "по лицу от админской мощи"
        assert "получили по лицу от админской мощи" in msg.answer.call_args[0][0]


# --- Группа 3: Доступ Создателя к суду без назначенного судьи (10 тестов) ---
# Проверяем 10 вариаций, где Создатель (999) выносит приговор при разных суммах штрафа,
# даже если судья в чате не назначен (None) или назначен кто-то другой (888).

judge_test_cases = [
    # (chat_judge_id, fine_amount, expected_balance)
    (None, 1000, 1000),
    (888, 500, 500),
    (None, 99999, 99999),
    (777, 100, 100),
    (None, 1, 1),
    (111, 2500, 2500),
    (None, 15000, 15000),
    (222, 900, 900),
    (None, 4321, 4321),
    (555, 12345, 12345),
]

@pytest.mark.parametrize("chat_judge_id, fine_amount, expected_balance", judge_test_cases)
@pytest.mark.asyncio
async def test_creator_can_judge_always(chat_judge_id, fine_amount, expected_balance):
    msg = create_mock_message(f"/judge {fine_amount}", user_id=999, target_id=222, is_reply=True)
    
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=chat_judge_id), \
         patch("court.update_user_balance", new_callable=AsyncMock, return_value=True) as mock_update:
         
        await court.cmd_judge(msg)
        
        # Проверяем, что баланс успешно обновился, несмотря на отсутствие прав судьи в чате
        mock_update.assert_called_once_with(123, 222, -fine_amount, min_balance=0)
        assert "СУДЕБНЫЙ ПРИГОВОР" in msg.answer.call_args[0][0]
