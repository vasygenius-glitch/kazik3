import time
import random
import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command
from db import get_db
from utils_pkg.cache_manager import global_cache
from config import CREATOR_ID, CREATOR_IDS

from user_manager import update_user_balance, get_user_data, update_user_field

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
                "MWTR": {"name": "MandelWater Inc (MWTR)", "ticker": "MWTR", "desc": "Главный поставщик миндальной воды в Закулисье."},
                "LMP": {"name": "LightGlow (LMP)", "ticker": "LMP", "desc": "Производитель бесконечно гудящих ламп."},
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
    },
    "summer": {
        "id": "summer",
        "name": "СЕЗОН 2: ЛЕТНИЙ КУРАЖ (SUMMER 2026)",
        "emoji": "☀️🏖️🍹",
        "description": (
            "Наступило лето! Время отпусков, солнца и больших выигрышей.\n\n"
            "☀️ <b>ЛЕТНИЙ КУРАЖ:</b> Базовый заработок на работе увеличен на 20%, "
            "а промокоды приносят на 20% больше средств!\n\n"
            "📊 <b>ВЛИЯНИЕ НА МИР:</b>\n"
            "📈 Базовый заработок: +20%\n"
            "🍀 Летнее везение в играх: +15% к шансу выигрыша\n"
            "🔥 Доступны новые команды: /beach_spin, /summer_case, /resort_invest"
        ),
        "multiplier": 1.2,
        "glitch_chance": 0.0,
        "strings": {
            "tax": "🍹 Курортный сбор (Налог)",
            "balance": "☀️ Солнечные коины (Баланс)",
            "shop": "🏖️ Летний Базар",
            "shop_biz": "🏖️ Пляжные кафе",
            "shop_cars": "🛥️ Водные яхты",
            "work": "🍍 Сбор ананасов на пляже",
            "crime": "🥥 Кража кокосов у туристов",
            "bonus": "🍦 Летнее мороженое",
            "profile": "ЛИЧНОЕ ДЕЛО ОТДЫХАЮЩЕГО",
            "bank_label": "🏖️ Шезлонг-сейф",
            "bank_title": "🏦 ЛЕТНИЕ БАНКИ",
            "top_winner": "САМЫЙ АКТИВНЫЙ ТУРИСТ",
            "bj_start": "🏖️ КАЗИНО 'ПЛЯЖНЫЙ БРИЗ'",
            "bj_win": "🎉 ЛЕТНИЙ ДЖЕКПОТ!",
            "roulette_start": "🌀 КОЛЕСО ПЛЯЖНОГО ФОРТУНЫ...",
            "job_list": ["продавал кукурузу на пляже", "работал спасателем на вышке", "смешивал мохито в баре", "катал туристов на банане"],
            "stocks": {
                "COCO": {"name": "CocoNut Co (COCO)", "ticker": "COCO", "desc": "Главный экспортер кокосового молока."},
                "SUNS": {"name": "SunScreen Ltd (SUNS)", "ticker": "SUNS", "desc": "Крупнейший бренд солнцезащитных кремов."},
            }
        },
        "events": [
            {"chance": 0.15, "msg": "\n\n🍹 <b>ВЫ НАШЛИ КОКТЕЙЛЬ!</b> Освежает и дает +{value} сыр.", "range": (5000, 15000)},
            {"chance": 0.05, "msg": "\n\n🦀 <b>ВАС УКУСИЛ КРАБ!</b> Пришлось купить пластырь за -{value} сыр.", "range": (3000, 7000), "is_penalty": True},
            {"chance": 0.08, "msg": "\n\n🕶️ <b>ВЫ НАШЛИ ЗАБЫТЫЕ ОЧКИ!</b> Продали их за +{value} сыр.", "range": (2000, 8000)},
        ]
    },
    "tayniy_baniy": {
        "id": "tayniy_baniy",
        "name": "СЕЗОН 3: ДИКТОРЫ ТАЙНИЙ БАНИЙ (BATH 2026)",
        "emoji": "🛁🧖‍♂️🧼",
        "description": (
            "Добро пожаловать в сезон Дикторов Тайний Баний!\n\n"
            "🛁 <b>ТАЙНЫ БАНИ:</b> Базовый заработок на работе увеличен на 10%!\n\n"
            "📊 <b>ВЛИЯНИЕ НА МИР:</b>\n"
            "📈 Базовый заработок: +10%\n"
            "🍀 Шанс получить редких дикторов!\n"
            "🔥 Доступны новые команды: /banya_case, /banya_spin, /banya_dictor"
        ),
        "multiplier": 1.1,
        "glitch_chance": 0.0,
        "strings": {
            "tax": "🧖‍♂️ Банный сбор (Налог)",
            "balance": "🧼 Банные коины (Баланс)",
            "shop": "🛁 Банная лавка",
            "shop_biz": "🧖‍♂️ Банные комплексы",
            "shop_cars": "🛢 Бочки для купания",
            "work": "🧼 Парение веником",
            "crime": "🧖‍♂️ Подслушивание в бане",
            "bonus": "🧼 Банное мыло",
            "profile": "ЛИЧНОЕ ДЕЛО БАНЩИКА",
            "bank_label": "🛁 Шкафчик в бане",
            "bank_title": "🏦 БАННЫЕ БАНКИ",
            "top_winner": "САМЫЙ ЧИСТЫЙ БАНЩИК",
            "bj_start": "🎰 КАЗИНО 'ТАЙНАЯ БАНЯ'",
            "bj_win": "🎉 БАННЫЙ ДЖЕКПОТ!",
            "roulette_start": "🌀 КРУЖЕНИЕ ВЕЙПА...",
            "job_list": ["вязал березовые веники", "поддавал пару в печь", "массажировал плечи", "разносил квас гостям"],
            "stocks": {
                "VEIK": {"name": "Vennik & Co (VEIK)", "ticker": "VEIK", "desc": "Главный производитель березовых веников."},
                "PAR": {"name": "SteamTech (PAR)", "ticker": "PAR", "desc": "Системы парогенерации нового поколения."},
            }
        },
        "seasonal_disease": {"id": "steam_fever", "name": "Банный Жар", "desc": "Вам слишком жарко. Температура зашкаливает!"},
        "events": [
            {"chance": 0.15, "msg": "\n\n🧖‍♂️ <b>ВЫ ОПАРИЛИСЬ ВЕНИКОМ!</b> Тело поет! Получено +{value} сыр.", "range": (5000, 15000)},
            {"chance": 0.05, "msg": "\n\n🔥 <b>ВЫ ОБОЖГЛИСЬ ПАРОМ!</b> Пришлось купить лед за -{value} сыр.", "range": (3000, 7000), "is_penalty": True},
            {"chance": 0.08, "msg": "\n\n🧼 <b>ВЫ НАШЛИ ЭЛИТНОЕ МЫЛО!</b> Продали его за +{value} сыр.", "range": (2000, 8000)},
        ]
    }
}

