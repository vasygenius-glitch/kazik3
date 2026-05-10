import time
import random
import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command
from db import get_db
from utils_pkg.cache_manager import global_cache
from user_manager import update_user_balance

router = Router()

# --- ШАБЛОНЫ СЕЗОНОВ ---
SEASON_TEMPLATES = {
    "backrooms": {
        "id": "backrooms",
        "name": "СЕЗОН 1: ЗАКУЛИСЬЕ (LEVEL 0)",
        "emoji": "💊🚪🏚️",
        "description": (
            "Вы провалились сквозь текстуры реальности.\n\n"
            "⚠️ <b>ХАРДКОР:</b> Доходы от обычной работы снижены на 30%. "
            "Но есть шанс найти Миндальную Воду или ценные артефакты!\n\n"
            "📊 <b>ВЛИЯНИЕ НА МИР:</b>\n"
            "📉 Базовый заработок: -30%\n"
            "🍀 Шанс на Миндальную Воду: 15%\n"
            "👾 Шанс встретить Сущность: 5% (Штраф)"
        ),
        "multiplier": 0.7,
        "glitch_chance": 0.1, # 10% шанс на глитч в тексте
        "strings": {
            "tax": "📦 Утечка реальности (Налог)",
            "balance": "🔋 Энергия (Баланс)",
            "shop": "🏚️ Склад Забытых Вещей",
            "shop_biz": "🏗️ Заброшенные объекты",
            "shop_cars": "🚲 Средства побега",
            "work": "🔦 Исследование коридоров",
            "crime": "👣 Мародерство во тьме",
            "bonus": "🍶 Запас Миндальной Воды",
            "profile": "ЛИЧНОЕ ДЕЛО ВЫЖИВШЕГО",
            "bank_label": "📦 Хранилище",
            "bank_title": "🛡️ БЕЗОПАСНЫЕ ХАБЫ",
            "top_winner": "ЛУЧШИЙ ВЫЖИВШИЙ",
            "bj_start": "🎰 КАЗИНО 'ПУСТОТА'",
            "bj_win": "💎 ВЫБРОС ЭНЕРГИИ!",
            "roulette_start": "🌀 ВИХРЬ РЕАЛЬНОСТИ...",
            "job_list": ["искал выход в желтых коридорах", "собирал миндальную воду", "чистил гудящие лампы", "рисовал карту уровня 0"],
            "stocks": {
                "MWTR": {"name": "MandelWater Inc (MWTR)", "desc": "Главный поставщик миндальной воды в Закулисье."},
                "LMP": {"name": "LightGlow (LMP)", "desc": "Производитель бесконечно гудящих ламп."},
            }
        },
        "seasonal_disease": {"id": "reality_flu", "name": "Грипп Реальности", "desc": "Ваше тело мерцает. 20% шанс, что сообщение в чате превратится в глитч."},
        "events": [
            {"chance": 0.15, "msg": "\n\n🍶 <b>ВЫ НАШЛИ МИНДАЛЬНУЮ ВОДУ!</b> +{value} сыр.", "range": (5000, 15000)},
            {"chance": 0.05, "msg": "\n\n👾 <b>СУЩНОСТЬ ЗАМЕТИЛА ВАС!</b> -{value} сыр.", "range": (3000, 7000), "is_penalty": True},
            {"chance": 0.08, "msg": "\n\n🎒 <b>ВЫ НАШЛИ ЗАБЫТЫЙ РЮКЗАК!</b> Внутри было +{value} сыр.", "range": (2000, 8000)},
            {"chance": 0.04, "msg": "\n\n🔘 <b>СТРАННАЯ КНОПКА:</b> Вы нажали на нее и получили +{value} сыр. из ниоткуда.", "range": (10000, 25000)},
            {"chance": 0.03, "msg": "\n\n🔦 <b>СТАРЫЙ ФОНАРИК:</b> Вы продали его другому выжившему за +{value} сыр.", "range": (1000, 5000)},
            {"chance": 0.02, "msg": "\n\n🧩 <b>ГЛЮЧНЫЙ ЧИП:</b> Он странно вибрирует... Вы получили +{value} сыр.", "range": (30000, 50000)}
        ]
    }
}

