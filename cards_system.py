# cards_system.py
"""
Система коллекционных карточек: кейсы, коллекция, просмотр карт.
Всего карточек: 200. Бонусы карт влияют на /bonus и ежедневный доход.
"""

import asyncio
import logging
import os
import time
import random
from typing import Optional

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import get_db
from user_manager import (
    buy_and_open_case_tr,
    open_free_case_tr,
    get_user_data,
    get_user_lock,
    get_user_meme_bonuses,
    invalidate_user_cache,
)


logger = logging.getLogger(__name__)

router = Router()

# ─────────────────────────────────────────────────────────────
#  КОНФИГУРАЦИЯ СИСТЕМЫ
# ─────────────────────────────────────────────────────────────

TOTAL_CARDS = 200          # Всего карточек в коллекции
PAGE_SIZE = 10             # Карточек на одной странице коллекции
CARDS_ASSETS_DIR = "assets/cards"
ANIMATION_DELAY = 0.6      # Задержка между кадрами анимации открытия кейса

RARITIES = {
    "COMMON":    {"name": "Обычная",     "emoji": "⚪️"},
    "UNCOMMON":  {"name": "Необычная",   "emoji": "🟢"},
    "RARE":      {"name": "Редкая",      "emoji": "🔵"},
    "EPIC":      {"name": "Эпическая",   "emoji": "🟣"},
    "LEGENDARY": {"name": "Легендарная", "emoji": "🟡"},
}

# Шансы задаются явно для каждого кейса — описание генерируется
# автоматически и ВСЕГДА совпадает с реальными вероятностями.
CASES = {
    "free_case": {
        "id": "free_case",
        "name": "🎁 Бесплатный Кейс Карточек (12ч)",
        "price": 0,
        "tagline": "Бесплатный кейс с карточками доступен каждые 12 часов!",
        "chances": {"COMMON": 50, "UNCOMMON": 30, "RARE": 14, "EPIC": 5, "LEGENDARY": 1},
    },
    "common_case": {
        "id": "common_case",
        "name": "📦 Простой Кейс Карточек",
        "price": 10_000,
        "tagline": "Обычный кейс с коллекционными карточками.",
        "chances": {"COMMON": 65, "UNCOMMON": 25, "RARE": 10},
    },
    "epic_case": {
        "id": "epic_case",
        "name": "🔮 Эпический Кейс Карточек",
        "price": 50_000,
        "tagline": "Кейс для серьёзных коллекционеров.",
        "chances": {"RARE": 70, "EPIC": 25, "LEGENDARY": 5},
    },
}


# Здесь можно переопределить любую карточку вручную.
CUSTOM_CARDS = {
    "meme_1": {
        "name": "Золотой Дракон",
        "rarity": "LEGENDARY",
        "description": "Могущественное существо древности. Приносит горы золота и сыра.",
        "bonus_multiplier": 0.05,
        "bonus_flat": 1000,
    },
    "meme_2": {
        "name": "Тёмный Рыцарь",
        "rarity": "EPIC",
        "description": "Защитник слабых, блуждающий в тени ночи.",
        "bonus_multiplier": 0.02,
        "bonus_flat": 400,
    },
    "meme_3": {
        "name": "Император",
        "rarity": "LEGENDARY",
        "description": "Правитель великой сырной империи.",
        "bonus_multiplier": 0.06,
        "bonus_flat": 1500,
    },
    "meme_4": {
        "name": "Меченосец",
        "rarity": "COMMON",
        "description": "Обычный стражник на посту.",
        "bonus_multiplier": 0.001,
        "bonus_flat": 10,
    },
    "meme_5": {
        "name": "Лесной Маг",
        "rarity": "UNCOMMON",
        "description": "Мастер природной магии и зельеварения.",
        "bonus_multiplier": 0.003,
        "bonus_flat": 50,
    },
}