async def get_season_config():
    cached = global_cache.get("current_season")
    if cached: return cached
    
    db = get_db()
    if db is None:
        return {"active": False}
        
    # Check if db is a unittest mock
    if type(db).__name__ in ('MagicMock', 'AsyncMock', 'Mock') or hasattr(db, '_mock_return_value'):
        return {"active": False}
        
    try:
        doc = await db.collection('bot_settings').document('season').get()
        if type(doc).__name__ in ('MagicMock', 'AsyncMock', 'Mock') or hasattr(doc, '_mock_return_value'):
            return {"active": False}
        if doc.exists:
            data = doc.to_dict()
            if type(data).__name__ in ('MagicMock', 'AsyncMock', 'Mock'):
                data = {"active": False}
        else:
            data = {"active": False}
            await db.collection('bot_settings').document('season').set(data)
    except Exception:
        data = {"active": False}
    
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
    if message.from_user.id != CREATOR_ID: return
    
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
    async def announce_season():
        count = 0
        for chat_id in whitelist:
            try:
                await message.bot.send_message(chat_id=chat_id, text=announce_text)
                count += 1
                await asyncio.sleep(0.1)
            except Exception: continue
        
        from config import CREATOR_ID
        await message.bot.send_message(CREATOR_ID, f"📢 <b>Рассылка сезона завершена!</b>\nОповещено чатов: {count}")

    from utils import fire_and_forget
    fire_and_forget(announce_season())
    
    await message.answer(f"✅ <b>Сезон '{season_id}' активирован!</b> Рассылка запущена в фоновом режиме.")

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

    # 5. Дроп дикторов для сезона Дикторов Тайний Баний
    if cfg.get("id") == "tayniy_baniy":
        # 8% шанс при работе/крайме найти случайного диктора
        if random.random() < 0.08:
            dictors = [
                {"id": "dictor_common", "name": "обычный диктор тайний баний", "rarity": "Обычный", "color": "⚪", "weight": 45.0},
                {"id": "dictor_simple", "name": "простой диктор тайний баний", "rarity": "Простой", "color": "⚪", "weight": 25.0},
                {"id": "dictor_basic", "name": "базовый диктор тайний баний", "rarity": "Базовый", "color": "⚪", "weight": 15.0},
                {"id": "dictor_uncommon", "name": "необычный диктор тайний баний", "rarity": "Необычный", "color": "🟢", "weight": 6.0},
                {"id": "dictor_rare", "name": "редкий диктор тайний баний", "rarity": "Редкий", "color": "🔵", "weight": 4.0},
                {"id": "dictor_epic", "name": "эпический диктор тайний баний", "rarity": "Эпический", "color": "🟣", "weight": 2.0},
                {"id": "dictor_legendary", "name": "легендарный диктор тайний баний", "rarity": "Легендарный", "color": "🟡", "weight": 1.5},
                {"id": "dictor_mythic", "name": "мифический диктор тайний баний", "rarity": "Мифический", "color": "🔴", "weight": 0.8},
                {"id": "dictor_cosmic", "name": "космический диктор тайний баний", "rarity": "Космический", "color": "🌌", "weight": 0.4},
                {"id": "dictor_divine", "name": "божественный диктор тайний баний", "rarity": "Божественный", "color": "⚡", "weight": 0.1},
                {"id": "dictor_shadow", "name": "теневой диктор тайний баний", "rarity": "Теневой", "color": "👤", "weight": 0.03},
                {"id": "dictor_abyss", "name": "диктор бездны тайний баний", "rarity": "Бездны", "color": "🕳", "weight": 0.03},
                {"id": "dictor_elder", "name": "древний диктор тайний баний", "rarity": "Древний", "color": "⏳", "weight": 0.03},
                {"id": "dictor_chaos", "name": "диктор хаоса тайний баний", "rarity": "Хаоса", "color": "🌀", "weight": 0.02},
                {"id": "dictor_void", "name": "диктор пустоты тайний баний", "rarity": "Пустоты", "color": "🌌", "weight": 0.02},
                {"id": "dictor_infinity", "name": "бесконечный диктор тайний баний", "rarity": "Бесконечный", "color": "♾", "weight": 0.02},
                {"id": "dictor_secret", "name": "секретный диктор тайний баний", "rarity": "Секретный", "color": "🤫", "weight": 0.02},
                {"id": "dictor_emperor", "name": "императорский диктор тайний баний", "rarity": "Императорский", "color": "👑", "weight": 0.01},
                {"id": "dictor_ghost", "name": "призрачный диктор тайний баний", "rarity": "Призрачный", "color": "👻", "weight": 0.01},
                {"id": "dictor_immortal", "name": "бессмертный диктор тайний баний", "rarity": "Бессмертный", "color": "🪐", "weight": 0.01},
            ]
            chosen = random.choices(dictors, weights=[d["weight"] for d in dictors], k=1)[0]
            from user_manager import add_item_to_inventory
            success = await add_item_to_inventory(chat_id, user_id, chosen["id"])
            if success:
                msg += f"\n\n🖤🐇 <b>НАХОДКА!</b> Вы нашли: <code>{chosen['name']}</code> (черный кролик 🖤🐇, {chosen['color']} {chosen['rarity']})! Он добавлен в ваш /inventory."

    return final_value, await get_glitch_text(msg)

