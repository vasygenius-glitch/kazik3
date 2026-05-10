import time
import random
from aiogram import Router, F, types
from aiogram.filters import Command
from db import get_db
from utils_pkg.cache_manager import global_cache
from user_manager import update_user_balance

router = Router()

# КОНФИГУРАЦИЯ СЕЗОНА 1
SEASON_1_CONFIG = {
    "id": "season_1_backrooms",
    "name": "СЕЗОН 1: ЗАКУЛИСЬЕ (LEVEL 0)",
    "emoji": "💊🚪🏚️",
    "description": (
        "Вы провалились сквозь текстуры реальности. Бесконечные желтые коридоры, гул ламп и сырость. "
        "В этом месяце выживание важнее прибыли. \n\n"
        "⚠️ <b>ХАРДКОР:</b> Реальность нестабильна. Доходы от обычной работы снижены на 30%. "
        "Но есть шанс найти Миндальную Воду или ценные артефакты!"
    ),
    "bonus_target": "exploration", 
    "multiplier": 0.7, # ПЕНАЛЬТИ: -30% к доходам (Хардкор)
    "end_time": int(time.time()) + 86400 * 30, # 1 Месяц
    "active": True
}

async def get_season_config():
    cached = global_cache.get("current_season")
    if cached: return cached
    
    db = get_db()
    doc = await db.collection('bot_settings').document('season').get()
    if doc.exists:
        data = doc.to_dict()
    else:
        data = SEASON_1_CONFIG
        await db.collection('bot_settings').document('season').set(data)
    
    global_cache.set("current_season", data, ttl=300)
    return data

@router.message(Command("season", "сезон"))
async def cmd_season(message: types.Message):
    cfg = await get_season_config()
    if not cfg.get("active"):
        return await message.answer("⏸ Сейчас нет активного сезона. Ждите анонсов!")
    
    remain = cfg['end_time'] - int(time.time())
    days = remain // 86400
    hours = (remain % 86400) // 3600
    
    text = (
        f"🏆 <b>{cfg['name']}</b> 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{cfg['description']}\n\n"
        f"📊 <b>ВЛИЯНИЕ НА МИР:</b>\n"
        f"📉 Базовый заработок: <b>-30%</b> (Аномалия)\n"
        f"🍀 Шанс на Миндальную Воду: <b>15%</b>\n"
        f"👾 Шанс встретить Сущность: <b>5%</b> (Штраф)\n\n"
        f"⏳ Осталось: <b>{days}д. {hours}ч.</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Используйте /work и /crime, чтобы искать выход!</i>"
    )
    await message.answer(text)

@router.message(Command("start_season_1"))
async def cmd_start_season_1(message: types.Message):
    # Только для админа (проверка по ID или правам, тут упрощено)
    # if message.from_user.id != ADMIN_ID: return
    
    db = get_db()
    await db.collection('bot_settings').document('season').set(SEASON_1_CONFIG)
    global_cache.delete("current_season")
    
    announce = (
        "📢 <b>ВНИМАНИЕ! ОБЪЯВЛЕНО НАЧАЛО 1 СЕЗОНА!</b>\n\n"
        "🌑 <b>ТЕМА: ЗАКУЛИСЬЕ (BACKROOMS)</b> 🌑\n"
        "🗓 <b>СРОК: 1 МЕСЯЦ</b>\n\n"
        "Мир изменился. Теперь за каждым углом может ждать опасность, а деньги добывать стало в разы сложнее.\n"
        "Готовы ли вы выжить в 1 сезоне?\n\n"
        "👉 Пиши <code>/season</code> чтобы узнать подробности!"
    )
    await message.answer(announce)

# Улучшенная логика бонусов/штрафов
async def apply_season_logic(chat_id: int, user_id: int, base_value: int) -> tuple[int, str]:
    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "season_1_backrooms":
        return base_value, ""
    
    # 1. Применяем пенальти сезона (Хардкор)
    final_value = int(base_value * cfg.get("multiplier", 1.0))
    msg = ""
    
    # 2. Случайные события сезона
    rnd = random.random()
    
    if rnd < 0.15: # Миндальная вода (Бонус)
        bonus = random.randint(5000, 15000)
        await update_user_balance(chat_id, user_id, bonus)
        msg = f"\n\n🍶 <b>ВЫ НАШЛИ МИНДАЛЬНУЮ ВОДУ!</b> Вы восстановили силы и получили бонус <b>+{bonus}</b> сыр.!"
    elif rnd < 0.20: # Сущность (Штраф)
        penalty = random.randint(3000, 7000)
        await update_user_balance(chat_id, user_id, -penalty)
        msg = f"\n\n👾 <b>СУЩНОСТЬ ЗАМЕТИЛА ВАС!</b> Убегая, вы обронили <b>-{penalty}</b> сыр.!"
    
    return final_value, msg