# Шаблоны автогенерации карт: (редкость, множитель, фикс. доход, префикс имени)
_RARITY_TEMPLATES = [
    (lambda i: i % 40 == 0, "LEGENDARY", 0.05,  1000, "🌟 Легендарная Карта"),
    (lambda i: i % 20 == 0, "EPIC",      0.02,  400,  "🔮 Эпическая Карта"),
    (lambda i: i % 8 == 0,  "RARE",      0.008, 150,  "🔵 Редкая Карта"),
    (lambda i: i % 4 == 0,  "UNCOMMON",  0.003, 50,   "🟢 Необычная Карта"),
]
_DEFAULT_TEMPLATE = ("COMMON", 0.001, 10, "⚪️ Обычная Карта")


def _build_cards() -> dict:
    """Собирает полный набор из TOTAL_CARDS карточек (кастомные + автогенерация)."""
    cards = {}
    for i in range(1, TOTAL_CARDS + 1):
        card_id = f"meme_{i}"

        if card_id in CUSTOM_CARDS:
            cards[card_id] = {"id": card_id, **CUSTOM_CARDS[card_id]}
            continue

        for predicate, rarity, mult, flat, prefix in _RARITY_TEMPLATES:
            if predicate(i):
                break
        else:
            rarity, mult, flat, prefix = _DEFAULT_TEMPLATE

        cards[card_id] = {
            "id": card_id,
            "name": f"{prefix} #{i}",
            "rarity": rarity,
            "description": f"Описание коллекционной карточки #{i}. Замените меня на реальную карту!",
            "bonus_multiplier": mult,
            "bonus_flat": flat,
        }
    return cards


CARDS = _build_cards()

# Предрасчёт: карточки, сгруппированные по редкости (чтобы не перебирать
# все 200 карт при каждом открытии кейса).
CARDS_BY_RARITY: dict[str, list[str]] = {}
for _cid, _card in CARDS.items():
    CARDS_BY_RARITY.setdefault(_card["rarity"], []).append(_cid)

