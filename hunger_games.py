import random
import asyncio
import time
import secrets

s_random = secrets.SystemRandom()
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html
from user_manager import get_user_data, update_user_balance, update_user_field
from config import CREATOR_ID

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
    
    if not message.reply_to_message:
        return await message.answer("Сделайте реплай на будущего Фронтмена.")
    
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)
    
    await update_user_field(message.chat.id, target_id, 'is_frontman', True)
    await message.answer(f"🎭 <b>{target_name}</b> теперь официально <b>Фронтмен</b> голодных игр!")

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
    
    # Списание ставки
    data = await get_user_data(chat_id, user_id)
    if data.get('balance', 0) < game['bet']:
        return await callback.answer("У вас недостаточно сыроежек для взноса!", show_alert=True)
    
    await update_user_balance(chat_id, user_id, -game['bet'])
    
    game['players'].append({
        'id': user_id,
        'name': callback.from_user.full_name,
        'health': 100,
        'items': []
    })
    
    await callback.answer("Вы вступили в Голодные Игры! Да пребудет с вами удача.")
    
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

async def run_hg_simulation(chat_id: int, message: types.Message, bot: Bot):
    game = active_hg.get(chat_id)
    if not game: return

    players = game['players']
    # Гарантируем наличие здоровья у всех участников
    for p in players:
        p['health'] = 100

    bet = game['bet']
    initial_count = len(players)
    
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
    total_pool = bet * initial_count
    
    frontman_fee = int(total_pool * 0.05)
    prize = total_pool - frontman_fee
    
    await update_user_balance(chat_id, winner['id'], prize)
    await update_user_balance(chat_id, game['host_id'], frontman_fee)
    
    if chat_id in active_hg:
        del active_hg[chat_id]
    
    await message.answer(
        f"👑 <b>ПОБЕДИТЕЛЬ ГОЛОДНЫХ ИГР — {escape_html(winner['name'])}!</b>\n\n"
        f"💰 Выигрыш: <b>{prize}</b> сыр.\n"
        f"🎭 Фронтмен {escape_html(game['host_name'])} получил <b>{frontman_fee}</b> за организацию."
    )
