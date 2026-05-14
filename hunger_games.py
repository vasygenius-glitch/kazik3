import random
import asyncio
import time
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html
from user_manager import get_user_data, update_user_balance, update_user_field
from config import CREATOR_ID

router = Router()

# Состояния игр: {chat_id: {state: 'lobby/running', participants: [], bet: 0, host_id: 0}}
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

@router.message(Command("hg_create"))
@router.message(F.text.lower().startswith("создать ги"))
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
        'participants': [], # List of {id: int, name: str}
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
    
    if any(p['id'] == user_id for p in game['participants']):
        return await callback.answer("Вы уже в списке трибутов.", show_alert=True)
    
    if len(game['participants']) >= 10:
        return await callback.answer("Арена переполнена! Максимум 10 человек.", show_alert=True)
    
    # Списание ставки
    data = await get_user_data(chat_id, user_id)
    if data.get('balance', 0) < game['bet']:
        return await callback.answer("У вас недостаточно сыроежек для взноса!", show_alert=True)
    
    await update_user_balance(chat_id, user_id, -game['bet'])
    
    game['participants'].append({
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
        f"👥 Игроков: <b>{len(game['participants'])} / 10</b>\n\n"
        f"<b>Список участников:</b>\n" + 
        "\n".join([f"— {escape_html(p['name'])}" for p in game['participants']]),
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
    
    if len(game['participants']) < 3:
        return await callback.answer("Нужно минимум 3 трибута для начала резни!", show_alert=True)
    
    game['state'] = 'running'
    await callback.message.edit_text("🔔 <b>ГОНГ ПРОЗВУЧАЛ! ТРИБУТЫ БЕГУТ К РОГУ ИЗОБИЛИЯ!</b>")
    
    # Запускаем симуляцию
    asyncio.create_task(run_hg_simulation(chat_id, callback.message, bot))

@router.message(Command("hg_cancel"))
@router.message(F.text.lower().startswith("отменить ги"))
async def cmd_hg_cancel(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in active_hg:
        return await message.answer("❌ В этом чате нет активных Голодных Игр.")

    game = active_hg[chat_id]

    # Только Фронтмен или Создатель может отменить
    if not await is_frontman(chat_id, user_id):
        return await message.answer("❌ Только Фронтмен или Создатель может отменить игры.")

    if game['state'] != 'lobby':
        return await message.answer("❌ Игра уже началась, отмена невозможна!")

    # Возврат ставок
    for p in game['participants']:
        await update_user_balance(chat_id, p['id'], game['bet'])

    del active_hg[chat_id]
    await message.answer("🚫 <b>Голодные Игры отменены Фронтменом.</b> Все взносы возвращены.")

async def run_hg_simulation(chat_id: int, message: types.Message, bot: Bot):
    game = active_hg[chat_id]
    # Используем копию списка участников для симуляции
    players = list(game['participants'])
    bet = game['bet']
    
    events = [
        "{p1} нашел заржавевший меч и чувствует себя увереннее.",
        "{p1} наступил на ловушку и потерял 30 HP.",
        "{p1} и {p2} вступили в схватку! {p1} победил, оставив {p2} истекать кровью.",
        "{p1} спрятался в кустах и съел лечебные ягоды (+20 HP).",
        "{p1} выследил {p2} и прикончил его точным броском копья!",
        "{p1} упал с обрыва, пытаясь достать припасы. Минус 50 HP.",
        "{p1} объединился с {p2}, но ночью {p1} предал напарника!",
        "Дикие звери напали на {p1}! Он чудом спасся, но потерял много крови.",
        "{p1} нашел спонсорскую посылку с едой."
    ]
    
    kill_events = [
        "💀 {p1} зверски убит {p2}!",
        "💀 {p1} не пережил холодную ночь на арене.",
        "💀 {p1} подорвался на мине у Рога Изобилия.",
        "💀 {p1} проиграл дуэль с {p2} и испустил дух."
    ]

    while len(players) > 1:
        await asyncio.sleep(4)
        
        # Выбираем случайное событие
        if random.random() < 0.4 and len(players) >= 2: # Шанс смерти
            p1_idx = random.randrange(len(players))
            victim = players.pop(p1_idx)
            killer = random.choice(players)
            
            evt = random.choice(kill_events).format(p1=escape_html(victim['name']), p2=escape_html(killer['name']))
            await message.answer(evt)
        else:
            p1 = random.choice(players)
            p2 = random.choice(players) if len(players) > 1 else p1
            
            evt = random.choice(events).format(p1=escape_html(p1['name']), p2=escape_html(p2['name']))
            await message.answer(f"🏃 {evt}")

    # Победитель
    winner = players[0]
    total_pool = bet * (len(game['participants']))
    
    # Фронтмен получает 5% за организацию (не имбово, но приятно)
    frontman_fee = int(total_pool * 0.05)
    prize = total_pool - frontman_fee
    
    await update_user_balance(chat_id, winner['id'], prize)
    await update_user_balance(chat_id, game['host_id'], frontman_fee)
    
    del active_hg[chat_id]
    
    await message.answer(
        f"👑 <b>ПОБЕДИТЕЛЬ ГОЛОДНЫХ ИГР — {escape_html(winner['name'])}!</b>\n\n"
        f"💰 Выигрыш: <b>{prize}</b> сыр.\n"
        f"🎭 Фронтмен {escape_html(game['host_name'])} получил <b>{frontman_fee}</b> за зрелищность."
    )