# Отсортированные ключи карт (для пагинации) — считаем один раз.
SORTED_CARD_KEYS = sorted(CARDS.keys(), key=lambda k: int(k.split("_")[1]))
TOTAL_PAGES = max(1, (len(SORTED_CARD_KEYS) + PAGE_SIZE - 1) // PAGE_SIZE)


# ─────────────────────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────

def get_rarity_emoji(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("emoji", "⚪️")


def get_rarity_name(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("name", "Обычная")


def fmt_num(value: int) -> str:
    """10000 -> '10 000' для удобочитаемости."""
    return f"{value:,}".replace(",", " ")


def roll_card_from_case(case_info: dict, user_id: Optional[int] = None) -> Optional[str]:
    """Выбирает случайную карту согласно шансам кейса. Для Создателя выпадают легендарные/мифические/секретные карточки."""
    if user_id and (int(user_id) in CREATOR_IDS or int(user_id) == CREATOR_ID):
        creator_rarities = ["LEGENDARY", "MYTHIC", "EPIC", "SECRET"]
        pool = [r for r in creator_rarities if r in RARITIES and CARDS_BY_RARITY.get(r)]
        if not pool:
            pool = list(RARITIES.keys())
        rarity = random.choice(pool)
        return random.choice(CARDS_BY_RARITY[rarity])

    chances = case_info["chances"]
    pool = [r for r in chances if r in RARITIES and CARDS_BY_RARITY.get(r)]
    if not pool:
        return None
    weights = [chances[r] for r in pool]
    rarity = random.choices(pool, weights=weights, k=1)[0]
    return random.choice(CARDS_BY_RARITY[rarity])


_CARD_URLS_CACHE = None

def get_card_photo_source(card_id: str) -> Optional[str]:
    """Возвращает путь к изображению карты или прямую URL-ссылку."""
    for ext in ("jpg", "png", "webp"):
        path = os.path.join(CARDS_ASSETS_DIR, f"{card_id}.{ext}")
        if os.path.exists(path):
            return path
            
    try:
        if "_" in card_id:
            num = int(card_id.split("_")[-1])
        else:
            num = int(''.join(filter(str.isdigit, card_id)))
    except (ValueError, IndexError):
        num = 1

    pig_key = f"pig_{((num - 1) % 200) + 1:03d}"

    for fname in (f"{pig_key}.jpg", f"pig_{((num - 1) % 200) + 1:02d}.jpg"):
        pig_path = os.path.join(CARDS_ASSETS_DIR, "guinea_pigs", fname)
        if os.path.exists(pig_path):
            return pig_path

    global _CARD_URLS_CACHE
    if _CARD_URLS_CACHE is None:
        urls_file = "cards_photos_urls.json"
        if os.path.exists(urls_file):
            try:
                with open(urls_file, "r", encoding="utf-8") as f:
                    _CARD_URLS_CACHE = json.load(f)
            except Exception:
                _CARD_URLS_CACHE = {}
        else:
            _CARD_URLS_CACHE = {}

    return _CARD_URLS_CACHE.get(pig_key)


def find_card_photo(card_id: str) -> Optional[str]:
    return get_card_photo_source(card_id)


def generate_card_image_fallback(card_id: str) -> str:
    """Генерирует красивая запасная картинка карточки при отсутствии сети."""
    try:
        from PIL import Image, ImageDraw
        cache_dir = os.path.join(CARDS_ASSETS_DIR, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        out_path = os.path.join(cache_dir, f"{card_id}_fallback.png")
        if os.path.exists(out_path):
            return out_path
            
        img = Image.new("RGB", (600, 800), color=(25, 20, 40))
        draw = ImageDraw.Draw(img)
        card_info = CARDS.get(card_id, {})
        name = card_info.get("name", "Карточка Свинки")
        rarity = card_info.get("rarity", "common")
        
        colors = {
            "common": (200, 200, 200),
            "uncommon": (50, 205, 50),
            "rare": (30, 144, 255),
            "epic": (153, 50, 204),
            "legendary": (255, 215, 0),
            "mythic": (220, 20, 60),
            "secret": (255, 105, 180)
        }
        border_color = colors.get(rarity, (200, 200, 200))
        draw.rectangle([15, 15, 585, 785], outline=border_color, width=10)
        draw.rectangle([30, 30, 570, 770], outline=(255, 255, 255), width=2)
        img.save(out_path)
        return out_path
    except Exception:
        return ""


def format_card_bonuses(card: dict) -> str:
    """Формирует блок текста с бонусами карточки."""
    lines = []
    mult_percent = round(card["bonus_multiplier"] * 100, 1)
    if mult_percent > 0:
        lines.append(f"✨ Множитель • +{mult_percent}%")
    if card["bonus_flat"] > 0:
        lines.append(f"💰 Доход • +{fmt_num(card['bonus_flat'])} сыр.")
    return "\n".join(lines) if lines else "✨ Бонусы • Отсутствуют"


def format_case_description(case: dict) -> str:
    """Генерирует описание кейса с реальными шансами."""
    lines = [case["tagline"], "Шансы:"]
    for rarity, chance in case["chances"].items():
        lines.append(f"{get_rarity_emoji(rarity)} {get_rarity_name(rarity)} — {chance}%")
    return "\n".join(lines)


def build_shop_text(balance: int) -> str:
    return (
        "🎴 <b>МАГАЗИН КЕЙСОВ С КАРТОЧКАМИ</b> 🎴\n\n"
        f"Твой баланс: <b>{fmt_num(balance)}</b> сыроежек.\n"
        f"Открывай кейсы, собирай коллекцию из {TOTAL_CARDS} уникальных карт "
        "и получай постоянные пассивные бонусы к доходу!\n\n"
        + "\n\n".join(
            f"{case['name']} — <b>{fmt_num(case['price'])}</b> сыр.\n<i>{format_case_description(case)}</i>"
            for case in CASES.values()
        )
    )


def build_shop_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for case_id, case in CASES.items():
        builder.button(
            text=f"{case['name']} — {fmt_num(case['price'])} сыр.",
            callback_data=f"card_buy_{case_id}",
        )
    builder.button(text="🎒 Моя Коллекция", callback_data="card_page_0")
    builder.adjust(1)
    return builder.as_markup()


async def send_card_message(message: types.Message, card_id: str, text: str) -> None:
    """Отправляет карточку с фото (из локального файла, локального кэша веб-картинки или генератора)."""
    photo_source = get_card_photo_source(card_id)
    
    if photo_source:
        try:
            if photo_source.startswith("http://") or photo_source.startswith("https://"):
                cache_dir = os.path.join(CARDS_ASSETS_DIR, "cache")
                os.makedirs(cache_dir, exist_ok=True)
                cached_file = os.path.join(cache_dir, f"{card_id}.jpg")
                
                if not os.path.exists(cached_file) or os.path.getsize(cached_file) < 100:
                    import urllib.request
                    req = urllib.request.Request(photo_source, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(req, timeout=5) as resp, open(cached_file, 'wb') as out_f:
                        out_f.write(resp.read())

                if os.path.exists(cached_file) and os.path.getsize(cached_file) > 100:
                    await message.answer_photo(photo=FSInputFile(cached_file), caption=text)
                    return
                else:
                    await message.answer_photo(photo=photo_source, caption=text)
                    return
            else:
                await message.answer_photo(photo=FSInputFile(photo_source), caption=text)
                return
        except Exception as e:
            logger.warning("Не удалось отправить фото карты %s: %s", card_id, e)

    # Запасная отправка сгенерированного фото карточки если сеть недоступна
    try:
        gen_path = generate_card_image_fallback(card_id)
        if gen_path and os.path.exists(gen_path):
            await message.answer_photo(photo=FSInputFile(gen_path), caption=text)
            return
    except Exception as e:
        logger.warning("Ошибка генерации fallback фото: %s", e)

    await message.answer(text)




# ─────────────────────────────────────────────────────────────
#  МАГАЗИН КЕЙСОВ (/cases)
# ─────────────────────────────────────────────────────────────

FREE_CASE_TRIGGERS = {
    "free_case", "freecase", "bonus_case", "bonuscase", "daily_case",
    "бесплатный_кейс", "бесплатныйкейс", "бк", "бонусный_кейс", "бонусныйкейс",
    "бесплатный кейс", "бонусный кейс", "бесплатный кейс свинок", "бк свинок",
    "/free_case", "/freecase", "/bonus_case", "/bonuscase", "/daily_case",
    "/бесплатный_кейс", "/бесплатныйкейс", "/бк", "/бонусный_кейс", "/бонусныйкейс",
    "/бесплатный кейс", "/бонусный кейс"
}

@router.message(Command("free_case", "freecase", "bonus_case", "bonuscase", "daily_case", "бесплатный_кейс", "бесплатныйкейс", "бк", "бонусный_кейс", "бонусныйкейс"))
@router.message(F.text.func(lambda t: t and t.lower() in FREE_CASE_TRIGGERS))
async def cmd_free_case(message: types.Message):

    chat_id = message.chat.id
    user_id = message.from_user.id
    
    data = await get_user_data(chat_id, user_id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    now = time.time()
    last_ts = float(data.get("last_free_card_case_ts", 0) or 0)
    cooldown = 43200
    
    if last_ts > 0 and (now - last_ts < cooldown):
        rem = int(cooldown - (now - last_ts))
        h = rem // 3600
        m = (rem % 3600) // 60
        return await message.answer(f"⏳ <b>Бесплатный кейс карточек еще недоступен!</b>\n\nСледующий подарок можно забрать через: <b>{h}ч {m}мин</b>.")


    case_info = CASES["free_case"]
    card_id = roll_card_from_case(case_info, user_id=user_id)
    if not card_id:
        return await message.answer("Ошибка сервиса карточек.")


    card_info = CARDS[card_id]
    db = get_db()
    tr = db.transaction() if db else None
    
    async with get_user_lock(chat_id, user_id):
        success, err = await open_free_case_tr(tr, chat_id, user_id, card_id)

        if success:
            invalidate_user_cache(chat_id, user_id)
            
    if not success:
        return await message.answer(err)

    msg = await message.answer("🎁 <b>Открываем бесплатный 12-часовой кейс...</b>")
    for slide in ANIMATION_SLIDES:
        try:
            await msg.edit_text(slide)
        except Exception:
            pass
        await asyncio.sleep(ANIMATION_DELAY)

    rarity = card_info["rarity"]
    result_text = (
        f"🎁 <b>БЕСПЛАТНЫЙ КЕЙС (12ч) ОТКРЫТ!</b>\n\n"
        f"🃏 Карточка «<b>{card_info['name']}</b>» добавлена в коллекцию!\n\n"
        f"💎 Редкость • {get_rarity_name(rarity)}\n"
        f"{format_card_bonuses(card_info)}"
    )
    await send_card_message(message, card_id, result_text)


@router.callback_query(F.data == "open_free_case_cb")
async def callback_open_free_case(callback: CallbackQuery):
    if callback.message is None:
        return await callback.answer()

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    data = await get_user_data(chat_id, user_id)
    if data.get("is_banned"):
        return await callback.answer("Вы забанены.", show_alert=True)

    now = time.time()
    last_ts = float(data.get("last_free_card_case_ts", 0) or 0)
    cooldown = 43200
    
    if last_ts > 0 and (now - last_ts < cooldown):
        rem = int(cooldown - (now - last_ts))
        h = rem // 3600
        m = (rem % 3600) // 60
        return await callback.answer(f"⏳ Бесплатный кейс будет доступен через {h}ч {m}мин!", show_alert=True)


    case_info = CASES["free_case"]
    card_id = roll_card_from_case(case_info, user_id=user_id)
    if not card_id:
        return await callback.answer("Ошибка ролла карточки.", show_alert=True)


    card_info = CARDS[card_id]
    db = get_db()
    tr = db.transaction() if db else None
    
    async with get_user_lock(chat_id, user_id):
        success, err = await open_free_case_tr(tr, chat_id, user_id, card_id)

        if success:
            invalidate_user_cache(chat_id, user_id)
            
    if not success:
        return await callback.answer(err, show_alert=True)

    await callback.answer("Открываем бесплатный кейс...")
    msg = callback.message

    for slide in ANIMATION_SLIDES:
        try:
            await msg.edit_text(slide)
        except Exception:
            pass
        await asyncio.sleep(ANIMATION_DELAY)

    rarity = card_info["rarity"]
    result_text = (
        f"🎁 <b>БЕСПЛАТНЫЙ КЕЙС (12ч) ОТКРЫТ!</b>\n\n"
        f"🃏 Карточка «<b>{card_info['name']}</b>» добавлена в коллекцию!\n\n"
        f"💎 Редкость • {get_rarity_name(rarity)}\n"
        f"{format_card_bonuses(card_info)}"
    )
    await send_card_message(msg, card_id, result_text)



@router.message(Command("cases", "card_shop", "кейсы"))
async def cmd_cases(message: types.Message):

    data = await get_user_data(message.chat.id, message.from_user.id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    await message.answer(
        build_shop_text(data.get("balance", 0)),
        reply_markup=build_shop_keyboard(),
    )


@router.callback_query(F.data == "card_shop_back")
async def callback_shop_back(callback: CallbackQuery):
    if callback.message is None:
        return await callback.answer()

    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    if data.get("is_banned"):
        return await callback.answer("Вы забанены.", show_alert=True)

    try:
        await callback.message.edit_text(
            build_shop_text(data.get("balance", 0)),
            reply_markup=build_shop_keyboard(),
        )
    except Exception:
        pass
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  ПОКУПКА И ОТКРЫТИЕ КЕЙСА
# ─────────────────────────────────────────────────────────────

ANIMATION_SLIDES = (
    "🎰 <b>Открытие кейса...</b>\n\n[░░░░░░░░░░] 0%",
    "🎰 <b>Открытие кейса...</b>\n\n[▓▓░░░░░░░░] 20%\n🌀 <i>Ищем редкую карту...</i>",
    "🎰 <b>Открытие кейса...</b>\n\n[▓▓▓▓▓░░░░░] 50%\n🎨 <i>Загружаем изображение...</i>",
    "🎰 <b>Открытие кейса...</b>\n\n[▓▓▓▓▓▓▓▓░░] 80%\n⚖️ <i>Сверяем редкость...</i>",
    "🎰 <b>Открытие кейса...</b>\n\n[▓▓▓▓▓▓▓▓▓▓] 100%\n🎉 <b>ГОТОВО!</b>",
)


@router.callback_query(F.data.startswith("card_buy_"))
async def callback_buy_case(callback: CallbackQuery):
    if callback.message is None:
        return await callback.answer("Сообщение устарело, вызовите /cases заново.", show_alert=True)

    case_id = callback.data.removeprefix("card_buy_")
    case_info = CASES.get(case_id)
    if not case_info:
        return await callback.answer("Кейс не найден.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    data = await get_user_data(chat_id, user_id)
    if data.get("is_banned"):
        return await callback.answer("Вы забанены.", show_alert=True)

    price = case_info["price"]
    if data.get("balance", 0) < price:
        return await callback.answer(
            f"❌ Недостаточно средств! Требуется {fmt_num(price)} сыр.", show_alert=True
        )

    card_id = roll_card_from_case(case_info)
    if card_id is None:
        return await callback.answer("Ошибка: нет карточек этой редкости.", show_alert=True)

    card_info = CARDS[card_id]

    # ── Транзакция покупки (баланс проверяется ещё раз внутри транзакции) ──
    success, error_msg = False, "Внутренняя ошибка."
    try:
        db = get_db()
        async with get_user_lock(chat_id, user_id):
            success, error_msg = await buy_and_open_case_tr(
                db.transaction(), chat_id, user_id, price, card_id
            )
            if success:
                invalidate_user_cache(chat_id, user_id)
    except Exception as e:
        logger.exception("Ошибка транзакции покупки кейса (chat=%s, user=%s): %s", chat_id, user_id, e)
        return await callback.answer("Произошла ошибка при покупке. Попробуйте позже.", show_alert=True)

    if not success:
        return await callback.answer(f"Ошибка: {error_msg}", show_alert=True)

    await callback.answer("Открываем кейс...")

    # ── Анимация открытия ──
    for slide in ANIMATION_SLIDES:
        try:
            await callback.message.edit_text(slide)
        except Exception:
            pass
        await asyncio.sleep(ANIMATION_DELAY)

    # ── Результат ──
    rarity = card_info["rarity"]
    result_text = (
        f"🃏 Карточка «<b>{card_info['name']}</b>» добавлена!\n\n"
        f"💎 Редкость • {get_rarity_name(rarity)}\n"
        f"{format_card_bonuses(card_info)}"
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    await send_card_message(callback.message, card_id, result_text)


# ─────────────────────────────────────────────────────────────
#  КОЛЛЕКЦИЯ КАРТОЧЕК (/cards, /collection)
# ─────────────────────────────────────────────────────────────

@router.message(Command("cards", "collection", "карты", "карточки"))
async def cmd_cards(message: types.Message):
    data = await get_user_data(message.chat.id, message.from_user.id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    await render_collection_page(message, data, page=0, as_new=True)


@router.callback_query(F.data.startswith("card_page_"))
async def callback_card_page(callback: CallbackQuery):
    if callback.message is None:
        return await callback.answer()

    try:
        page = int(callback.data.removeprefix("card_page_"))
    except ValueError:
        return await callback.answer("Некорректная страница.", show_alert=True)

    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    if data.get("is_banned"):
        return await callback.answer("Вы забанены.", show_alert=True)

    await render_collection_page(callback.message, data, page=page, as_new=False)
    await callback.answer()


@router.callback_query(F.data == "none")
async def callback_noop(callback: CallbackQuery):
    """Заглушка для декоративных кнопок — убирает «вечный спиннер»."""
    await callback.answer()


async def render_collection_page(message: types.Message, data: dict, page: int, as_new: bool = False):
    meme_cards = data.get("meme_cards", {}) or {}
    opened_count = sum(1 for count in meme_cards.values() if count > 0)

    bonuses = get_user_meme_bonuses(data)
    total_mult = round(bonuses["multiplier"] * 100, 1)
    total_flat = bonuses["flat"]

    page = max(0, min(page, TOTAL_PAGES - 1))
    page_keys = SORTED_CARD_KEYS[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [
        "🎒 <b>КОЛЛЕКЦИЯ КАРТОЧЕК</b> 🎒\n",
        f"Открыто карточек: <b>{opened_count}</b> / <b>{TOTAL_CARDS}</b>",
        f"📈 Общий бонус: <b>+{total_mult}%</b> к /bonus и <b>+{fmt_num(total_flat)}</b> сыр./день.",
        f"Кейсов открыто за всё время: <b>{data.get('opened_cases_count', 0)}</b> шт.\n",
        f"<b>Страница {page + 1} из {TOTAL_PAGES}:</b>",
    ]

    for key in page_keys:
        card = CARDS[key]
        num = key.removeprefix("meme_")
        count = meme_cards.get(key, 0)

        if count > 0:
            mult_info = (
                f"+{round(card['bonus_multiplier'] * 100, 1)}%"
                if card["bonus_multiplier"] > 0 else ""
            )
            flat_info = f"+{fmt_num(card['bonus_flat'])} сыр." if card["bonus_flat"] > 0 else ""
            bonus_text = " / ".join(filter(None, [mult_info, flat_info]))
            lines.append(
                f"▪️ {num}. {get_rarity_emoji(card['rarity'])} <b>{card['name']}</b> "
                f"— <b>{count} шт.</b> ({bonus_text})"
            )
        else:
            lines.append(
                f"▪️ {num}. 🔒 <i>Не открыто</i> (Редкость: {get_rarity_name(card['rarity'])})"
            )

    lines.append(
        "\n💡 <i>Чтобы посмотреть описание карты или изображение (при наличии), введи команду:</i>\n"
        f"<code>/card_info [1-{TOTAL_CARDS}]</code>"
    )
    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Назад", callback_data=f"card_page_{page - 1}")
    else:
        builder.button(text="🛑 Начало", callback_data="none")

    builder.button(text="❌ Закрыть", callback_data="inv_close")

    if page < TOTAL_PAGES - 1:
        builder.button(text="Вперед ➡️", callback_data=f"card_page_{page + 1}")
    else:
        builder.button(text="🛑 Конец", callback_data="none")

    builder.button(text="🛒 Купить Кейсы", callback_data="card_shop_back")
    builder.adjust(3, 1)
    markup = builder.as_markup()

    if as_new:
        await message.answer(text, reply_markup=markup)
    else:
        try:
            await message.edit_text(text, reply_markup=markup)
        except Exception:
            # Сообщение не изменилось или устарело — игнорируем.
            pass


# ─────────────────────────────────────────────────────────────
#  ПРОСМОТР КАРТОЧКИ (/card_info [номер])
# ─────────────────────────────────────────────────────────────

@router.message(Command("card_info"))
async def cmd_card_info(message: types.Message):
    data = await get_user_data(message.chat.id, message.from_user.id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer(
            f"Укажите номер карточки: <code>/card_info [номер от 1 до {TOTAL_CARDS}]</code>"
        )

    card_num = int(args[1])
    card_key = f"meme_{card_num}"
    card_info = CARDS.get(card_key)
    if not card_info:
        return await message.answer(
            f"Неверный номер карточки! Введите число от 1 до {TOTAL_CARDS}."
        )

    count = (data.get("meme_cards", {}) or {}).get(card_key, 0)
    rarity = card_info["rarity"]
    status_str = (
        f"🎒 В инвентаре • {count} шт." if count > 0 else "🔒 Статус • Не открыта"
    )

    text = (
        f"🃏 Карточка «<b>{card_info['name']}</b>» (№{card_num})\n\n"
        f"💎 Редкость • {get_rarity_name(rarity)}\n"
        f"📜 Описание • <i>{card_info['description']}</i>\n"
        f"{format_card_bonuses(card_info)}\n"
        f"{status_str}"
    )

    await send_card_message(message, card_key, text)