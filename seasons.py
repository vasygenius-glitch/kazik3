import time
from aiogram import Router, F, types
from aiogram.filters import Command
from db import get_db
from utils_pkg.cache_manager import global_cache

router = Router()

# Дефолтный конфиг сезона (затычка, которую легко менять)
DEFAULT_SEASON = {
    "id": "backrooms_v1",
    "name": "Закулисье (Backrooms)",
    "emoji": "🚪🏚️",
    "description": "Вы застряли в бесконечных желтых коридорах. Время собирать сыр среди сырых стен!",
    "bonus_target": "crime", # На что действует бонус (work/crime/games)
    "multiplier": 1.25,      # Множитель +25%
    "end_time": int(time.time()) + 86400 * 7, # Конец через неделю
    "active": False
}

async def get_season_config():
    """Получает текущие настройки сезона из кэша или БД."""
    cached = global_cache.get("current_season")
    if cached: return cached
    
    db = get_db()
    doc = await db.collection('bot_settings').document('season').get()
    if doc.exists:
        data = doc.to_dict()
    else:
        data = DEFAULT_SEASON
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
        f"{cfg['emoji']} <b>ТЕКУЩИЙ СЕЗОН: {cfg['name']}</b> {cfg['emoji']}\n\n"
        f"📝 <b>О событии:</b> {cfg['description']}\n\n"
        f"🎁 <b>Бустеры:</b> +{int((cfg['multiplier']-1)*100)}% к заработку через <code>/{cfg['bonus_target']}</code>\n"
        f"⏳ До конца осталось: <b>{days}д. {hours}ч.</b>\n\n"
        f"<i>Успей накопить как можно больше сыра в тематике этого сезона!</i>"
    )
    
    # Можно добавить кнопку "Магазин сезона" в будущем
    await message.answer(text)

# Функция для применения бонусов в других модулях
async def apply_season_bonus(base_value: int, target_type: str) -> int:
    cfg = await get_season_config()
    if cfg.get("active") and cfg.get("bonus_target") == target_type:
        return int(base_value * cfg.get("multiplier", 1.0))
    return base_value