async def get_season_config():
    cached = global_cache.get("current_season")
    if cached: return cached
    
    db = get_db()
    doc = await db.collection('bot_settings').document('season').get()
    if doc.exists:
        data = doc.to_dict()
    else:
        data = {"active": False}
        await db.collection('bot_settings').document('season').set(data)
    
    global_cache.set("current_season", data, ttl=300)
    return data

@router.message(Command("season", "сезон"))
async def cmd_season(message: types.Message):
    cfg = await get_season_config()
    if not cfg.get("active"):
        return await message.answer("⏸ Сейчас нет активного сезона. Ждите анонсов!")
    
    remain = cfg.get('end_time', 0) - int(time.time())
    if remain < 0:
        return await message.answer("🏁 Сезон подошел к концу! Подводим итоги...")

    days = remain // 86400
    hours = (remain % 86400) // 3600
    
    mult_percent = int((cfg.get('multiplier', 1.0) - 1.0) * 100)
    mult_text = f"📈 <b>+{mult_percent}%</b>" if mult_percent > 0 else f"📉 <b>{mult_percent}%</b>"
    if mult_percent == 0: mult_text = "📊 Стабильность"

    text = (
        f"🏆 <b>{cfg['name']}</b> 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{cfg['description']}\n\n"
        f"⏳ Осталось: <b>{days}д. {hours}ч.</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Используйте /work и /crime, чтобы искать выход!</i>"
    )
    await message.answer(text)

