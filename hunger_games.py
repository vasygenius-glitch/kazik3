import secrets
s_random = secrets.SystemRandom()
import random
import asyncio
import time
import secrets

s_random = secrets.SystemRandom()
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html
from user_manager import (
    get_user_data, update_user_balance, update_user_field,
    update_user_balance_tr, get_user_ref, safe_get_snapshot
)
from config import CREATOR_ID
from db import get_db
from firebase_admin import firestore_async

router = Router()

# Состояния игр: {chat_id: {state: 'lobby/running', players: [], bet: 0, host_id: 0}}
active_hg = {}

# --- ПРОВЕРКИ ---
async def is_frontman(chat_id: int, user_id: int) -> bool:
    if str(user_id) == str(CREATOR_ID):
        return True
    data = await get_user_data(chat_id, user_id)
    return data.get('is_frontman', False)

@router.message(Command("фронтмен"))
async def cmd_assign_frontman(message: types.Message):
    if str(message.from_user.id) != str(CREATOR_ID):
        return await message.answer("❌ Только Создатель может назначать Фронтменов.")
    
    target_id = None
    target_name = None
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)
    else:
        args = message.text.split()
        if len(args) < 2:
            return await message.answer("Использование: <code>/фронтмен [реплай | ID | @username]</code>")

        from user_manager import get_user_by_username_or_id
        target_id, target_data = await get_user_by_username_or_id(message.chat.id, args[1])
        if not target_id:
            return await message.answer("❌ Пользователь не найден в этом чате.")
        target_name = escape_html(target_data.get('full_name', f"ID: {target_id}"))
    
    await update_user_field(message.chat.id, target_id, 'is_frontman', True)
    await message.answer(f"🎭 <b>{target_name}</b> теперь официально <b>Фронтмен</b> голодных игр!")

@router.message(Command("убрать_фронтмена"))
async def cmd_remove_frontman(message: types.Message):
    if str(message.from_user.id) != str(CREATOR_ID):
        return await message.answer("❌ Только Создатель может снимать Фронтменов.")

    target_id = None
    target_name = None

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)
    else:
        args = message.text.split()
        if len(args) < 2:
            return await message.answer("Использование: <code>/убрать_фронтмена [реплай | ID | @username]</code>")

        from user_manager import get_user_by_username_or_id
        target_id, target_data = await get_user_by_username_or_id(message.chat.id, args[1])
        if not target_id:
            return await message.answer("❌ Пользователь не найден в этом чате.")
        target_name = escape_html(target_data.get('full_name', f"ID: {target_id}"))

    await update_user_field(message.chat.id, target_id, 'is_frontman', False)
    await message.answer(f"🎭 С <b>{target_name}</b> снята маска <b>Фронтмена</b>.")

