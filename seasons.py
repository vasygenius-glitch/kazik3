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
    db = get_db()
    await db.collection('bot_settings').document('season').set(SEASON_1_CONFIG)
    global_cache.delete("current_season")
    
    # Торжественный текст анонса
    announce_text = (
        "✨ <b>ТОРЖЕСТВЕННОЕ ОТКРЫТИЕ 1 СЕЗОНА</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🌀 <b>ТЕМА:</b> <code>ЗАКУЛИСЬЕ / BACKROOMS</code>\n"
        "⏳ <b>СРОК:</b> <code>30 ДНЕЙ</code>\n\n"
        "🚪 <b>ГРАНИЦА РЕАЛЬНОСТИ СТЕРТА.</b>\n"
        "Вы провалились в бесконечные лабиринты... Здесь не работают привычные законы физики и экономики. \n\n"
        "📉 <b>КРИЗИС:</b> Доходы от работ снижены на 30%.\n"
        "🍶 <b>ШАНС:</b> Ищите миндальную воду для выживания.\n"
        "👾 <b>РИСК:</b> Опасайтесь сущностей во тьме.\n\n"
        "<i>Это будет долгий месяц. Готов ли ты сохранить рассудок?</i>\n\n"
        "👉 Начни выживание: <code>/season</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    from whitelist import get_whitelist
    whitelist = await get_whitelist()
    
    count = 0
    for chat_id in whitelist:
        try:
            await message.bot.send_message(chat_id=chat_id, text=announce_text)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
            
    await message.answer(f"🎊 <b>Сезон 1 торжественно запущен!</b>\nРассылка завершена для <b>{count}</b> чатов.")

# --- СИСТЕМНАЯ АДАПТАЦИЯ (ТЕМАТИЗАЦИЯ) ---
async def get_season_string(key: str, default: str) -> str:
    """Адаптирует системные строки под тему текущего сезона."""
    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "season_1_backrooms":
        return default
    
    mapping = {
        "tax": "📦 Утечка реальности (Налог)",
        "balance": "🔋 Энергия (Баланс)",
        "shop": "🏚️ Склад Забытых Вещей",
        "shop_biz": "🏗️ Заброшенные объекты",
        "shop_cars": "🚲 Средства побега",
        "work": "🔦 Исследование коридоров",
        "crime": "👣 Мародерство во тьме",
        "bonus": "🍶 Запас Миндальной Воды"
    }
    return mapping.get(key, default)

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