@router.message(Command("set_season", "start_season_1"))
async def cmd_set_season(message: types.Message):
    if message.from_user.id not in [6154129759]: return
    
    args = message.text.split()
    if message.text.startswith("/start_season_1"):
        season_id = "backrooms"
    elif len(args) < 2:
        keys = ", ".join(SEASON_TEMPLATES.keys())
        return await message.answer(f"Использование: <code>/set_season [id]</code>\nДоступные: <code>{keys}</code>")
    else:
        season_id = args[1].lower()
    
    db = get_db()
    if season_id == "off":
        await db.collection('bot_settings').document('season').update({"active": False})
        global_cache.delete("current_season")
        return await message.answer("🛑 <b>Сезонный режим отключен.</b>")
    
    if season_id not in SEASON_TEMPLATES: return await message.answer("❌ Шаблон не найден.")
    
    new_cfg = SEASON_TEMPLATES[season_id].copy()
    new_cfg["active"] = True
    new_cfg["end_time"] = int(time.time()) + 86400 * 30
    
    await db.collection('bot_settings').document('season').set(new_cfg)
    global_cache.delete("current_season")
    
    announce_text = (
        f"✨ <b>НОВЫЙ СЕЗОН ОБЪЯВЛЕН!</b> ✨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌀 <b>ТЕМА:</b> <code>{new_cfg['name']}</code>\n"
        f"⏳ <b>СРОК:</b> <code>30 ДНЕЙ</code>\n\n"
        f"{new_cfg['description']}\n\n"
        f"👉 Подробнее: <code>/season</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    from whitelist import get_whitelist
    whitelist = await get_whitelist()
    count = 0
    for chat_id in whitelist:
        try:
            await message.bot.send_message(chat_id=chat_id, text=announce_text)
            count += 1
            await asyncio.sleep(0.05)
        except: continue
    await message.answer(f"✅ <b>Сезон '{season_id}' активирован!</b>")

# --- СИСТЕМНАЯ АДАПТАЦИЯ ---
async def get_season_string(key: str, default: str) -> str:
    cfg = await get_season_config()
    if not cfg.get("active"): return default
    return cfg.get("strings", {}).get(key, default)

async def apply_season_logic(chat_id: int, user_id: int, base_value: int) -> tuple[int, str]:
    cfg = await get_season_config()
    if not cfg.get("active"): return base_value, ""
    
    # 1. Базовый множитель
    final_value = int(base_value * cfg.get("multiplier", 1.0))
    msg = ""
    
    # 2. Аномальная волатильность (Рандомность)
    # В Закулисье реальность плывет. 10% шанс на "Искажение ценности"
    if random.random() < 0.15:
        distortion = random.uniform(0.1, 2.5)
        final_value = int(final_value * distortion)
        if distortion < 0.5:
            msg = "\n\n🌀 <b>ИСКАЖЕНИЕ:</b> Реальность сжалась, ваша добыча почти исчезла..."
        elif distortion > 2.0:
            msg = "\n\n✨ <b>АНОМАЛИЯ:</b> Вещи из параллельного слоя выпали в ваш карман! Добыча увеличена!"

    # 3. Сезонные артефакты и события
    events = cfg.get("events", [])
    if events:
        rnd = random.random()
        cumulative = 0
        for event in events:
            cumulative += event['chance']
            if rnd < cumulative:
                val = random.randint(*event.get('range', (1000, 5000)))
                
                # Добавим критическую удачу для событий
                if random.random() < 0.05: # 5% шанс на "Идеальный артефакт"
                    val *= 3
                    msg = event['msg'].format(value=val).replace("!", " (ИДЕАЛЬНОЕ СОСТОЯНИЕ)!!!")
                else:
                    msg = event['msg'].format(value=val)
                
                await update_user_balance(chat_id, user_id, -val if event.get('is_penalty') else val)
                break
    
    # 4. Редкий эффект "Эхо" (Повторение награды)
    if random.random() < 0.03:
        msg += "\n\n👥 <b>ЭХО:</b> Вы слышите шаги сзади... Это вы сами из прошлого! Награда дублирована."
        await update_user_balance(chat_id, user_id, final_value)

    return final_value, await get_glitch_text(msg)

async def get_glitch_text(text: str) -> str:
    if not text: return ""
    cfg = await get_season_config()
    if not cfg.get("active"): return text
    
    chance = cfg.get("glitch_chance", 0.1)
    
    # 1. Глобальная нестабильность (шанс увеличивается со временем дня?)
    # Сделаем просто рандомный всплеск
    if random.random() < 0.05: chance = 0.8 # Внезапный сильный глитч

    if random.random() > chance:
        return text
    
    chars = list(text)
    glitches = ["ζ", "⧫", "☠", "☣", "⌬", "⌁", "⟁", "╳", "░", "█", "▓", "▒", "▯", "⫸"]
    
    # Типы глитчей
    g_type = random.choice(["chars", "scramble", "mirror", "empty"])
    
    if g_type == "chars":
        # Замена символов
        for _ in range(random.randint(2, 6)):
            idx = random.randint(0, len(chars) - 1)
            if chars[idx] not in [" ", "<", ">", "/", "=", "\n"]:
                chars[idx] = random.choice(glitches)
    
    elif g_type == "scramble":
        # Перемешивание букв в случайном слове
        words = text.split()
        if len(words) > 2:
            target_idx = random.randint(0, len(words)-1)
            w = list(words[target_idx])
            random.shuffle(w)
            words[target_idx] = "".join(w)
            return " ".join(words)

    elif g_type == "mirror" and len(text) > 10:
        # Отражение части текста
        return text[:5] + text[5:][::-1]

    elif g_type == "empty":
        # Текст пропадает в пустоте
        return "<i>[СООБЩЕНИЕ ПОГЛОЩЕНО ПУСТОТОЙ]</i>"

    res = "".join(chars)
    if random.random() < 0.1:
        noises = [" *бзззт*", " (гудение ламп)", " ...вы слышите шаги...", " [ОШИБКА СИНХРОНИЗАЦИИ]"]
        res += random.choice(noises)
    
    return res