@router.message(F.text.lower().startswith("/hg_create") | F.text.lower().startswith("создать ги"))
async def cmd_hg_create(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if not await is_frontman(chat_id, user_id):
        return await message.answer("❌ У вас нет маски Фронтмена для проведения этих игр.")
    
    if chat_id in active_hg:
        return await message.answer("❌ В этом чате уже идет подготовка или проведение игр.")
    
    args = message.text.split()
    try:
        bet = int(args[1]) if len(args) > 1 else 1000
        if bet < 100: bet = 100
    except ValueError:
        return await message.answer("Ставка должна быть числом.")
    
    active_hg[chat_id] = {
        'state': 'lobby',
        'players': [], # List of {id: int, name: str}
        'bet': bet,
        'host_id': user_id,
        'host_name': message.from_user.full_name,
        'expires': time.time() + 300
    }
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Вступить в игру 🗡", callback_data=f"hg_join_{chat_id}")
    
    await message.answer(
        f"🏆 <b>ГОЛОДНЫЕ ИГРЫ НАЧИНАЮТСЯ!</b>\n\n"
        f"🎭 Организатор: <b>{escape_html(message.from_user.full_name)}</b>\n"
        f"💰 Взнос: <b>{bet}</b> сыр.\n"
        f"👥 Игроков: <b>0 / 10</b> (Минимум 3)\n\n"
        f"Жмите кнопку ниже, чтобы рискнуть жизнью ради сыра!",
        reply_markup=builder.as_markup()
    )

@firestore_async.transactional
async def distribute_prizes_tr(transaction, chat_id, winner_id, prize, host_id, fee, winner_diseases):
    # 1. Начисляем приз победителю
    await update_user_balance_tr(transaction, chat_id, winner_id, prize)
    # 2. Начисляем комиссию фронтмену
    await update_user_balance_tr(transaction, chat_id, host_id, fee)

    # 3. Синхронизируем болезни победителя (если он заразился ВИЧ в процессе)
    if 'hiv' in winner_diseases:
        ref = get_user_ref(chat_id, winner_id)
        snapshot = await safe_get_snapshot(transaction, ref)
        if snapshot.exists:
            data = snapshot.to_dict()
            d_dict = data.get('diseases', {}).copy()
            if 'hiv' not in d_dict:
                d_dict['hiv'] = time.time() + 3600 # На час
                transaction.update(ref, {'diseases': d_dict})

                from user_manager import set_in_cache, mark_dirty
                data['diseases'] = d_dict
                set_in_cache(chat_id, winner_id, data)
                mark_dirty(chat_id, winner_id)

@firestore_async.transactional
async def join_hg_tr(transaction, chat_id, user_id, base_bet):
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return None, "Пользователь не найден"

    data = snapshot.to_dict()
    is_vip = data.get('is_vip', False)
    # VIP скидка 20%
    bet = int(base_bet * 0.8) if is_vip else base_bet

    if data.get('balance', 0) < bet:
        return None, "Недостаточно сыроежек для взноса!"

    # Проверка на презерватив (дает защиту от болезней в игре)
    inventory = data.get('inventory', {}).copy()
    has_condom = inventory.get('condom', 0) > 0
    if has_condom:
        inventory['condom'] -= 1
        if inventory['condom'] <= 0:
            del inventory['condom']

    new_balance = data.get('balance', 0) - bet

    updates = {
        'balance': new_balance,
        'inventory': inventory
    }
    transaction.update(ref, updates)

    # Синхронизация кэша
    from user_manager import set_in_cache, mark_dirty
    data['balance'] = new_balance
    data['inventory'] = inventory
    set_in_cache(chat_id, user_id, data)
    mark_dirty(chat_id, user_id)

    # Получаем активные болезни
    diseases_dict = data.get('diseases', {})
    current_time = time.time()
    active_diseases = [d for d, exp in diseases_dict.items() if current_time < exp]

    return {
        'id': user_id,
        'name': data.get('full_name', 'Трибут'),
        'health': 100,
        'is_vip': is_vip,
        'has_condom': has_condom,
        'diseases': active_diseases,
        'bet_paid': bet
    }, None

@router.callback_query(F.data.startswith("hg_join_"))
async def cb_hg_join(callback: types.CallbackQuery):
    chat_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if chat_id not in active_hg:
        return await callback.answer("Игры уже закончились или не начинались.", show_alert=True)
    
    game = active_hg[chat_id]
    if game['state'] != 'lobby':
        return await callback.answer("Игра уже в процессе!", show_alert=True)
    
    if any(p['id'] == user_id for p in game['players']):
        return await callback.answer("Вы уже в списке трибутов.", show_alert=True)
    
    if len(game['players']) >= 10:
        return await callback.answer("Арена переполнена! Максимум 10 человек.", show_alert=True)
    
    # Списание ставки через транзакцию
    db = get_db()
    try:
        player_data, error = await join_hg_tr(db.transaction(), chat_id, user_id, game['bet'])
        if error:
            return await callback.answer(error, show_alert=True)

        game['players'].append(player_data)
        await callback.answer("Вы вступили в Голодные Игры! Да пребудет с вами удача.")
    except Exception as e:
        print(f"HG Join Error: {e}")
        return await callback.answer("Произошла ошибка при вступлении.", show_alert=True)
    
    # Обновляем сообщение
    builder = InlineKeyboardBuilder()
    builder.button(text="Вступить в игру 🗡", callback_data=f"hg_join_{chat_id}")
    if user_id == game['host_id']: # Фронтмен может нажать старт
        builder.button(text="НАЧАТЬ ЖАТВУ 🩸", callback_data=f"hg_start_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"🏆 <b>ГОЛОДНЫЕ ИГРЫ: СБОР ТРИБУТОВ</b>\n\n"
        f"🎭 Организатор: <b>{escape_html(game['host_name'])}</b>\n"
        f"💰 Взнос: <b>{game['bet']}</b> сыр.\n"
        f"👥 Игроков: <b>{len(game['players'])} / 10</b>\n\n"
        f"<b>Список участников:</b>\n" + 
        "\n".join([f"— {escape_html(p['name'])}" for p in game['players']]),
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("hg_start_"))
async def cb_hg_start(callback: types.CallbackQuery, bot: Bot):
    chat_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if chat_id not in active_hg: return
    game = active_hg[chat_id]
    
    if user_id != game['host_id']:
        return await callback.answer("Только Фронтмен может дать сигнал к началу!", show_alert=True)
    
    if len(game['players']) < 3:
        return await callback.answer("Нужно минимум 3 трибута для начала резни!", show_alert=True)
    
    game['state'] = 'running'
    await callback.message.edit_text("🔔 <b>ГОНГ ПРОЗВУЧАЛ! ТРИБУТЫ БЕГУТ К РОГУ ИЗОБИЛИЯ!</b>")
    
    # Запускаем симуляцию
    asyncio.create_task(run_hg_simulation(chat_id, callback.message, bot))


@router.message(Command("hg_cancel") | F.text.lower().startswith("отменить ги"))
async def cmd_hg_cancel(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in active_hg:
        return await message.answer("❌ В этом чате нет активных Голодных Игр.")

    game = active_hg[chat_id]

    # Только Создатель или текущий Фронтмен-организатор могут отменить
    if str(user_id) != str(CREATOR_ID) and user_id != game['host_id']:
        return await message.answer("❌ Только организатор этих игр или Создатель могут их отменить.")

    if game['state'] != 'lobby':
        return await message.answer("❌ Игры уже начались, отменить нельзя!")

    # Возврат ставок
    db = get_db()
    for p in game['players']:
        await update_user_balance(chat_id, p['id'], p.get('bet_paid', game['bet']))

    del active_hg[chat_id]
    await message.answer("🛑 <b>ГОЛОДНЫЕ ИГРЫ ОТМЕНЕНЫ!</b> Все взносы возвращены участникам.")

async def run_hg_simulation(chat_id: int, message: types.Message, bot: Bot):
    game = active_hg.get(chat_id)
    if not game: return

    players = game['players'].copy()
    # Гарантируем наличие здоровья у всех участников
    for p in players:
        p['health'] = 100

    bet = game['bet']
    initial_count = len(players)

    # Считаем общий пул на основе фактически списанных ставок (у VIP меньше взнос, но пул честный)
    total_pool = sum(p.get('bet_paid', bet) for p in game['players'])
    
    # Расширенный список событий с влиянием на HP
    events = [
        {"text": "🍎 {p1} нашел спонсорскую посылку с едой (+25 HP).", "hp": 25, "target": "p1"},
        {"text": "🗡 {p1} ранил {p2} в честной дуэли (-35 HP).", "hp": -35, "target": "p2"},
        {"text": "🏹 {p1} подстрелил {p2} из засады (-30 HP).", "hp": -30, "target": "p2"},
        {"text": "🪵 {p1} наступил на шипы в лесу (-20 HP).", "hp": -20, "target": "p1"},
        {"text": "🧗 {p1} упал с крутого склона (-40 HP).", "hp": -40, "target": "p1"},
        {"text": "🐍 {p1} укусила гадюка (-15 HP).", "hp": -15, "target": "p1"},
        {"text": "🍓 {p1} нашел лечебные ягоды (+15 HP).", "hp": 15, "target": "p1"},
        {"text": "🔥 {p1} случайно обжегся, разводя костер (-10 HP).", "hp": -10, "target": "p1"},
        {"text": "💧 {p1} утолил жажду из чистого ручья (+10 HP).", "hp": 10, "target": "p1"},
        {"text": "🐝 На {p1} напал рой диких ос (-25 HP).", "hp": -25, "target": "p1"},
        {"text": "⚡️ В {p1} чуть не попала молния! (-30 HP).", "hp": -30, "target": "p1"},
        {"text": "🍄 {p1} съел подозрительный гриб... (-20 HP).", "hp": -20, "target": "p1"},
        {"text": "🎁 Спонсоры прислали {p1} бинты (+40 HP).", "hp": 40, "target": "p1"},
        {"text": "🔪 {p1} и {p2} сцепились в рукопашную! {p1} ранил {p2} (-25 HP).", "hp": -25, "target": "p2"},
        {"text": "🐺 Дикие звери напали на {p1}! (-45 HP).", "hp": -45, "target": "p1"},
    ]

    main_msg = await message.answer("🚀 <b>Игры начались! Высадка на арену...</b>")
    round_num = 1
    all_logs = []

    while len(players) > 1:
        await asyncio.sleep(5)
        
        current_round_logs = [f"📅 <b>ДЕНЬ {round_num}</b>"]
        # Шанс случайного заражения ЗППП (если не VIP и нет защиты)
        if s_random.random() < 0.15:
            p = s_random.choice(players)
            if not p.get('is_vip') and not p.get('has_condom'):
                if 'hiv' not in p.get('diseases', []):
                    if 'diseases' not in p: p['diseases'] = []
                    p['diseases'].append('hiv')
                    current_round_logs.append(f"🤮 <b>{escape_html(p['name'])}</b> наступил на зараженную иглу! Кажется, это ВИЧ...")

        # Количество событий зависит от числа игроков
        num_events = s_random.randint(2, 3) if len(players) > 4 else 2

        for _ in range(num_events):
            if len(players) <= 1: break

            evt = s_random.choice(events)
            p1 = s_random.choice(players)
            others = [p for p in players if p['id'] != p1['id']]
            p2 = s_random.choice(others) if others else p1
            
            target = p1 if evt['target'] == 'p1' else p2
            target['health'] += evt['hp']
            if target['health'] > 100: target['health'] = 100
            
            log_entry = evt['text'].format(p1=escape_html(p1['name']), p2=escape_html(p2['name']))

            if target['health'] <= 0:
                target['health'] = 0
                log_entry += f"\n💀 <b>{escape_html(target['name'])} ПОГИБ!</b>"
                players.remove(target)

            current_round_logs.append(log_entry)

        # Формируем статус выживших
        status = "\n📊 <b>Живые:</b>\n" + "\n".join([f"— {escape_html(p['name'])} ({p['health']} HP)" for p in players])

        # Храним только последние 2 дня в одном сообщении для компактности
        all_logs.append("\n".join(current_round_logs))
        if len(all_logs) > 2:
            all_logs.pop(0)

        full_text = "🏆 <b>ГОЛОДНЫЕ ИГРЫ В РАЗГАРЕ</b>\n\n" + "\n\n".join(all_logs) + "\n" + status

        try:
            await main_msg.edit_text(full_text)
        except Exception:
            # Если сообщение нельзя редактировать, отправляем новое
            main_msg = await message.answer(full_text)

        round_num += 1

    # Завершение игры
    winner = players[0]
    # Фронтмен получает 5% за организацию
    frontman_fee = int(total_pool * 0.05)
    prize = total_pool - frontman_fee
    
    # Транзакционное начисление
    db = get_db()
    try:
        await distribute_prizes_tr(db.transaction(), chat_id, winner['id'], prize, game['host_id'], frontman_fee, winner.get('diseases', []))
    except Exception as e:
        print(f"HG Prize Distribution Error: {e}")
        # Если транзакция упала, попробуем обычный баланс (fallback)
        await update_user_balance(chat_id, winner['id'], prize)
        await update_user_balance(chat_id, game['host_id'], frontman_fee)

    if chat_id in active_hg:
        del active_hg[chat_id]
    
    await message.answer(
        f"👑 <b>ПОБЕДИТЕЛЬ ГОЛОДНЫХ ИГР — {escape_html(winner['name'])}!</b>\n\n"
        f"💰 Выигрыш: <b>{prize}</b> сыр.\n"
        f"🎭 Фронтмен {escape_html(game['host_name'])} получил <b>{frontman_fee}</b> за организацию."
    )