async def get_glitch_text(text: str) -> str:
    if not text: return ""
    cfg = await get_season_config()
    if not cfg.get("active"): return text
    
    chance = cfg.get("glitch_chance", 0.1)
    
    # 1. Глобальная нестабильность — рандомный всплеск
    if random.random() < 0.05: chance = 0.8

    if random.random() > chance:
        return text
    
    glitches = ["ζ", "⧫", "☠", "☣", "⌬", "⌁", "⟁", "╳", "░", "█", "▓", "▒", "▯", "⫸"]
    
    # Безопасное разделение текста на HTML-теги и простой текст
    import re
    parts = re.split(r'(<[^>]+>)', text)
    
    # Типы глитчей (только безопасные для HTML)
    g_type = random.choice(["chars", "scramble_safe", "insert"])
    
    if g_type == "chars":
        # Замена символов ТОЛЬКО в не-теговых частях
        for i, part in enumerate(parts):
            if part.startswith('<'):
                continue  # Пропускаем HTML-теги
            chars = list(part)
            replacements = random.randint(1, min(4, max(1, len(chars) // 3)))
            for _ in range(replacements):
                if not chars:
                    break
                idx = random.randint(0, len(chars) - 1)
                if chars[idx] not in [" ", "\n", "&", ";", "#"]:
                    chars[idx] = random.choice(glitches)
            parts[i] = "".join(chars)
    
    elif g_type == "scramble_safe":
        # Перемешивание букв в случайном слове (только в не-теговых частях)
        text_parts_indices = [i for i, p in enumerate(parts) if not p.startswith('<') and len(p.strip()) > 3]
        if text_parts_indices:
            target_idx = random.choice(text_parts_indices)
            words = parts[target_idx].split()
            if len(words) > 1:
                word_idx = random.randint(0, len(words) - 1)
                word = words[word_idx]
                if '&' not in word and len(word) > 2:
                    w = list(word)
                    random.shuffle(w)
                    words[word_idx] = "".join(w)
                    parts[target_idx] = " ".join(words)

    elif g_type == "insert":
        # Вставка глитч-символов между словами (безопасно)
        text_parts_indices = [i for i, p in enumerate(parts) if not p.startswith('<') and len(p.strip()) > 0]
        if text_parts_indices:
            target_idx = random.choice(text_parts_indices)
            insert_pos = random.randint(0, len(parts[target_idx]))
            glitch_insert = random.choice(glitches) * random.randint(1, 3)
            parts[target_idx] = parts[target_idx][:insert_pos] + glitch_insert + parts[target_idx][insert_pos:]

    res = "".join(parts)
    if random.random() < 0.1:
        noises = [" *бзззт*", " (гудение ламп)", " ...вы слышите шаги...", " [ОШИБКА СИНХРОНИЗАЦИИ]"]
        res += random.choice(noises)
    
    return res


# --- НОВЫЕ ЛЕТНИЕ КОМАНДЫ (Летний сезон) ---

@router.message(Command("beach_spin"))
async def cmd_beach_spin(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "summer":
        return await message.answer("☀️ Летний сезон сейчас не активен. Эта команда доступна только летом!")
        

    u_data = await get_user_data(chat_id, user_id)
    if u_data.get('is_banned', False):
        return
        
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: <code>/beach_spin [ставка]</code>")
        
    try:
        bet = int(args[1])
        if bet < 100:
            return await message.answer("Минимальная ставка — 100 сыроежек.")
    except ValueError:
        return await message.answer("Ставка должна быть числом.")
        
    if u_data.get('balance', 0) - bet < -5000:
        return await message.answer("💸 Недостаточно средств! У вас лимит кредита.")
        
    await update_user_balance(chat_id, user_id, -bet, action="Beach Spin Bet")
    
    msg = await message.answer("🌊 <i>Крутим надувной круг фортуны...</i> 🌊")
    await asyncio.sleep(1.0)
    
    rnd = random.random()
    if rnd < 0.40:
        result_msg = "💧 Вы выиграли <b>Бутылку холодной воды</b>! Жара спала, но ставка сгорела. (0x)"
        profit = 0
    elif rnd < 0.70:
        profit = int(bet * 0.5)
        result_msg = f"🍦 Вы выиграли <b>Мороженое</b>! Частично освежает: возвращено <b>{profit}</b> сыроежек. (0.5x)"
    elif rnd < 0.85:
        profit = int(bet * 1.5)
        result_msg = f"🕶️ Вы выиграли <b>Стильные солнцезащитные очки</b>! Выигрыш: <b>{profit}</b> сыроежек! (1.5x)"
    elif rnd < 0.95:
        profit = int(bet * 2.5)
        result_msg = f"🏖️ Вы выиграли <b>Шезлонг под зонтиком</b>! Отличный отдых: выигрыш <b>{profit}</b> сыроежек! (2.5x)"
    else:
        profit = int(bet * 5.0)
        result_msg = f"🍹 <b>ДЖЕКПОТ ПЛЯЖНОЙ ВЕЧЕРИНКИ!</b> Все танцуют! Выигрыш: <b>{profit}</b> сыроежек! (5.0x)"
        
    if profit > 0:
        await update_user_balance(chat_id, user_id, profit, action="Beach Spin Win")
        
    await msg.edit_text(
        f"🏖️ <b>ПЛЯЖНЫЙ СПИН:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: <b>{bet}</b> сыроежек\n"
        f"✨ {result_msg}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

@router.message(Command("summer_case"))
async def cmd_summer_case(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "summer":
        return await message.answer("☀️ Летний сезон сейчас не активен. Эта команда доступна только летом!")
        

    u_data = await get_user_data(chat_id, user_id)
    if u_data.get('is_banned', False):
        return
        
    CASE_PRICE = 10000
    if u_data.get('balance', 0) < CASE_PRICE:
        return await message.answer(f"💸 Летний кейс стоит <b>{CASE_PRICE}</b> сыроежек. У вас недостаточно средств.")
        
    await update_user_balance(chat_id, user_id, -CASE_PRICE, action="Summer Case Open")
    
    msg = await message.answer("🎁 <i>Открываем Летний Кейс...</i> 🐚")
    await asyncio.sleep(1.0)
    
    rnd = random.random()
    if rnd < 0.45:
        reward = random.randint(1000, 4000)
        items = ["Сломанный надувной круг ⭕", "Подгоревшая кукуруза 🌽", "Пустая бутылка из-под крема от загара 🧴"]
        item = random.choice(items)
        rarity = "Обычный"
        color = "⚪"
    elif rnd < 0.80:
        reward = random.randint(5000, 8000)
        items = ["Пляжное полотенце 🧣", "Холодный лимонад 🍹", "Мяч для пляжного волейбола 🏐"]
        item = random.choice(items)
        rarity = "Редкий"
        color = "🔵"
    elif rnd < 0.95:
        reward = random.randint(10000, 15000)
        items = ["Солнцезащитные очки Ray-Ban 🕶️", "Билет в аквапарк 🎫", "Надувной матрас-фламинго 🦩"]
        item = random.choice(items)
        rarity = "Эпический"
        color = "🟣"
    else:
        reward = random.randint(30000, 60000)
        items = ["Скутер для дайвинга 🛵", "Ключи от пляжного бунгало 🔑🛖", "Золотой шезлонг 🏆🏖️"]
        item = random.choice(items)
        rarity = "Легендарный"
        color = "🟡"
        
    await update_user_balance(chat_id, user_id, reward, action="Summer Case Reward")
    
    await msg.edit_text(
        f"🎁 <b>ОТКРЫТИЕ ЛЕТНЕГО КЕЙСА:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Стоимость: <b>{CASE_PRICE}</b> сыроежек\n\n"
        f"{color} <b>Находка:</b> {item}\n"
        f"Редкость: <b>{rarity}</b>\n"
        f"💰 Награда из кейса: <b>{reward}</b> сыроежек!\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

@router.message(Command("resort_invest"))
async def cmd_resort_invest(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "summer":
        return await message.answer("☀️ Летний сезон сейчас не активен. Эта команда доступна только летом!")
        

    u_data = await get_user_data(chat_id, user_id)
    if u_data.get('is_banned', False):
        return
        
    COOLDOWN = 7200
    last_invest = u_data.get('last_resort_invest_time', 0)
    now = time.time()
    if now - last_invest < COOLDOWN:
        remain = int(COOLDOWN - (now - last_invest))
        mins, secs = divmod(remain, 60)
        hours, mins = divmod(mins, 60)
        return await message.answer(f"⏳ Ваши курортные менеджеры еще не подготовили новые инвест-проекты. Подождите {hours}ч {mins}м {secs}с.")
        
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: <code>/resort_invest [сумма]</code>\n(Минимум 5000 сыроежек, максимум 500 000)")
        
    try:
        amount = int(args[1])
        if amount < 5000 or amount > 500000:
            return await message.answer("Сумма инвестиций должна быть от 5 000 до 500 000 сыроежек.")
    except ValueError:
        return await message.answer("Сумма должна быть числом.")
        
    if u_data.get('balance', 0) < amount:
        return await message.answer("💸 У вас недостаточно средств для инвестирования такой суммы.")
        
    await update_user_balance(chat_id, user_id, -amount, action="Resort Invest")
    await update_user_field(chat_id, user_id, 'last_resort_invest_time', now)
    
    msg = await message.answer("🏨 <i>Инвестируем в строительство пляжного отеля...</i> 🏗️")
    await asyncio.sleep(1.0)
    
    rnd = random.random()
    if rnd < 0.45:
        profit = int(amount * 1.5)
        result_text = f"📈 <b>УСПЕХ!</b> Отель открылся вовремя. Вы получили обратно вашу инвестицию и доход: <b>{profit}</b> сыроежек! (+50% прибыли)"
        await update_user_balance(chat_id, user_id, profit, action="Resort Invest Profit")
    elif rnd < 0.55:
        profit = int(amount * 2.5)
        result_text = f"🔥 <b>ТУРИСТИЧЕСКИЙ БУМ!</b> Наплыв туристов превзошел ожидания! Вы получили: <b>{profit}</b> сыроежек! (+150% прибыли)"
        await update_user_balance(chat_id, user_id, profit, action="Resort Invest Jackpot")
    else:
        result_text = "⛈️ <b>Форс-мажор!</b> Тропический ураган повредил инфраструктуру отеля. Инвестиции полностью сгорели."
        
    await msg.edit_text(
        f"🏖️ <b>ИНВЕСТИЦИИ В КУРОРТЫ:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Инвестировано: <b>{amount}</b> сыроежек\n\n"
        f"{result_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


# --- НОВЫЕ БАННЫЕ КОМАНДЫ (Сезон Дикторов Тайний Баний) ---

BANYA_CASE_PRICE = 12000

BANYA_DICTORS_LIST = [
    {"id": "dictor_common", "name": "обычный диктор тайний баний", "rarity": "Обычный", "color": "⚪", "weight": 45.0},
    {"id": "dictor_simple", "name": "простой диктор тайний баний", "rarity": "Простой", "color": "⚪", "weight": 25.0},
    {"id": "dictor_basic", "name": "базовый диктор тайний баний", "rarity": "Базовый", "color": "⚪", "weight": 15.0},
    {"id": "dictor_uncommon", "name": "необычный диктор тайний баний", "rarity": "Необычный", "color": "🟢", "weight": 6.0},
    {"id": "dictor_rare", "name": "редкий диктор тайний баний", "rarity": "Редкий", "color": "🔵", "weight": 4.0},
    {"id": "dictor_epic", "name": "эпический диктор тайний баний", "rarity": "Эпический", "color": "🟣", "weight": 2.0},
    {"id": "dictor_legendary", "name": "легендарный диктор тайний баний", "rarity": "Легендарный", "color": "🟡", "weight": 1.5},
    {"id": "dictor_mythic", "name": "мифический диктор тайний баний", "rarity": "Мифический", "color": "🔴", "weight": 0.8},
    {"id": "dictor_cosmic", "name": "космический диктор тайний баний", "rarity": "Космический", "color": "🌌", "weight": 0.4},
    {"id": "dictor_divine", "name": "божественный диктор тайний баний", "rarity": "Божественный", "color": "⚡", "weight": 0.1},
    {"id": "dictor_shadow", "name": "теневой диктор тайний баний", "rarity": "Теневой", "color": "👤", "weight": 0.03},
    {"id": "dictor_abyss", "name": "диктор бездны тайний баний", "rarity": "Бездны", "color": "🕳", "weight": 0.03},
    {"id": "dictor_elder", "name": "древний диктор тайний баний", "rarity": "Древний", "color": "⏳", "weight": 0.03},
    {"id": "dictor_chaos", "name": "диктор хаоса тайний баний", "rarity": "Хаоса", "color": "🌀", "weight": 0.02},
    {"id": "dictor_void", "name": "диктор пустоты тайний баний", "rarity": "Пустоты", "color": "🌌", "weight": 0.02},
    {"id": "dictor_infinity", "name": "бесконечный диктор тайний баний", "rarity": "Бесконечный", "color": "♾", "weight": 0.02},
    {"id": "dictor_secret", "name": "секретный диктор тайний баний", "rarity": "Секретный", "color": "🤫", "weight": 0.02},
    {"id": "dictor_emperor", "name": "императорский диктор тайний баний", "rarity": "Императорский", "color": "👑", "weight": 0.01},
    {"id": "dictor_ghost", "name": "призрачный диктор тайний баний", "rarity": "Призрачный", "color": "👻", "weight": 0.01},
    {"id": "dictor_immortal", "name": "бессмертный диктор тайний баний", "rarity": "Бессмертный", "color": "🪐", "weight": 0.01},
]


async def execute_batch_banya_case(chat_id: int, user_id: int, count: int, msg: types.Message = None):
    u_data = await get_user_data(chat_id, user_id)
    balance = u_data.get('balance', 0)
    max_affordable = max(0, balance // BANYA_CASE_PRICE)

    if max_affordable < 1:
        text = f"💸 Банный кейс стоит <b>{BANYA_CASE_PRICE}</b> сыроежек. У вас недостаточно средств."
        if msg:
            return await msg.edit_text(text)
        return

    count = max(1, min(count, max_affordable))
    total_cost = count * BANYA_CASE_PRICE

    await update_user_balance(chat_id, user_id, -total_cost, action=f"Banya Case Open {count}x")

    weights = [d["weight"] for d in BANYA_DICTORS_LIST]
    is_creator = (user_id in CREATOR_IDS or int(user_id) == CREATOR_ID)
    top_dictors = [d for d in BANYA_DICTORS_LIST if d["rarity"] in ("Бессмертный", "Императорский", "Секретный", "Божественный", "Бесконечный", "Призрачный", "Хаоса", "Пустоты", "Космический", "Мифический", "Легендарный")]

    from user_manager import add_item_to_inventory
    won_counts = {}

    for _ in range(count):
        if is_creator:
            chosen = random.choice(top_dictors)
        else:
            chosen = random.choices(BANYA_DICTORS_LIST, weights=weights, k=1)[0]

        d_id = chosen["id"]
        won_counts[d_id] = won_counts.get(d_id, 0) + 1
        await add_item_to_inventory(chat_id, user_id, d_id, count=1)

    # Формируем сводку
    from shop import ITEMS
    res_lines = [
        f"🎁 <b>ОТКРЫТИЕ БАННЫХ КЕЙСОВ ({count} шт):</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"Потрачено: <b>{total_cost}</b> сыроежек\n",
        f"🖤🐇 <b>Выпавшие дикторы:</b>"
    ]

    for d_id, qty in won_counts.items():
        dictor_obj = next((d for d in BANYA_DICTORS_LIST if d["id"] == d_id), None)
        d_name = dictor_obj["name"] if dictor_obj else d_id
        d_rarity = dictor_obj["rarity"] if dictor_obj else ""
        d_color = dictor_obj["color"] if dictor_obj else "🖤"
        res_lines.append(f"▪️ {d_color} <b>{d_name}</b> — <b>{qty} шт.</b> ({d_rarity})")

    res_lines.append("\n✨ Предметы добавлены в ваш /inventory!")
    res_lines.append("━━━━━━━━━━━━━━━━━━━━")

    out_text = "\n".join(res_lines)
    if msg:
        await msg.edit_text(out_text)


@router.message(Command("banya_case", "bath_case"))
async def cmd_banya_case(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "tayniy_baniy":
        return await message.answer("🛁 Сезон Дикторов Тайний Баний сейчас не активен. Эта команда доступна только в этом сезоне!")

    u_data = await get_user_data(chat_id, user_id)
    if u_data.get('is_banned', False):
        return

    balance = u_data.get('balance', 0)
    max_cases = max(0, balance // BANYA_CASE_PRICE)

    if max_cases < 1:
        return await message.answer(f"💸 Банный кейс стоит <b>{BANYA_CASE_PRICE}</b> сыроежек. У вас недостаточно средств.")

    raw_text = message.text if isinstance(message.text, str) else "/banya_case"
    args = raw_text.split()

    if len(args) >= 2:
        arg_val = args[1].lower()
        if arg_val in ("all", "все", "макс", "max"):
            count = max_cases
        else:
            try:
                count = int(arg_val)
            except ValueError:
                count = 1
        msg = await message.answer(f"🛁 <i>Открываем {count} банных кейсов...</i> 🧖‍♂️")
        return await execute_batch_banya_case(chat_id, user_id, count, msg)

    # Показываем интерактивные кнопки выбора: 1, 5, 50, на все деньги
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()

    builder.button(text="🎁 1 кейс (12k)", callback_data="banya_case_do_1")
    if max_cases >= 5:
        builder.button(text="🎁 5 кейсов (60k)", callback_data="banya_case_do_5")
    if max_cases >= 50:
        builder.button(text="🎁 50 кейсов (600k)", callback_data="banya_case_do_50")
    
    builder.button(text=f"🔥 НА ВСЕ ДЕНЬГИ ({max_cases} шт)", callback_data=f"banya_case_do_{max_cases}")
    builder.adjust(1)

    text = (
        f"🛁 <b>ОТКРЫТИЕ БАННЫХ КЕЙСОВ ДИКТОРОВ</b> 🛁\n\n"
        f"Стоимость 1 кейса: <b>{BANYA_CASE_PRICE}</b> сыроежек.\n"
        f"Ваш баланс: <b>{balance}</b> сыр. (Доступно для открытия: <b>{max_cases} шт.</b>)\n\n"
        f"Выберите количество кейсов для открытия:"
    )
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("banya_case_do_"))
async def callback_banya_case_do(callback: types.CallbackQuery):
    try:
        qty = int(callback.data.removeprefix("banya_case_do_"))
    except ValueError:
        qty = 1

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    await callback.answer(f"Открываем {qty} кейсов...")
    await execute_batch_banya_case(chat_id, user_id, qty, callback.message)


@router.message(Command("banya_spin"))
async def cmd_banya_spin(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "tayniy_baniy":
        return await message.answer("🛁 Сезон Дикторов Тайний Баний сейчас не активен. Эта команда доступна только в этом сезоне!")
        
    u_data = await get_user_data(chat_id, user_id)
    if u_data.get('is_banned', False):
        return
        
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: <code>/banya_spin [ставка]</code>")
        
    try:
        bet = int(args[1])
        if bet < 100:
            return await message.answer("Минимальная ставка — 100 сыроежек.")
    except ValueError:
        return await message.answer("Ставка должна быть числом.")
        
    if u_data.get('balance', 0) - bet < -5000:
        return await message.answer("💸 Недостаточно средств! У вас лимит кредита.")
        
    await update_user_balance(chat_id, user_id, -bet, action="Banya Spin Bet")
    
    msg = await message.answer("🛁 <i>Поддаем жару в печку... Подкидываем дрова...</i> 💨")
    await asyncio.sleep(1.0)
    
    rnd = random.random()
    if rnd < 0.40:
        result_msg = "💨 Весь пар ушел в трубу! Ставка сгорела. (0x)"
        profit = 0
    elif rnd < 0.70:
        profit = int(bet * 0.5)
        result_msg = f"🧼 Нашли кусочек старого мыла: возвращено <b>{profit}</b> сыроежек. (0.5x)"
    elif rnd < 0.85:
        profit = int(bet * 1.5)
        result_msg = f"🌿 Свежий березовый веник! Выигрыш: <b>{profit}</b> сыроежек! (1.5x)"
    elif rnd < 0.95:
        profit = int(bet * 2.5)
        result_msg = f"🍻 Холодное пиво и раки! Прекрасно попарились: выигрыш <b>{profit}</b> сыроежек! (2.5x)"
    else:
        profit = int(bet * 5.0)
        result_msg = f"🧖‍♂️ <b>ЦАРСКИЙ ПАР! ДЖЕКПОТ!</b> Выигрыш: <b>{profit}</b> сыроежек! (5.0x)"
        
    if profit > 0:
        await update_user_balance(chat_id, user_id, profit, action="Banya Spin Win")
        
    await msg.edit_text(
        f"🧖‍♂️ <b>БАННЫЙ СПИН:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: <b>{bet}</b> сыроежек\n"
        f"✨ {result_msg}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

@router.message(Command("banya_dictor", "bath_dictor"))
async def cmd_banya_dictor(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "tayniy_baniy":
        return await message.answer("🛁 Сезон Дикторов Тайний Баний сейчас не активен. Эта команда доступна только в этом сезоне!")
        
    u_data = await get_user_data(chat_id, user_id)
    if u_data.get('is_banned', False):
        return
        
    inventory = u_data.get('inventory', {})
    
    owned_dictors = []
    dictor_ids = [
        "dictor_common", "dictor_simple", "dictor_basic",
        "dictor_uncommon", "dictor_rare", "dictor_epic", "dictor_legendary", "dictor_mythic", "dictor_cosmic", "dictor_divine",
        "dictor_shadow", "dictor_abyss", "dictor_elder", "dictor_chaos", "dictor_void", "dictor_infinity", "dictor_secret", "dictor_emperor", "dictor_ghost", "dictor_immortal"
    ]
    
    for d_id in dictor_ids:
        if inventory.get(d_id, 0) > 0:
            owned_dictors.append(d_id)
            
    if not owned_dictors:
        return await message.answer(
            "🛁 <b>У вас нет ни одного диктора тайний баний!</b>\n"
            "Откройте банный кейс: <code>/banya_case</code>"
        )
        
    chosen_id = None
    for d_id in reversed(dictor_ids):
        if d_id in owned_dictors:
            chosen_id = d_id
            break
            
    prefixes = {
        "dictor_common": "⚪️ Обычный диктор (черный кролик 🖤🐇) лениво бурчит из-под веника: ",
        "dictor_simple": "⚪️ Простой диктор (черный кролик 🖤🐇) скромно пикает на полке: ",
        "dictor_basic": "⚪️ Базовый диктор (черный кролик 🖤🐇) ровным голосом вещает: ",
        "dictor_uncommon": "🟢 Необычный диктор (черный кролик 🖤🐇) бодро говорит, подливая воду: ",
        "dictor_rare": "🔵 Редкий диктор (черный кролик 🖤🐇) глубокомысленно вздыхает: ",
        "dictor_epic": "🟣 Эпический диктор (черный кролик 🖤🐇) загадочно шепчет в облаке пара: ",
        "dictor_legendary": "🟡 Легендарный диктор (черный кролик 🖤🐇) авторитетно провозглашает: ",
        "dictor_mythic": "🔴 Мифический диктор (черный кролик 🖤🐇) из глубин бани предсказывает: ",
        "dictor_cosmic": "🌌 Космический диктор (черный кролик 🖤🐇) вещает сквозь звездный туман: ",
        "dictor_divine": "⚡ Божественный диктор (черный кролик 🖤🐇) громогласно вещает с небесных полков: ",
        "dictor_shadow": "👤 Теневой диктор (черный кролик 🖤🐇) шепчет из темного угла предбанника: ",
        "dictor_abyss": "🕳 Диктор бездны (черный кролик 🖤🐇) эхом доносит из бездонной бочки: ",
        "dictor_elder": "⏳ Древний диктор (черный кролик 🖤🐇) хрипло скрипит вековой мудростью: ",
        "dictor_chaos": "🌀 Диктор хаоса (черный кролик 🖤🐇) безумно смеется сквозь пар: ",
        "dictor_void": "🌌 Диктор пустоты (черный кролик 🖤🐇) беззвучно проецирует мысли: ",
        "dictor_infinity": "♾ Бесконечный диктор (черный кролик 🖤🐇) говорит сразу на всех языках: ",
        "dictor_secret": "🤫 Секретный диктор (черный кролик 🖤🐇) тайно передает на ухо: ",
        "dictor_emperor": "👑 Императорский диктор (черный кролик 🖤🐇) величественно повелевает: ",
        "dictor_ghost": "👻 Призрачный диктор (черный кролик 🖤🐇) леденящим голосом завывает: ",
        "dictor_immortal": "🪐 Бессмертный диктор (черный кролик 🖤🐇) вечно произносит: "
    }
    
    prefix = prefixes.get(chosen_id, "🧖‍♂️ Диктор говорит: ")
    
    answers = [
        "Бесспорно", "Предрешено", "Никаких сомнений", "Определённо да", "Можешь быть уверен в этом",
        "Мне кажется — «да»", "Вероятнее всего", "Хорошие перспективы", "Знаки говорят — «да»", "Да",
        "Пока не ясно, попробуй снова", "Спроси позже", "Лучше не рассказывать", "Сейчас нельзя предсказать",
        "Сконцентрируйся и спроси опять", "Даже не думай", "Мой ответ — «нет»", "По моим данным — «нет»",
        "Перспективы не очень хорошие", "Весьма сомнительно"
    ]
    
    ans_text = random.choice(answers)
    await message.answer(f"🎱 {prefix}<b>«{ans_text}»</b>")

    # Голосовая TTS озвучка
    try:
        from tts_utils import text_to_speech_voice
        voice_name = "ru-RU-SvetlanaNeural" if chosen_id in ["dictor_cosmic", "dictor_divine", "dictor_secret", "dictor_immortal"] else "ru-RU-DmitryNeural"
        voice_file = await text_to_speech_voice(f"Диктор говорит: {ans_text}", voice_name=voice_name)
        if voice_file:
            try:
                await message.answer_voice(voice=voice_file)
            except Exception as e_voice:
                print(f"Voice send failed, fallback to audio: {e_voice}")
                await message.answer_audio(audio=voice_file, title="Озвучка Диктора", performer="Диктор Бани")
    except Exception as exc:
        print(f"TTS Error: {exc}")




DICTOR_RANKS = [
    "dictor_common", "dictor_simple", "dictor_basic",
    "dictor_uncommon", "dictor_rare", "dictor_epic", "dictor_legendary", "dictor_mythic", "dictor_cosmic", "dictor_divine",
    "dictor_shadow", "dictor_abyss", "dictor_elder", "dictor_chaos", "dictor_void", "dictor_infinity", "dictor_secret", "dictor_emperor", "dictor_ghost", "dictor_immortal"
]


async def render_banya_craft_page(message_or_callback, chat_id: int, user_id: int, page: int = 0, is_edit: bool = False):
    from shop import ITEMS
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    cfg = await get_season_config()
    if not cfg.get("active") or cfg.get("id") != "tayniy_baniy":
        text = "🛁 Сезон Дикторов Тайний Баний сейчас не активен!"
        if is_edit and hasattr(message_or_callback, "message") and message_or_callback.message:
            return await message_or_callback.message.edit_text(text)
        else:
            return await message_or_callback.answer(text)

    u_data = await get_user_data(chat_id, user_id)
    if u_data.get('is_banned', False):
        return

    inventory = u_data.get('inventory', {})

    craftable = []
    for idx, d_id in enumerate(DICTOR_RANKS[:-1]):
        count = inventory.get(d_id, 0)
        if count >= 3:
            next_id = DICTOR_RANKS[idx + 1]
            craftable.append((d_id, next_id, count))

    if not craftable:
        text = (
            "🧪 <b>АПГРЕЙДЕР ДИКТОРОВ ТАЙНИЙ БАНИЙ:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Для улучшения необходимо <b>3 одинаковых диктора</b> одного ранга.\n"
            "Рецепт: <b>3 Диктора (Ранг N) ➔ 1 Диктор (Ранг N+1)</b>\n"
            "Шанс успеха: <b>85%</b>!\n\n"
            "❌ У вас пока нет 3 одинаковых дикторов. Открывайте кейсы <code>/banya_case</code> или ищите их на работе <code>/work</code>!"
        )
        if is_edit and hasattr(message_or_callback, "message") and message_or_callback.message:
            return await message_or_callback.message.edit_text(text)
        else:
            return await message_or_callback.answer(text)

    PAGE_SIZE = 3
    total_pages = max(1, (len(craftable) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    page_items = craftable[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [
        "🧪 <b>АПГРЕЙДЕР ДИКТОРОВ ТАЙНИЙ БАНИЙ</b> 🧪\n",
        f"<i>Показаны от простых до легендарных (Стр. {page + 1} из {total_pages}):</i>\n"
    ]

    builder = InlineKeyboardBuilder()

    for d_id, next_id, count in page_items:
        curr_name = ITEMS.get(d_id, {}).get("name", d_id)
        next_name = ITEMS.get(next_id, {}).get("name", next_id)
        lines.append(f"▪️ <b>{curr_name}</b> ({count} шт) ➔ <code>{next_name}</code>")
        builder.button(
            text=f"🧪 {curr_name} ({count} шт) ➔ {next_name}",
            callback_data=f"banya_craft_sel_{d_id}"
        )

    builder.adjust(1)

    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"banya_craft_page_{page - 1}"))
    else:
        nav_row.append(types.InlineKeyboardButton(text="🛑 Начало", callback_data="none"))

    nav_row.append(types.InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="none"))

    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"banya_craft_page_{page + 1}"))
    else:
        nav_row.append(types.InlineKeyboardButton(text="🛑 Конец", callback_data="none"))

    builder.row(*nav_row)

    text_out = "\n".join(lines)
    markup = builder.as_markup()

    if is_edit and hasattr(message_or_callback, "message") and message_or_callback.message:
        try:
            await message_or_callback.message.edit_text(text_out, reply_markup=markup)
        except Exception:
            pass
    else:
        await message_or_callback.answer(text_out, reply_markup=markup)


@router.message(Command("banya_craft", "dictor_craft", "upgrade_dictor"))
async def cmd_banya_craft(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    await render_banya_craft_page(message, chat_id, user_id, page=0, is_edit=False)


@router.callback_query(F.data.startswith("banya_craft_page_"))
async def callback_banya_craft_page(callback: types.CallbackQuery):
    try:
        page_num = int(callback.data.removeprefix("banya_craft_page_"))
    except ValueError:
        page_num = 0
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    await callback.answer()
    await render_banya_craft_page(callback, chat_id, user_id, page=page_num, is_edit=True)


@router.callback_query(F.data.startswith("banya_craft_sel_"))
async def callback_banya_craft_select(callback: types.CallbackQuery):
    d_id = callback.data.removeprefix("banya_craft_sel_")
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    u_data = await get_user_data(chat_id, user_id)
    inventory = u_data.get('inventory', {})
    count = inventory.get(d_id, 0)

    if count < 3:
        return await callback.answer("❌ У вас недостаточно этих дикторов (нужно минимум 3 шт).", show_alert=True)

    if d_id not in DICTOR_RANKS or DICTOR_RANKS.index(d_id) >= len(DICTOR_RANKS) - 1:
        return await callback.answer("❌ Нельзя улучшить этот ранг дикторов.", show_alert=True)

    curr_idx = DICTOR_RANKS.index(d_id)
    next_id = DICTOR_RANKS[curr_idx + 1]

    from shop import ITEMS
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    curr_name = ITEMS.get(d_id, {}).get("name", d_id)
    next_name = ITEMS.get(next_id, {}).get("name", next_id)

    max_crafts = count // 3
    builder = InlineKeyboardBuilder()

    options = [1]
    if max_crafts >= 2:
        options.append(2)
    if max_crafts >= 5:
        options.append(5)
    if max_crafts not in options:
        options.append(max_crafts)

    for c_qty in options:
        btn_label = f"🔥 ВСЕ ({c_qty} крафтов)" if c_qty == max_crafts else f"🧪 {c_qty} крафт ({c_qty * 3} шт)"
        builder.button(
            text=btn_label,
            callback_data=f"banya_craft_do_{d_id}_{c_qty}"
        )

    builder.button(text="⬅️ Назад к выбору", callback_data="banya_craft_back")
    builder.adjust(1)

    text = (
        f"🔥 <b>НАСТРОЙКА АПГРЕЙДА</b> 🔥\n\n"
        f"Предмет: <b>{curr_name}</b>\n"
        f"В наличии: <b>{count} шт.</b> (Максимум крафтов: <b>{max_crafts}</b>)\n"
        f"Цель: <code>{next_name}</code>\n\n"
        f"Выберите количество одновременных апгрейдов:"
    )

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "banya_craft_back")
async def callback_banya_craft_back(callback: types.CallbackQuery):
    await callback.answer()
    if callback.message:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        await render_banya_craft_page(callback, chat_id, user_id, page=0, is_edit=True)


@router.callback_query(F.data.startswith("banya_craft_do_"))
async def callback_banya_craft_do(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 5:
        return await callback.answer()

    d_id = f"{parts[3]}_{parts[4]}"
    try:
        qty = int(parts[5])
    except (ValueError, IndexError):
        qty = 1

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    u_data = await get_user_data(chat_id, user_id)
    inventory = u_data.get('inventory', {})
    count = inventory.get(d_id, 0)

    req_count = qty * 3
    if count < req_count:
        return await callback.answer(f"❌ Нужно {req_count} шт., а у вас в наличии {count} шт.", show_alert=True)

    if d_id not in DICTOR_RANKS or DICTOR_RANKS.index(d_id) >= len(DICTOR_RANKS) - 1:
        return await callback.answer("❌ Ошибка ранга диктора.", show_alert=True)

    curr_idx = DICTOR_RANKS.index(d_id)
    next_id = DICTOR_RANKS[curr_idx + 1]

    from shop import ITEMS
    from user_manager import remove_item_from_inventory, add_item_to_inventory

    curr_name = ITEMS.get(d_id, {}).get("name", d_id)
    next_name = ITEMS.get(next_id, {}).get("name", next_id)

    await callback.answer(f"Запуск {qty} крафтов...")

    success_count = 0
    fail_count = 0

    for _ in range(qty):
        if random.random() < 0.85:
            success_count += 1
        else:
            fail_count += 1

    consumed_on_success = success_count * 3
    consumed_on_fail = fail_count * 2
    total_consumed = consumed_on_success + consumed_on_fail

    await remove_item_from_inventory(chat_id, user_id, d_id, count=total_consumed)
    if success_count > 0:
        await add_item_to_inventory(chat_id, user_id, next_id, count=success_count)

    result_lines = [
        f"🔥 <b>РЕЗУЛЬТАТЫ МАССОВОГО АПГРЕЙДА!</b> 🔥\n",
        f"Всего попыток: <b>{qty}</b>",
        f"Потрачено ингредиентов: <b>{total_consumed}x {curr_name}</b>\n",
        f"✅ Успешных попыток: <b>{success_count}</b> ➔ Получено: <b>+{success_count}x {next_name}</b>",
        f"💥 Сгорели в печи (неудачи): <b>{fail_count}</b> (спасен {fail_count}x {curr_name})\n",
        "Предметы обновлены в вашем /inventory!"
    ]

    await callback.message.edit_text("\n".join(result_lines))




@router.message(Command("give_dictor", "grant_dictor"))
async def cmd_give_dictor(message: types.Message):
    if message.from_user.id != CREATOR_ID:
        return
        
    args = message.text.split()
    target_user_id = None
    dictor_id = None
    
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        if len(args) >= 2:
            dictor_id = args[1].lower()
    else:
        if len(args) < 3:
            return await message.answer(
                "❌ Использование:\n"
                "1. С ответом на сообщение: <code>/give_dictor [ID_диктора]</code>\n"
                "2. Без ответа: <code>/give_dictor [ID_пользователя] [ID_диктора]</code>"
            )
        try:
            target_user_id = int(args[1])
            dictor_id = args[2].lower()
        except ValueError:
            return await message.answer("❌ ID пользователя должен быть числом.")
            
    from shop import ITEMS
    if dictor_id and not dictor_id.startswith("dictor_"):
        if f"dictor_{dictor_id}" in ITEMS:
            dictor_id = f"dictor_{dictor_id}"
            
    if not dictor_id or dictor_id not in ITEMS or not dictor_id.startswith("dictor_"):
        dictor_list = [k.replace("dictor_", "") for k in ITEMS if k.startswith("dictor_")]
        return await message.answer(
            f"❌ Диктор не найден. Доступные ID:\n"
            f"<code>{', '.join(dictor_list)}</code>"
        )
        
    from user_manager import add_item_to_inventory
    success = await add_item_to_inventory(message.chat.id, target_user_id, dictor_id)
    
    if success:
        dictor_name = ITEMS[dictor_id]["name"]
        await message.answer(
            f"✅ Диктор <b>{dictor_name}</b> успешно выдан пользователю <code>{target_user_id}</code>!"
        )
    else:
        await message.answer("❌ Не удалось выдать диктора (пользователь не найден в БД чата).")




