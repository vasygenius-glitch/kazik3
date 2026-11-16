# cards_system.py
"""
Система коллекционных карточек v3.1 (Гайд + Закалка карт + Награды за сеты):
- Встроенный интерактивный Гайд (/card_help, кнопка «📖 Гайд» в меню)
- Закалка (прокачка) открытых карт за дубликат + осколки для усиления в дуэлях
- Награды за сбор тематических сетов (/sets)
- Жёсткие кулдауны (КД), защита от гонок, спама и двойных кликов
- Неблокирующая генерация PIL-карт, сбалансированные шансы, Гарант (Pity)
- Кликабельная атрибуция игрока во всех дропах, крафтах, осмотрах и меню
"""

import asyncio
import html
import json
import logging
import os
import random
import shutil
import threading
import time
from typing import Optional

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from firebase_admin import firestore_async

from config import CREATOR_ID, CREATOR_IDS
from db import get_db
from user_manager import (
    buy_and_open_case_tr,
    get_user_by_username_or_id,
    get_user_data,
    get_user_lock,
    get_user_meme_bonuses,
    invalidate_user_cache,
    open_free_case_tr,
    update_user_field,
)

logger = logging.getLogger(__name__)

router = Router()

# ─────────────────────────────────────────────────────────────
#  КОНФИГУРАЦИЯ СИСТЕМЫ И КУЛДАУНОВ (КД)
# ─────────────────────────────────────────────────────────────

TOTAL_CARDS = 200
PAGE_SIZE = 10
CARDS_ASSETS_DIR = "assets/cards"
ANIMATION_DELAY = 0.5
PITY_THRESHOLD = 20            # Гарант Легендарной+ карты каждые N открытий
MAX_CARD_LEVEL = 5             # Максимальный уровень закалки карты
CREATOR_BYPASS_COOLDOWN = True # Создатель не ограничен КД для тестов
TELEGRAM_CAPTION_LIMIT = 1024

COOLDOWNS = {
    "card_info": 15,       # Просмотр одной карточки (/card_info)
    "case_open": 10,       # Покупка и открытие кейса
    "free_case_spam": 30,  # Защита от спама /бк пока бесплатный кейс на КД
    "collection_cmd": 10,  # Вызов команды /cards или /sets
    "shop_cmd": 10,        # Вызов команды /cases
    "help_cmd": 15,        # Вызов гайда /card_help
    "craft": 5,            # Действия в Кузнице и закалка
    "duel": 60,            # Вызов на карточную дуэль
    "callback": 1.2,       # Минимальная пауза между кликами по кнопкам
}

# ─────────────────────────────────────────────────────────────
#  РЕДКОСТИ, ОСКОЛКИ И СИЛА КАРТ
# ─────────────────────────────────────────────────────────────

RARITIES = {
    "COMMON":    {"name": "Обычная",     "emoji": "⚪️", "stars": 1, "shards": 5,   "power": 10,  "color": (185, 195, 210), "bg": (24, 26, 36), "banner": "⚪️ ОБЫЧНАЯ КАРТА"},
    "UNCOMMON":  {"name": "Необычная",   "emoji": "🟢", "stars": 2, "shards": 12,  "power": 25,  "color": (72, 215, 120),  "bg": (18, 34, 26), "banner": "🟢 НЕОБЫЧНЫЙ ДРОП"},
    "RARE":      {"name": "Редкая",      "emoji": "🔵", "stars": 3, "shards": 30,  "power": 55,  "color": (65, 165, 255),  "bg": (16, 26, 44), "banner": "🔵✨ РЕДКИЙ ДРОП!"},
    "EPIC":      {"name": "Эпическая",   "emoji": "🟣", "stars": 4, "shards": 75,  "power": 110, "color": (180, 90, 245),  "bg": (32, 18, 46), "banner": "🟣🔮 ЭПИЧЕСКИЙ ДРОП!"},
    "LEGENDARY": {"name": "Легендарная", "emoji": "🟡", "stars": 5, "shards": 180, "power": 230, "color": (255, 210, 55),  "bg": (44, 32, 14), "banner": "🟡⚡️ ЛЕГЕНДАРНЫЙ ДРОП! ⚡️🟡"},
    "MYTHIC":    {"name": "Мифическая",  "emoji": "🔴", "stars": 6, "shards": 350, "power": 420, "color": (245, 55, 85),   "bg": (46, 14, 22), "banner": "🔴🔥 МИФИЧЕСКИЙ ДРОП! 🔥🔴"},
    "SECRET":    {"name": "Секретная",   "emoji": "🌈", "stars": 7, "shards": 700, "power": 777, "color": (255, 120, 210), "bg": (36, 16, 44), "banner": "🌈💎 СЕКРЕТНАЯ АНОМАЛИЯ! 💎🌈"},
}

RARITY_ORDER = ["COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC", "SECRET"]

CRAFT_COSTS = {
    "COMMON": 20,
    "UNCOMMON": 50,
    "RARE": 120,
    "EPIC": 300,
    "LEGENDARY": 750,
    "MYTHIC": 1500,
}

# ─────────────────────────────────────────────────────────────
#  КЕЙСЫ (СБАЛАНСИРОВАННЫЕ ШАНСЫ)
# ─────────────────────────────────────────────────────────────

CASES = {
    "free_case": {
        "id": "free_case",
        "name": "🎁 Бесплатный Кейс (12ч)",
        "price": 0,
        "tagline": "Доступен каждые 12 часов. Шанс поймать редкую свинку бесплатно!",
        "chances": {"COMMON": 56, "UNCOMMON": 28, "RARE": 11.5, "EPIC": 3.5, "LEGENDARY": 0.9, "MYTHIC": 0.1},
    },
    "common_case": {
        "id": "common_case",
        "name": "📦 Простой Кейс",
        "price": 10_000,
        "tagline": "Базовый кейс для быстрого старта коллекции и фарма осколков.",
        "chances": {"COMMON": 68, "UNCOMMON": 23, "RARE": 8, "EPIC": 1},
    },
    "epic_case": {
        "id": "epic_case",
        "name": "🔮 Эпический Кейс",
        "price": 50_000,
        "tagline": "Только от Редкой и выше — сбалансированный выбор коллекционера.",
        "chances": {"RARE": 72, "EPIC": 22.5, "LEGENDARY": 4.8, "MYTHIC": 0.65, "SECRET": 0.05},
    },
    "royal_case": {
        "id": "royal_case",
        "name": "👑 Королевский Кейс",
        "price": 150_000,
        "tagline": "Повышенный шанс на Эпических, Легендарных и Мифических свинок!",
        "chances": {"RARE": 38, "EPIC": 45, "LEGENDARY": 14, "MYTHIC": 2.75, "SECRET": 0.25},
    },
    "secret_case": {
        "id": "secret_case",
        "name": "🕳 Тайный Кейс",
        "price": 350_000,
        "tagline": "Элитный кейс без мусора. Минимум Эпик, лучший шанс на Секретку!",
        "chances": {"EPIC": 60, "LEGENDARY": 30, "MYTHIC": 9, "SECRET": 1.0},
    },
}

# ─────────────────────────────────────────────────────────────
#  ТЕМАТИЧЕСКИЕ СЕТЫ (АЛЬБОМЫ) С НАГРАДАМИ
# ─────────────────────────────────────────────────────────────

CARD_SETS = {
    "bathhouse": {
        "name": "🧖‍♂️ Банная Братва",
        "cards": ["meme_4", "meme_5", "meme_12", "meme_20", "meme_40"],
        "reward_shards": 120,
    },
    "cheese_empire": {
        "name": "🧀 Сырная Империя",
        "cards": ["meme_1", "meme_2", "meme_3", "meme_24", "meme_80"],
        "reward_shards": 250,
    },
    "cyber_pigs": {
        "name": "🤖 Кибер-Хрюши",
        "cards": ["meme_16", "meme_32", "meme_60", "meme_100", "meme_160"],
        "reward_shards": 350,
    },
    "night_watch": {
        "name": "🌙 Ночной Дозор",
        "cards": ["meme_8", "meme_28", "meme_48", "meme_120", "meme_180"],
        "reward_shards": 280,
    },
    "secret_order": {
        "name": "🌈 Тайный Орден",
        "cards": ["meme_77", "meme_140", "meme_199", "meme_200"],
        "reward_shards": 600,
    },
}

# ─────────────────────────────────────────────────────────────
#  МЕНЕДЖЕР КУЛДАУНОВ, АНТИ-СПАМА И ЗАЩИТА ОТ ГОНОК
# ─────────────────────────────────────────────────────────────

class CooldownManager:
    """Лёгкий in-memory менеджер КД с автоматической очисткой."""

    def __init__(self) -> None:
        self._store: dict[tuple[int, int, str], float] = {}
        self._last_cleanup: float = 0.0

    @staticmethod
    def is_creator(user_id: int) -> bool:
        return int(user_id) in CREATOR_IDS or int(user_id) == CREATOR_ID

    def check(self, chat_id: int, user_id: int, action: str) -> tuple[bool, float]:
        if CREATOR_BYPASS_COOLDOWN and self.is_creator(user_id):
            return True, 0.0

        now = time.monotonic()
        self._maybe_cleanup(now)

        key = (int(chat_id), int(user_id), action)
        expires_at = self._store.get(key, 0.0)
        if now < expires_at:
            return False, round(expires_at - now, 1)
        return True, 0.0

    def trigger(self, chat_id: int, user_id: int, action: str, duration: Optional[float] = None) -> None:
        if CREATOR_BYPASS_COOLDOWN and self.is_creator(user_id):
            return
        cd = duration if duration is not None else COOLDOWNS.get(action, 5)
        key = (int(chat_id), int(user_id), action)
        self._store[key] = time.monotonic() + cd

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < 120:
            return
        self._last_cleanup = now
        expired = [k for k, exp in self._store.items() if exp <= now]
        for k in expired:
            self._store.pop(k, None)


cooldowns = CooldownManager()
ACTIVE_OPENINGS: set[tuple[int, int]] = set()
ACTIVE_DUELS: dict[str, dict] = {}


def _cleanup_expired_duels() -> None:
    now = time.monotonic()
    expired = [k for k, v in ACTIVE_DUELS.items() if v.get("expires", 0) <= now]
    for k in expired:
        ACTIVE_DUELS.pop(k, None)


async def _auto_delete_later(msg: types.Message, delay: float = 6.0) -> None:
    await asyncio.sleep(delay)
    await _safe_delete(msg)


async def _safe_delete(msg: Optional[types.Message]) -> None:
    if msg is None:
        return
    try:
        await msg.delete()
    except Exception:
        pass


async def _safe_edit_text(
    msg: types.Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception:
        return False


def _trim_caption(text: str, limit: int = TELEGRAM_CAPTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def fmt_seconds(sec: float) -> str:
    s = max(1, int(round(sec)))
    if s >= 60:
        m, rem = divmod(s, 60)
        return f"{m}м {rem}с" if rem else f"{m}м"
    return f"{s} сек."


def format_player_mention(user: Optional[types.User], fallback_name: str = "Игрок") -> str:
    if user is None:
        return html.escape(fallback_name)
    safe_name = html.escape(user.full_name or fallback_name)
    return f'<a href="tg://user?id={user.id}">{safe_name}</a>'


# ─────────────────────────────────────────────────────────────
#  ГЕНЕРАЦИЯ 200 КАРТ
# ─────────────────────────────────────────────────────────────

CUSTOM_CARDS = {
    "meme_1": {
        "name": "Золотой Дракон",
        "rarity": "LEGENDARY",
        "description": "Могущественное существо древности. Приносит горы золота и сыра.",
        "bonus_multiplier": 0.015,
        "bonus_flat": 300,
    },
    "meme_2": {
        "name": "Тёмный Рыцарь",
        "rarity": "EPIC",
        "description": "Защитник слабых, блуждающий в тени ночи.",
        "bonus_multiplier": 0.006,
        "bonus_flat": 120,
    },
    "meme_3": {
        "name": "Император",
        "rarity": "LEGENDARY",
        "description": "Правитель великой сырной империи.",
        "bonus_multiplier": 0.018,
        "bonus_flat": 450,
    },
    "meme_4": {
        "name": "Меченосец",
        "rarity": "COMMON",
        "description": "Обычный стражник на посту у входа в парилку.",
        "bonus_multiplier": 0.0003,
        "bonus_flat": 3,
    },
    "meme_5": {
        "name": "Лесной Маг",
        "rarity": "UNCOMMON",
        "description": "Мастер природной магии, отваров и берёзовых веников.",
        "bonus_multiplier": 0.0009,
        "bonus_flat": 15,
    },
    "meme_77": {
        "name": "Хрюшка-Аномалия 77",
        "rarity": "SECRET",
        "description": "Сбой в матрице сырной экономики. Вибрирует на частоте чистого профита.",
        "bonus_multiplier": 0.040,
        "bonus_flat": 1200,
    },
    "meme_199": {
        "name": "Древний Пармастер",
        "rarity": "MYTHIC",
        "description": "Повелитель стоградусного пара. Одного взмаха веника хватает на джекпот.",
        "bonus_multiplier": 0.028,
        "bonus_flat": 750,
    },
    "meme_200": {
        "name": "Абсолютный Свин-Творец",
        "rarity": "SECRET",
        "description": "Мифическая финальная карта коллекции. Сияет всеми цветами сыра.",
        "bonus_multiplier": 0.050,
        "bonus_flat": 1500,
    },
}

_RARITY_TEMPLATES = [
    (lambda i: i % 100 == 0, "SECRET",    0.045,  1200, "🌈 Секретная"),
    (lambda i: i % 50 == 0,  "MYTHIC",    0.025,  650,  "🔴 Мифическая"),
    (lambda i: i % 40 == 0,  "LEGENDARY", 0.015,  300,  "🌟 Легендарная"),
    (lambda i: i % 20 == 0,  "EPIC",      0.006,  120,  "🔮 Эпическая"),
    (lambda i: i % 8 == 0,   "RARE",      0.0024, 45,   "🔵 Редкая"),
    (lambda i: i % 4 == 0,   "UNCOMMON",  0.0009, 15,   "🟢 Необычная"),
]
_DEFAULT_TEMPLATE = ("COMMON", 0.0003, 3, "⚪️ Обычная")

PIG_TITLES = [
    "Свинка Пухляш", "Капитан Морсвак", "Свинка в Маске", "Глава Свинячьей Мафии",
    "Свинка-Бизнесмен", "Берёзовый Пацан", "Баняпузик", "Свинка-Шпион", "Император Свинок",
    "Свинка-Геймер", "Гангстер Пушок", "Пушистый Банщик", "Свинка-Авиатор", "Пророк Свинок",
    "Свинка-Загадка", "Золотая Свинка", "Космический Хрюш", "Мастер Веника", "Свинка-Джазмен",
    "Свинка-Повар", "Свинка-Программист", "Капибара-Брат", "Свинка-Детектив", "Свинка-Самурай",
    "Свинка-Трейдер", "Сырный Барон", "Свинка-Алхимик", "Повелитель Огурцов", "Хрюндель Нео",
    "Свинка-Бард", "Страж Холодильника", "Свинка-Хакер", "Агент Хрю-007", "Свинка-Фараон",
]

PIG_TRAITS = [
    "с золотым моноклем", "в банном халате", "с неоновыми ушами", "в очках из будущего",
    "с запасом огурцов", "из параллельной бани", "с секретным чемоданом", "в короне из сыра",
    "на турбо-самокате", "с катаной из бамбука", "в худи оверсайз", "с платиновым веником",
]

PIG_DESCS = [
    "Любит свежий огурчик и абсолютную тишину перед банным паром.",
    "Контролирует все теневые поставки берёзовых веников в районе.",
    "Древняя морская свинка, знающая короткий путь к сыроежкам.",
    "Хитрый хрюшка, взломавший систему выпадения редких кейсов.",
    "Каждый день приносит стабильный пассивный доход своему владельцу.",
    "Охраняет подступы к парилке и не пускает спамеров в чат.",
    "Обладает пушистой шёрсткой и невероятно харизматичным взглядом!",
    "Легенда гласит, что если погладить её по ушку — следующий кейс окупится.",
    "Работает на чистом кофеине, сыре и хорошем настроении.",
]


def _build_cards() -> dict[str, dict]:
    cards = {}
    for i in range(1, TOTAL_CARDS + 1):
        card_id = f"meme_{i}"
        if card_id in CUSTOM_CARDS:
            c = {"id": card_id, **CUSTOM_CARDS[card_id]}
            c["power"] = RARITIES[c["rarity"]]["power"] + int(c["bonus_flat"] * 0.25)
            cards[card_id] = c
            continue

        for predicate, rarity, mult, flat, prefix in _RARITY_TEMPLATES:
            if predicate(i):
                break
        else:
            rarity, mult, flat, prefix = _DEFAULT_TEMPLATE

        title = PIG_TITLES[(i - 1) % len(PIG_TITLES)]
        trait = PIG_TRAITS[((i - 1) // len(PIG_TITLES)) % len(PIG_TRAITS)]
        desc = PIG_DESCS[(i * 3) % len(PIG_DESCS)]

        cards[card_id] = {
            "id": card_id,
            "name": f"{prefix}: {title} {trait}",
            "rarity": rarity,
            "description": f"{desc} (№{i})",
            "bonus_multiplier": mult,
            "bonus_flat": flat,
            "power": RARITIES[rarity]["power"] + (i % 15),
        }
    return cards


CARDS = _build_cards()

CARDS_BY_RARITY: dict[str, list[str]] = {}
for _cid, _card in CARDS.items():
    CARDS_BY_RARITY.setdefault(_card["rarity"], []).append(_cid)

SORTED_CARD_KEYS = sorted(CARDS.keys(), key=lambda k: int(k.split("_")[1]))
CARD_FILE_IDS: dict[str, str] = {}
_PHOTO_PATH_CACHE: dict[str, Optional[str]] = {}
_CARD_URLS_CACHE: Optional[dict] = None


# ─────────────────────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ВИЗУАЛЬНЫЕ ХЕЛПЕРЫ
# ─────────────────────────────────────────────────────────────

def get_rarity_emoji(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("emoji", "⚪️")


def get_rarity_name(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("name", "Обычная")


def get_rarity_stars(rarity: str) -> str:
    stars = RARITIES.get(rarity, {}).get("stars", 1)
    return "★" * stars + "☆" * max(0, 7 - stars)


def get_rarity_shards(rarity: str) -> int:
    return RARITIES.get(rarity, {}).get("shards", 5)


def get_card_level(data: dict, card_id: str) -> int:
    levels = data.get("card_levels", {}) or {}
    return max(1, min(MAX_CARD_LEVEL, int(levels.get(card_id, 1))))


def get_effective_power(card_id: str, level: int = 1) -> int:
    base = CARDS[card_id].get("power", 10)
    return int(round(base * (1.0 + 0.15 * max(0, level - 1))))


def get_temper_cost(rarity: str, current_level: int) -> int:
    """Стоимость закалки в Сырных Осколках (плюс 1 дубликат карты)."""
    return get_rarity_shards(rarity) * current_level


def fmt_num(value: int | float) -> str:
    return f"{int(value):,}".replace(",", " ")


def make_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "▱" * length
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(ratio * length))
    return "▰" * filled + "▱" * (length - filled)


def roll_card_from_case(
    case_info: dict,
    user_id: Optional[int] = None,
    pity_count: int = 0,
) -> tuple[Optional[str], bool]:
    if user_id and cooldowns.is_creator(user_id):
        creator_rarities = ["SECRET", "MYTHIC", "LEGENDARY", "EPIC"]
        pool = [r for r in creator_rarities if CARDS_BY_RARITY.get(r)]
        rarity = random.choice(pool)
        return random.choice(CARDS_BY_RARITY[rarity]), False

    if pity_count + 1 >= PITY_THRESHOLD and case_info["id"] != "common_case":
        pity_pool = [r for r in ("LEGENDARY", "MYTHIC", "SECRET") if CARDS_BY_RARITY.get(r)]
        if pity_pool:
            rarity = random.choices(pity_pool, weights=[82, 16, 2], k=1)[0]
            return random.choice(CARDS_BY_RARITY[rarity]), True

    chances = case_info["chances"]
    pool = [r for r in chances if r in RARITIES and CARDS_BY_RARITY.get(r)]
    if not pool:
        return None, False
    weights = [chances[r] for r in pool]
    rarity = random.choices(pool, weights=weights, k=1)[0]
    return random.choice(CARDS_BY_RARITY[rarity]), False


ASSETS_ZIP_URL = "https://github.com/vasygenius-glitch/kazik3/releases/download/v2.0-cards-assets/cards_assets_opt.zip"
_ASSETS_INITIALIZED = False
_ASSETS_LOCK = threading.Lock()


def ensure_cards_assets() -> bool:
    """Гарантирует наличие всех 200 изображений карточек.
    Если локальные файлы отсутствуют (например, свежий контейнер на Hugging Face Spaces),
    автоматически скачивает компактный архив из GitHub Release и распаковывает."""
    global _ASSETS_INITIALIZED
    if _ASSETS_INITIALIZED:
        return True

    with _ASSETS_LOCK:
        if _ASSETS_INITIALIZED:
            return True

        pig_dir = os.path.join(CARDS_ASSETS_DIR, "guinea_pigs")
        os.makedirs(pig_dir, exist_ok=True)
        os.makedirs(CARDS_ASSETS_DIR, exist_ok=True)

        existing_jpg = [
            f for f in os.listdir(pig_dir)
            if f.startswith("pig_") and (f.endswith(".jpg") or f.endswith(".webp"))
        ] if os.path.exists(pig_dir) else []

        if len(existing_jpg) >= 200:
            _ASSETS_INITIALIZED = True
            return True

        zip_path = os.path.join(CARDS_ASSETS_DIR, "cards_assets_opt.zip")
        if not os.path.exists(zip_path):
            try:
                import urllib.request
                logger.info("Загрузка архива карточек из GitHub Release: %s", ASSETS_ZIP_URL)
                req = urllib.request.Request(
                    ASSETS_ZIP_URL,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, "wb") as out_f:
                    shutil.copyfileobj(resp, out_f)
                logger.info("Архив карточек успешно скачан (%s)", zip_path)
            except Exception as e:
                logger.warning("Не удалось скачать архив карточек: %s", e)
                return False

        if os.path.exists(zip_path):
            try:
                import zipfile
                from PIL import Image
                with zipfile.ZipFile(zip_path, "r") as z:
                    for item in z.infolist():
                        if not item.filename.endswith(".webp"):
                            continue
                        base = os.path.splitext(item.filename)[0]
                        webp_path = os.path.join(pig_dir, item.filename)
                        jpg_name = base + ".jpg"
                        jpg_path = os.path.join(pig_dir, jpg_name)

                        if not os.path.exists(webp_path):
                            with open(webp_path, "wb") as f:
                                f.write(z.read(item))

                        if not os.path.exists(jpg_path):
                            try:
                                with Image.open(webp_path) as im:
                                    im.convert("RGB").save(jpg_path, "JPEG", quality=85)
                            except Exception:
                                pass

                        try:
                            num = int(base.split("_")[-1])
                            meme_path = os.path.join(CARDS_ASSETS_DIR, f"meme_{num}.jpg")
                            if not os.path.exists(meme_path) and os.path.exists(jpg_path):
                                shutil.copyfile(jpg_path, meme_path)
                        except Exception:
                            pass
                logger.info("Все 200 изображений карточек успешно подготовлены!")
                _PHOTO_PATH_CACHE.clear()
                _ASSETS_INITIALIZED = True
                return True
            except Exception as e:
                logger.warning("Ошибка при распаковке архива карточек: %s", e)
                return False

        return False


def _ensure_jpg_format(path: str) -> str:
    """Если файл в формате .webp, конвертирует его в .jpg для полной совместимости с Telegram Bot API."""
    if not path or not path.lower().endswith(".webp"):
        return path
    jpg_path = path.rsplit(".", 1)[0] + ".jpg"
    if os.path.exists(jpg_path):
        return jpg_path
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.convert("RGB").save(jpg_path, "JPEG", quality=85)
        return jpg_path
    except Exception as e:
        logger.warning("Не удалось сконвертировать %s в JPG: %s", path, e)
        return path


def _start_assets_loader_thread() -> None:
    try:
        t = threading.Thread(target=ensure_cards_assets, daemon=True, name="CardsAssetsLoader")
        t.start()
    except Exception as e:
        logger.warning("Не удалось запустить CardsAssetsLoader: %s", e)


_start_assets_loader_thread()


def get_card_photo_source(card_id: str) -> Optional[str]:
    if card_id in _PHOTO_PATH_CACHE and _PHOTO_PATH_CACHE[card_id]:
        cached = _PHOTO_PATH_CACHE[card_id]
        if cached and os.path.exists(cached):
            return cached

    # 1. Проверяем assets/cards/meme_X.(jpg|jpeg|png|webp)
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = os.path.join(CARDS_ASSETS_DIR, f"{card_id}.{ext}")
        if os.path.exists(path):
            res = _ensure_jpg_format(path)
            _PHOTO_PATH_CACHE[card_id] = res
            return res

    try:
        num = int(card_id.split("_")[-1]) if "_" in card_id else int("".join(filter(str.isdigit, card_id)))
    except (ValueError, IndexError):
        num = 1

    pig_key = f"pig_{((num - 1) % 200) + 1:03d}"
    pig_dir = os.path.join(CARDS_ASSETS_DIR, "guinea_pigs")

    # 2. Проверяем assets/cards/guinea_pigs/pig_XXX.(jpg|jpeg|png|webp)
    for ext in ("jpg", "jpeg", "png", "webp"):
        for pkey in (pig_key, f"pig_{((num - 1) % 200) + 1:02d}"):
            pig_path = os.path.join(pig_dir, f"{pkey}.{ext}")
            if os.path.exists(pig_path):
                res = _ensure_jpg_format(pig_path)
                _PHOTO_PATH_CACHE[card_id] = res
                return res

    # 3. Проверяем напрямую в assets/cards/
    for ext in ("jpg", "jpeg", "png", "webp"):
        alt_path = os.path.join(CARDS_ASSETS_DIR, f"{pig_key}.{ext}")
        if os.path.exists(alt_path):
            res = _ensure_jpg_format(alt_path)
            _PHOTO_PATH_CACHE[card_id] = res
            return res

    # 4. Если на диске пусто (новый контейнер), пробуем синхронный запуск загрузчика
    if ensure_cards_assets():
        for ext in ("jpg", "jpeg", "png", "webp"):
            path = os.path.join(CARDS_ASSETS_DIR, f"{card_id}.{ext}")
            if os.path.exists(path):
                res = _ensure_jpg_format(path)
                _PHOTO_PATH_CACHE[card_id] = res
                return res
        for ext in ("jpg", "jpeg", "png", "webp"):
            pig_path = os.path.join(pig_dir, f"{pig_key}.{ext}")
            if os.path.exists(pig_path):
                res = _ensure_jpg_format(pig_path)
                _PHOTO_PATH_CACHE[card_id] = res
                return res

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

    res = _CARD_URLS_CACHE.get(pig_key)
    _PHOTO_PATH_CACHE[card_id] = res
    return res


def find_card_photo(card_id: str) -> Optional[str]:
    return get_card_photo_source(card_id)


def _load_pil_font(size: int):
    from PIL import ImageFont
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def generate_card_image_fallback(card_id: str) -> str:
    """Генерирует стильную коллекционную карту v3 с эффектом свечения и диагональным узором."""
    try:
        from PIL import Image, ImageDraw

        cache_dir = os.path.join(CARDS_ASSETS_DIR, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        out_path = os.path.join(cache_dir, f"{card_id}_v3.png")
        if os.path.exists(out_path):
            return out_path

        card_info = CARDS.get(card_id, {})
        rarity = str(card_info.get("rarity", "COMMON")).upper()
        r_meta = RARITIES.get(rarity, RARITIES["COMMON"])
        border_color = r_meta["color"]
        bg_color = r_meta["bg"]

        w, h = 600, 820
        img = Image.new("RGB", (w, h), color=bg_color)
        draw = ImageDraw.Draw(img)

        stripe_col = tuple(min(255, c + 12) for c in bg_color)
        for x in range(-h, w + h, 36):
            draw.line([(x, 0), (x + h, h)], fill=stripe_col, width=2)

        if rarity in ("EPIC", "LEGENDARY", "MYTHIC", "SECRET"):
            glow = tuple(max(0, c // 2) for c in border_color)
            draw.rounded_rectangle([8, 8, w - 8, h - 8], radius=32, outline=glow, width=6)

        draw.rounded_rectangle([16, 16, w - 16, h - 16], radius=26, outline=border_color, width=10)
        draw.rounded_rectangle([32, 32, w - 32, h - 32], radius=18, outline=(245, 245, 255), width=2)

        draw.rounded_rectangle([54, 52, w - 54, 122], radius=14, fill=(16, 16, 26), outline=border_color, width=2)
        draw.rounded_rectangle([54, 142, w - 54, 530], radius=18, fill=(24, 22, 38), outline=border_color, width=3)
        draw.ellipse([175, 195, 425, 445], fill=(34, 30, 56), outline=border_color, width=4)
        draw.ellipse([195, 215, 405, 425], outline=(240, 240, 255), width=1)
        draw.rounded_rectangle([54, 552, w - 54, 766], radius=16, fill=(16, 16, 26), outline=border_color, width=2)

        font_title = _load_pil_font(26)
        font_sub = _load_pil_font(20)
        font_big = _load_pil_font(42)

        num_str = f"#{card_id.removeprefix('meme_')}"
        rarity_label = get_rarity_name(rarity).upper()
        stars_str = "*" * r_meta["stars"]

        draw.text((76, 72), num_str, fill=border_color, font=font_title)
        draw.text((240, 72), rarity_label, fill=(245, 245, 255), font=font_title)
        draw.text((232, 296), num_str, fill=border_color, font=font_big)

        name_raw = card_info.get("name", "Свинка")
        clean_name = name_raw.split(": ", 1)[-1][:28]
        draw.text((76, 578), clean_name, fill=(255, 255, 255), font=font_title)
        draw.text((76, 630), f"POWER: {card_info.get('power', 10)}   |   TIER: {stars_str}", fill=border_color, font=font_sub)

        mult_pct = round(card_info.get("bonus_multiplier", 0) * 100, 2)
        flat_val = card_info.get("bonus_flat", 0)
        draw.text((76, 680), f"BONUS: +{mult_pct}%   |   INCOME: +{flat_val}/day", fill=(200, 215, 235), font=font_sub)

        img.save(out_path)
        return out_path
    except Exception as e:
        logger.warning("Ошибка создания fallback PIL изображения %s: %s", card_id, e)
        return ""


def format_card_bonuses(card: dict, level: int = 1) -> str:
    lines = []
    mult_percent = round(card["bonus_multiplier"] * 100, 2)
    if mult_percent > 0:
        lines.append(f"✨ Множитель • <b>+{mult_percent}%</b> к /bonus")
    if card["bonus_flat"] > 0:
        lines.append(f"💰 Доход • <b>+{fmt_num(card['bonus_flat'])}</b> сыр./день")
    eff_power = get_effective_power(card["id"], level)
    lvl_tag = f" <i>(Ур. {level}/{MAX_CARD_LEVEL})</i>" if level > 1 else ""
    lines.append(f"⚔️ Сила • <b>{eff_power} ⚡</b>{lvl_tag}")
    return "\n".join(lines)


def format_case_description(case: dict) -> str:
    chance_parts = [
        f"{get_rarity_emoji(r)} {get_rarity_name(r)} {ch}%"
        for r, ch in case["chances"].items()
    ]
    return f"{case['tagline']}\nШансы: " + " | ".join(chance_parts)


def build_guide_text(player_mention: Optional[str] = None) -> str:
    owner_line = f"👤 Для игрока • {player_mention}\n" if player_mention else ""
    return (
        "📖 <b>ГАЙД ПО СИСТЕМЕ КАРТОЧЕК</b> 📖\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"{owner_line}\n"
        "<b>1️⃣ Как получать карточки?</b>\n"
        "• <code>/бк</code> — бесплатный кейс каждые 12 часов.\n"
        "• <code>/cases</code> — магазин кейсов за сыроежки (чем дороже кейс, тем выше шанс на редких свинок).\n"
        "• 🎯 <b>Гарант:</b> каждые <b>20 открытий</b> без 🟡 Легендарной+ карты срабатывает 100% гарант!\n\n"
        "<b>2️⃣ Зачем нужны дубликаты и 🧀 Осколки?</b>\n"
        "• Повторная карта из кейса автоматически даёт <b>Сырные Осколки</b>.\n"
        "• В <code>/forge</code> (Кузница) за осколки можно скрафтить <b>гарантированно НОВУЮ</b> карту!\n"
        "• В <code>/card_info [№]</code> можно <b>⬆️ Закалить</b> карту (дубликат + осколки), подняв её уровень (до 5) и силу для дуэлей.\n\n"
        "<b>3️⃣ Сеты, Витрина и Дуэли</b>\n"
        "• <code>/sets</code> — собирайте тематические альбомы и забирайте награды в 🧀 осколках.\n"
        "• <code>/cards</code> — коллекция с фильтрами. В <code>/card_info</code> поставьте лучшую карту на <b>⭐️ Витрину</b>.\n"
        "• <code>/card_duel</code> (ответом на сообщение) — битва картами с Витрины за <b>+15 🧀</b>!\n\n"
        "<b>4️⃣ Анти-спам</b>\n"
        "• На команды и открытие кейсов действуют короткие КД, чтобы не флудить в чате."
    )


def build_shop_text(data: dict, player_mention: Optional[str] = None) -> str:
    balance = data.get("balance", 0)
    shards = data.get("card_shards", 0)
    pity = data.get("card_pity", 0)
    pity_bar = make_progress_bar(pity, PITY_THRESHOLD, 10)

    cases_block = "\n\n".join(
        f"▸ {c['name']} — <b>{'БЕСПЛАТНО' if c['price'] == 0 else fmt_num(c['price']) + ' сыр.'}</b>\n"
        f"<i>{format_case_description(c)}</i>"
        for c in CASES.values()
    )

    owner_line = f"👤 Игрок • {player_mention}\n" if player_mention else ""
    return (
        "🎴 <b>МАГАЗИН КЕЙСОВ С КАРТОЧКАМИ</b> 🎴\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"{owner_line}"
        f"💰 Баланс: <b>{fmt_num(balance)}</b> сыр.  |  🧀 Осколки: <b>{fmt_num(shards)}</b>\n"
        f"🎯 Гарант Легендарки+: [{pity_bar}] <b>{pity}/{PITY_THRESHOLD}</b>\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
        f"{cases_block}"
    )


def build_shop_keyboard(user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    uid_suffix = f"_{user_id}" if user_id is not None else ""
    for case_id, case in CASES.items():
        if case_id == "free_case":
            builder.button(
                text=f"{case['name']} — Открыть",
                callback_data=f"open_free_case_cb_{user_id}" if user_id else "open_free_case_cb",
            )
        else:
            builder.button(
                text=f"{case['name']} — {fmt_num(case['price'])} сыр.",
                callback_data=f"card_buy_{case_id}{uid_suffix}",
            )
    builder.button(text="🎒 Коллекция", callback_data=f"card_page_0_all{uid_suffix}")
    builder.button(text="🔨 Кузница", callback_data=f"card_forge{uid_suffix}")
    builder.button(text="📖 Гайд", callback_data=f"card_guide{uid_suffix}")
    builder.button(text="❌ Закрыть", callback_data=f"card_close{uid_suffix}")
    builder.adjust(1, 1, 1, 1, 1, 2, 2)
    return builder.as_markup()


def build_card_caption_markup(
    card_key: str,
    user_id: int,
    is_fav: bool = False,
    can_temper: bool = False,
    temper_cost: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fav_text = "⭐️ На витрине" if is_fav else "☆ На витрину"
    builder.button(text=fav_text, callback_data=f"card_fav_{card_key}_{user_id}")
    if can_temper:
        builder.button(text=f"⬆️ Закалить ({temper_cost} 🧀)", callback_data=f"card_temper_{card_key}_{user_id}")
    builder.button(text="🎒 Коллекция", callback_data=f"card_page_0_all_{user_id}")
    builder.button(text="❌ Закрыть", callback_data=f"card_close_{user_id}")
    if can_temper:
        builder.adjust(2, 2)
    else:
        builder.adjust(2, 1)
    return builder.as_markup()


async def send_card_message(
    message: types.Message,
    card_id: str,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    caption = _trim_caption(text)
    cached_file_id = CARD_FILE_IDS.get(card_id)
    if cached_file_id:
        try:
            await message.answer_photo(photo=cached_file_id, caption=caption, reply_markup=reply_markup)
            return
        except Exception as e:
            logger.warning("Ошибка кэша file_id для %s: %s", card_id, e)
            CARD_FILE_IDS.pop(card_id, None)

    photo_source = get_card_photo_source(card_id)

    if photo_source and not photo_source.startswith(("http://", "https://")) and os.path.exists(photo_source):
        try:
            sent_msg = await message.answer_photo(
                photo=FSInputFile(photo_source), caption=caption, reply_markup=reply_markup
            )
            if sent_msg and sent_msg.photo:
                CARD_FILE_IDS[card_id] = sent_msg.photo[-1].file_id
            return
        except Exception as e:
            logger.warning("Ошибка отправки локального фото %s: %s", photo_source, e)

    if photo_source and photo_source.startswith(("http://", "https://")):
        clean_url = photo_source.split("?")[0]
        try:
            sent_msg = await message.answer_photo(photo=clean_url, caption=caption, reply_markup=reply_markup)
            if sent_msg and sent_msg.photo:
                CARD_FILE_IDS[card_id] = sent_msg.photo[-1].file_id
            return
        except Exception as e:
            logger.warning("Ошибка отправки URL фото %s: %s", clean_url, e)

    fallback_path = await asyncio.to_thread(generate_card_image_fallback, card_id)
    if fallback_path and os.path.exists(fallback_path):
        try:
            sent_msg = await message.answer_photo(
                photo=FSInputFile(fallback_path), caption=caption, reply_markup=reply_markup
            )
            if sent_msg and sent_msg.photo:
                CARD_FILE_IDS[card_id] = sent_msg.photo[-1].file_id
            return
        except Exception as e:
            logger.warning("Ошибка отправки PIL fallback %s: %s", fallback_path, e)

    default_pig_url = "https://images.unsplash.com/photo-1548767797-d8c844163c4c?w=800&auto=format&fit=crop"
    try:
        sent_msg = await message.answer_photo(photo=default_pig_url, caption=caption, reply_markup=reply_markup)
        if sent_msg and sent_msg.photo:
            CARD_FILE_IDS[card_id] = sent_msg.photo[-1].file_id
        return
    except Exception:
        pass

    await message.answer(caption, reply_markup=reply_markup)


# ─────────────────────────────────────────────────────────────
#  ОБРАБОТКА РЕЗУЛЬТАТА ДРОПА (ГАРАНТ + ОСКОЛКИ ЗА ДУБЛИКАТЫ)
# ─────────────────────────────────────────────────────────────

async def _process_drop_rewards(
    chat_id: int,
    user_id: int,
    card_id: str,
    was_already_owned: bool,
    triggered_pity: bool,
    pre_data: dict,
) -> tuple[int, int]:
    rarity = CARDS[card_id]["rarity"]
    new_pity = 0 if (triggered_pity or rarity in ("LEGENDARY", "MYTHIC", "SECRET")) else int(pre_data.get("card_pity", 0)) + 1

    gained_shards = 0
    try:
        await update_user_field(chat_id, user_id, "card_pity", new_pity)
        if was_already_owned:
            gained_shards = get_rarity_shards(rarity)
            new_shards = int(pre_data.get("card_shards", 0)) + gained_shards
            await update_user_field(chat_id, user_id, "card_shards", new_shards)
        invalidate_user_cache(chat_id, user_id)
    except Exception as e:
        logger.warning("Не удалось обновить pity/shards для %s: %s", user_id, e)

    return gained_shards, new_pity


def _build_animation_slides(player_mention: str, rarity: str) -> tuple[str, ...]:
    base = [
        f"🎰 <b>Открытие кейса</b> • {player_mention}\n\n[▱▱▱▱▱▱▱▱▱▱] 0%\n⚪️🟢🔵 <i>Раскручиваем барабан...</i>",
        f"🎰 <b>Открытие кейса</b> • {player_mention}\n\n[▰▰▰▱▱▱▱▱▱▱] 30%\n🌀 <i>Тасуем колоду свинок...</i>",
        f"🎰 <b>Открытие кейса</b> • {player_mention}\n\n[▰▰▰▰▰▰▱▱▱▱] 60%\n✨ <i>Сверяем редкость и ауру...</i>",
    ]
    if rarity in ("LEGENDARY", "MYTHIC", "SECRET"):
        base.append(f"🎰 <b>Открытие кейса</b> • {player_mention}\n\n[▰▰▰▰▰▰▰▰▰▱] 90%\n⚡️ <i>СИГНАЛ ВЫСОКОЙ РЕДКОСТИ...</i>")
        base.append(f"🎰 <b>Открытие кейса</b> • {player_mention}\n\n[▰▰▰▰▰▰▰▰▰▰] 100%\n🔥💥 <b>УЛЬТРА-ВСПЫШКА! ЧТО-ТО МОЩНОЕ!</b> 💥🔥")
    elif rarity in ("RARE", "EPIC"):
        base.append(f"🎰 <b>Открытие кейса</b> • {player_mention}\n\n[▰▰▰▰▰▰▰▰▰▰] 100%\n✨ <b>ЯРКАЯ ВСПЫШКА! ГОТОВО!</b>")
    else:
        base.append(f"🎰 <b>Открытие кейса</b> • {player_mention}\n\n[▰▰▰▰▰▰▰▰▰▰] 100%\n🎉 <b>ГОТОВО!</b>")
    return tuple(base)


def _build_drop_caption(
    title: str,
    player_mention: str,
    card_id: str,
    was_owned: bool,
    gained_shards: int,
    new_pity: int,
    triggered_pity: bool,
    level: int = 1,
) -> str:
    card = CARDS[card_id]
    rarity = card["rarity"]
    r_meta = RARITIES[rarity]
    num = card_id.removeprefix("meme_")
    stars = get_rarity_stars(rarity)
    pity_bar = make_progress_bar(new_pity, PITY_THRESHOLD, 8)

    badges = []
    if not was_owned:
        badges.append("🆕 <b>НОВАЯ КАРТА В КОЛЛЕКЦИИ!</b>")
    else:
        badges.append(f"♻️ Дубликат → <b>+{gained_shards} 🧀 осколков</b>")
    if triggered_pity:
        badges.append("🎯 <b>СРАБОТАЛ ГАРАНТ!</b>")

    badges_str = "\n".join(badges)
    return (
        f"{title}\n"
        f"{r_meta['banner']}\n"
        f"👤 Выбил(а) • {player_mention}\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"{badges_str}\n\n"
        f"🃏 «<b>{card['name']}</b>» (№{num})\n"
        f"💎 Редкость • {r_meta['emoji']} <b>{r_meta['name']}</b> <code>[{stars}]</code>\n"
        f"{format_card_bonuses(card, level)}\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"🎯 Гарант: [{pity_bar}] <b>{new_pity}/{PITY_THRESHOLD}</b>"
    )


# ─────────────────────────────────────────────────────────────
#  ГАЙД ПО КАРТОЧКАМ (/card_help, /гайд_карты)
# ─────────────────────────────────────────────────────────────

@router.message(Command("card_help", "cards_help", "гайд_карты", "помощь_карты", "карт_гайд"))
async def cmd_card_help(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    ok, left = cooldowns.check(chat_id, user_id, "help_cmd")
    if not ok:
        warn = await message.reply(f"⏳ Гайд на КД: подождите <b>{fmt_seconds(left)}</b>.")
        asyncio.create_task(_auto_delete_later(warn, 4.0))
        return

    cooldowns.trigger(chat_id, user_id, "help_cmd")
    player_mention = format_player_mention(message.from_user)

    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Магазин кейсов", callback_data=f"card_shop_back_{user_id}")
    builder.button(text="🎒 Моя Коллекция", callback_data=f"card_page_0_all_{user_id}")
    builder.button(text="❌ Закрыть", callback_data=f"card_close_{user_id}")
    builder.adjust(2, 1)

    await message.answer(build_guide_text(player_mention), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("card_guide"))
async def callback_card_guide(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    parts = callback.data.split("_")
    if len(parts) >= 3 and parts[-1].isdigit():
        if callback.from_user.id != int(parts[-1]):
            return await callback.answer("⚠️ Это не ваше меню!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    ok_cb, left_cb = cooldowns.check(chat_id, user_id, "callback")
    if not ok_cb:
        return await callback.answer(f"⏳ {fmt_seconds(left_cb)}", show_alert=False)
    cooldowns.trigger(chat_id, user_id, "callback")

    player_mention = format_player_mention(callback.from_user)
    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 В Магазин", callback_data=f"card_shop_back_{user_id}")
    builder.button(text="🎒 Коллекция", callback_data=f"card_page_0_all_{user_id}")
    builder.button(text="❌ Закрыть", callback_data=f"card_close_{user_id}")
    builder.adjust(2, 1)

    await _safe_edit_text(callback.message, build_guide_text(player_mention), builder.as_markup())
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  БЕСПЛАТНЫЙ КЕЙС И СБРОС КД
# ─────────────────────────────────────────────────────────────

FREE_CASE_TRIGGERS = {
    "free_case", "freecase", "bonus_case", "bonuscase", "daily_case",
    "бесплатный_кейс", "бесплатныйкейс", "бк", "бонусный_кейс", "бонусныйкейс",
    "бесплатный кейс", "бонусный кейс", "бесплатный кейс свинок", "бк свинок",
    "/free_case", "/freecase", "/bonus_case", "/bonuscase", "/daily_case",
    "/бесплатный_кейс", "/бесплатныйкейс", "/бк", "/бонусный_кейс", "/бонусныйкейс",
    "/бесплатный кейс", "/бонусный кейс",
}


@router.message(Command("reset_free_case", "reset_bc", "сброс_бк", "reset_case"))
async def cmd_reset_free_case(message: types.Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    if not cooldowns.is_creator(user_id):
        return await message.answer("❌ Доступно только Создателю бота.")

    chat_id = message.chat.id
    target_id = user_id
    target_mention = format_player_mention(message.from_user)

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        target_mention = format_player_mention(message.reply_to_message.from_user)
    else:
        args = (message.text or "").split()
        if len(args) >= 2:
            target_user = await get_user_by_username_or_id(chat_id, args[1])
            if target_user:
                target_id = target_user["user_id"]
                safe_name = html.escape(target_user.get("full_name", f"Юзер {target_id}"))
                target_mention = f'<a href="tg://user?id={target_id}">{safe_name}</a>'

    await update_user_field(chat_id, target_id, "last_free_card_case_ts", 0)
    invalidate_user_cache(chat_id, target_id)

    await message.answer(
        f"⚡️ <b>Сброс выполнен!</b>\n\n"
        f"Кулдаун бесплатного кейса для {target_mention} обнулён! Команда <code>/бк</code> доступна прямо сейчас."
    )


@router.message(Command("free_case", "freecase", "bonus_case", "bonuscase", "daily_case", "бесплатный_кейс", "бесплатныйкейс", "бк", "бонусный_кейс", "бонусныйкейс"))
@router.message(F.text.func(lambda t: t and t.strip().lower() in FREE_CASE_TRIGGERS))
async def cmd_free_case(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    player_mention = format_player_mention(message.from_user)

    if (chat_id, user_id) in ACTIVE_OPENINGS:
        return

    ok_spam, left_spam = cooldowns.check(chat_id, user_id, "free_case_spam")
    if not ok_spam:
        warn = await message.reply(f"⏳ Не спамьте <code>/бк</code>! Попробуйте через <b>{fmt_seconds(left_spam)}</b>.")
        asyncio.create_task(_auto_delete_later(warn, 5.0))
        return

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        if (chat_id, user_id) in ACTIVE_OPENINGS:
            return
        pre_data = await get_user_data(chat_id, user_id, message.from_user.full_name)
        if pre_data.get("is_banned"):
            return
        was_owned_map = pre_data.get("meme_cards", {}) or {}
        pity_count = int(pre_data.get("card_pity", 0))

        case_info = CASES["free_case"]
        card_id, triggered_pity = roll_card_from_case(case_info, user_id=user_id, pity_count=pity_count)
        if not card_id:
            return await message.answer("Ошибка сервиса карточек.")

        was_owned = was_owned_map.get(card_id, 0) > 0
        db = get_db()

        @firestore_async.async_transactional
        async def _run_tx(transaction):
            return await open_free_case_tr(transaction, chat_id, user_id, card_id)

        try:
            tr = db.transaction() if db else None
            success, err = await _run_tx(tr)
        except Exception as e:
            logger.exception("Ошибка транзакции бесплатного кейса (chat=%s, user=%s): %s", chat_id, user_id, e)
            return await message.answer("Произошла ошибка при открытии кейса. Попробуйте позже.")

        if not success:
            cooldowns.trigger(chat_id, user_id, "free_case_spam")
            return await message.answer(f"{player_mention}, {err}")

        ACTIVE_OPENINGS.add((chat_id, user_id))
        cooldowns.trigger(chat_id, user_id, "case_open")
        invalidate_user_cache(chat_id, user_id)
        gained_shards, new_pity = await _process_drop_rewards(
            chat_id, user_id, card_id, was_owned, triggered_pity, pre_data
        )

    try:
        slides = _build_animation_slides(player_mention, CARDS[card_id]["rarity"])
        msg = await message.answer(slides[0])
        for slide in slides[1:]:
            await asyncio.sleep(ANIMATION_DELAY)
            await _safe_edit_text(msg, slide)
        await asyncio.sleep(0.25)
        await _safe_delete(msg)

        lvl = get_card_level(pre_data, card_id)
        caption = _build_drop_caption(
            "🎁 <b>БЕСПЛАТНЫЙ КЕЙС (12ч) ОТКРЫТ!</b>",
            player_mention, card_id, was_owned, gained_shards, new_pity, triggered_pity, lvl
        )
        is_fav = pre_data.get("favorite_card_id") == card_id
        await send_card_message(
            message, card_id, caption, reply_markup=build_card_caption_markup(card_id, user_id, is_fav)
        )
    finally:
        ACTIVE_OPENINGS.discard((chat_id, user_id))


@router.callback_query(F.data.startswith("open_free_case_cb"))
async def callback_open_free_case(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    parts = callback.data.split("_")
    if len(parts) >= 5 and parts[4].isdigit():
        if callback.from_user.id != int(parts[4]):
            return await callback.answer("⚠️ Это не ваша кнопка!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    player_mention = format_player_mention(callback.from_user)

    if (chat_id, user_id) in ACTIVE_OPENINGS:
        return await callback.answer("⏳ Кейс уже открывается!", show_alert=False)

    ok_cb, left_cb = cooldowns.check(chat_id, user_id, "callback")
    if not ok_cb:
        return await callback.answer(f"⏳ Не так быстро ({fmt_seconds(left_cb)})", show_alert=False)
    cooldowns.trigger(chat_id, user_id, "callback")

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        if (chat_id, user_id) in ACTIVE_OPENINGS:
            return await callback.answer("⏳ Кейс уже открывается!", show_alert=False)
        pre_data = await get_user_data(chat_id, user_id)
        if pre_data.get("is_banned"):
            return await callback.answer("Вы забанены.", show_alert=True)
        was_owned_map = pre_data.get("meme_cards", {}) or {}
        pity_count = int(pre_data.get("card_pity", 0))

        case_info = CASES["free_case"]
        card_id, triggered_pity = roll_card_from_case(case_info, user_id=user_id, pity_count=pity_count)
        if not card_id:
            return await callback.answer("Ошибка ролла карточки.", show_alert=True)

        was_owned = was_owned_map.get(card_id, 0) > 0
        db = get_db()

        @firestore_async.async_transactional
        async def _run_tx(transaction):
            return await open_free_case_tr(transaction, chat_id, user_id, card_id)

        try:
            tr = db.transaction() if db else None
            success, err = await _run_tx(tr)
        except Exception as e:
            logger.exception("Ошибка транзакции бесплатного кейса callback: %s", e)
            return await callback.answer("Произошла ошибка при открытии кейса.", show_alert=True)

        if not success:
            return await callback.answer(err, show_alert=True)

        ACTIVE_OPENINGS.add((chat_id, user_id))
        cooldowns.trigger(chat_id, user_id, "case_open")
        invalidate_user_cache(chat_id, user_id)
        gained_shards, new_pity = await _process_drop_rewards(
            chat_id, user_id, card_id, was_owned, triggered_pity, pre_data
        )

    await callback.answer("Открываем бесплатный кейс...")
    try:
        slides = _build_animation_slides(player_mention, CARDS[card_id]["rarity"])
        for slide in slides:
            await _safe_edit_text(callback.message, slide)
            await asyncio.sleep(ANIMATION_DELAY)
        await _safe_delete(callback.message)

        lvl = get_card_level(pre_data, card_id)
        caption = _build_drop_caption(
            "🎁 <b>БЕСПЛАТНЫЙ КЕЙС (12ч) ОТКРЫТ!</b>",
            player_mention, card_id, was_owned, gained_shards, new_pity, triggered_pity, lvl
        )
        is_fav = pre_data.get("favorite_card_id") == card_id
        await send_card_message(
            callback.message, card_id, caption, reply_markup=build_card_caption_markup(card_id, user_id, is_fav)
        )
    finally:
        ACTIVE_OPENINGS.discard((chat_id, user_id))


# ─────────────────────────────────────────────────────────────
#  МАГАЗИН КЕЙСОВ (/cases)
# ─────────────────────────────────────────────────────────────

@router.message(Command("cases", "card_shop", "кейсы"))
async def cmd_cases(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    ok, left = cooldowns.check(chat_id, user_id, "shop_cmd")
    if not ok:
        warn = await message.reply(f"⏳ Магазин кейсов на КД: подождите <b>{fmt_seconds(left)}</b>.")
        asyncio.create_task(_auto_delete_later(warn, 5.0))
        return

    data = await get_user_data(chat_id, user_id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    cooldowns.trigger(chat_id, user_id, "shop_cmd")
    player_mention = format_player_mention(message.from_user)
    await message.answer(
        build_shop_text(data, player_mention),
        reply_markup=build_shop_keyboard(user_id=user_id),
    )


@router.callback_query(F.data.startswith("card_shop_back"))
async def callback_shop_back(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    parts = callback.data.split("_")
    if len(parts) >= 4 and parts[3].isdigit():
        if callback.from_user.id != int(parts[3]):
            return await callback.answer("⚠️ Это не ваше меню!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    ok_cb, left_cb = cooldowns.check(chat_id, user_id, "callback")
    if not ok_cb:
        return await callback.answer(f"⏳ Подождите {fmt_seconds(left_cb)}", show_alert=False)
    cooldowns.trigger(chat_id, user_id, "callback")

    data = await get_user_data(chat_id, user_id)
    if data.get("is_banned"):
        return await callback.answer("Вы забанены.", show_alert=True)

    player_mention = format_player_mention(callback.from_user)
    ok_edit = await _safe_edit_text(
        callback.message, build_shop_text(data, player_mention), build_shop_keyboard(user_id=user_id)
    )
    if not ok_edit:
        await callback.message.answer(
            build_shop_text(data, player_mention),
            reply_markup=build_shop_keyboard(user_id=user_id),
        )
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  ПОКУПКА И ОТКРЫТИЕ ПЛАТНОГО КЕЙСА
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("card_buy_"))
async def callback_buy_case(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer("Сообщение устарело, вызовите /cases заново.", show_alert=True)

    raw_data = callback.data.removeprefix("card_buy_")
    parts = raw_data.split("_")
    if len(parts) >= 2 and parts[-1].isdigit():
        owner_id = int(parts[-1])
        case_id = "_".join(parts[:-1])
        if callback.from_user.id != owner_id:
            return await callback.answer("⚠️ Это не ваше меню кейсов!", show_alert=True)
    else:
        case_id = raw_data

    case_info = CASES.get(case_id)
    if not case_info:
        return await callback.answer("Кейс не найден.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    player_mention = format_player_mention(callback.from_user)

    if (chat_id, user_id) in ACTIVE_OPENINGS:
        return await callback.answer("⏳ Предыдущий кейс ещё открывается!", show_alert=False)

    ok_cd, left_cd = cooldowns.check(chat_id, user_id, "case_open")
    if not ok_cd:
        return await callback.answer(
            f"⏳ КД на открытие кейсов: осталось {fmt_seconds(left_cd)}!",
            show_alert=True,
        )

    price = case_info["price"]
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        if (chat_id, user_id) in ACTIVE_OPENINGS:
            return await callback.answer("⏳ Кейс уже открывается!", show_alert=False)
        ok_cd2, left_cd2 = cooldowns.check(chat_id, user_id, "case_open")
        if not ok_cd2:
            return await callback.answer(f"⏳ КД: {fmt_seconds(left_cd2)}", show_alert=True)

        pre_data = await get_user_data(chat_id, user_id)
        if pre_data.get("is_banned"):
            return await callback.answer("Вы забанены.", show_alert=True)
        was_owned_map = pre_data.get("meme_cards", {}) or {}
        pity_count = int(pre_data.get("card_pity", 0))

        card_id, triggered_pity = roll_card_from_case(case_info, user_id=user_id, pity_count=pity_count)
        if card_id is None:
            return await callback.answer("Ошибка: нет карточек этой редкости.", show_alert=True)

        was_owned = was_owned_map.get(card_id, 0) > 0
        db = get_db()

        @firestore_async.async_transactional
        async def _run_tx(transaction):
            return await buy_and_open_case_tr(transaction, chat_id, user_id, price, card_id)

        try:
            tr = db.transaction() if db else None
            success, error_msg = await _run_tx(tr)
        except Exception as e:
            logger.exception("Ошибка транзакции покупки кейса (chat=%s, user=%s): %s", chat_id, user_id, e)
            return await callback.answer("Произошла ошибка при покупке. Попробуйте позже.", show_alert=True)

        if not success:
            return await callback.answer(f"Ошибка: {error_msg}", show_alert=True)

        ACTIVE_OPENINGS.add((chat_id, user_id))
        cooldowns.trigger(chat_id, user_id, "case_open")
        invalidate_user_cache(chat_id, user_id)
        gained_shards, new_pity = await _process_drop_rewards(
            chat_id, user_id, card_id, was_owned, triggered_pity, pre_data
        )

    await callback.answer("Открываем кейс...")
    try:
        slides = _build_animation_slides(player_mention, CARDS[card_id]["rarity"])
        for slide in slides:
            await _safe_edit_text(callback.message, slide)
            await asyncio.sleep(ANIMATION_DELAY)
        await _safe_delete(callback.message)

        lvl = get_card_level(pre_data, card_id)
        caption = _build_drop_caption(
            f"{case_info['name']} <b>ОТКРЫТ!</b>",
            player_mention, card_id, was_owned, gained_shards, new_pity, triggered_pity, lvl
        )
        is_fav = pre_data.get("favorite_card_id") == card_id
        await send_card_message(
            callback.message, card_id, caption, reply_markup=build_card_caption_markup(card_id, user_id, is_fav)
        )
    finally:
        ACTIVE_OPENINGS.discard((chat_id, user_id))


# ─────────────────────────────────────────────────────────────
#  КУЗНИЦА КАРТ (/forge, /кузница) + ЗАКАЛКА КАРТ
# ─────────────────────────────────────────────────────────────

def build_forge_text(data: dict, player_mention: Optional[str] = None) -> str:
    shards = int(data.get("card_shards", 0))
    meme_cards = data.get("meme_cards", {}) or {}
    owner_line = f"👤 Мастер • {player_mention}\n" if player_mention else ""

    lines = [
        "🔨 <b>КУЗНИЦА КАРТОЧЕК</b> 🔨",
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈",
        f"{owner_line}🧀 Сырные Осколки: <b>{fmt_num(shards)}</b>\n",
        "<i>Дубликаты дают осколки. Здесь можно выковать <b>ещё не открытую</b> карту! "
        "А в /card_info можно <b>⬆️ Закалить</b> уже открытую карту (за дубликат + осколки).</i>\n",
    ]
    for r in ("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"):
        cost = CRAFT_COSTS[r]
        pool = CARDS_BY_RARITY.get(r, [])
        missing = sum(1 for cid in pool if meme_cards.get(cid, 0) <= 0)
        status = f"осталось {missing} шт." if missing > 0 else "✅ все собраны"
        lines.append(
            f"{get_rarity_emoji(r)} <b>{get_rarity_name(r)}</b> — <b>{cost}</b> 🧀 ({status})"
        )
    return "\n".join(lines)


def build_forge_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in ("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"):
        builder.button(
            text=f"{get_rarity_emoji(r)} {get_rarity_name(r)} ({CRAFT_COSTS[r]} 🧀)",
            callback_data=f"card_craft_{r}_{user_id}",
        )
    builder.button(text="🛒 В Магазин", callback_data=f"card_shop_back_{user_id}")
    builder.button(text="🎒 Коллекция", callback_data=f"card_page_0_all_{user_id}")
    builder.button(text="📖 Гайд", callback_data=f"card_guide_{user_id}")
    builder.button(text="❌ Закрыть", callback_data=f"card_close_{user_id}")
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup()


@router.message(Command("forge", "кузница", "craft"))
async def cmd_forge(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    ok, left = cooldowns.check(chat_id, user_id, "craft")
    if not ok:
        warn = await message.reply(f"⏳ Кузница остывает: подождите <b>{fmt_seconds(left)}</b>.")
        asyncio.create_task(_auto_delete_later(warn, 4.0))
        return

    data = await get_user_data(chat_id, user_id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    cooldowns.trigger(chat_id, user_id, "craft")
    player_mention = format_player_mention(message.from_user)
    await message.answer(build_forge_text(data, player_mention), reply_markup=build_forge_keyboard(user_id))


@router.callback_query(F.data.startswith("card_forge"))
async def callback_forge_menu(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    parts = callback.data.split("_")
    if len(parts) >= 3 and parts[-1].isdigit():
        if callback.from_user.id != int(parts[-1]):
            return await callback.answer("⚠️ Это не ваша кузница!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    ok_cb, left_cb = cooldowns.check(chat_id, user_id, "callback")
    if not ok_cb:
        return await callback.answer(f"⏳ {fmt_seconds(left_cb)}", show_alert=False)
    cooldowns.trigger(chat_id, user_id, "callback")

    data = await get_user_data(chat_id, user_id)
    player_mention = format_player_mention(callback.from_user)
    await _safe_edit_text(callback.message, build_forge_text(data, player_mention), build_forge_keyboard(user_id))
    await callback.answer()


@router.callback_query(F.data.startswith("card_craft_"))
async def callback_craft_card(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    raw = callback.data.removeprefix("card_craft_")
    parts = raw.split("_")
    if len(parts) != 2 or not parts[1].isdigit():
        return await callback.answer("Ошибка данных.", show_alert=True)

    rarity, owner_id = parts[0], int(parts[1])
    if callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваша кузница!", show_alert=True)

    if rarity not in CRAFT_COSTS:
        return await callback.answer("Неизвестная редкость.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    player_mention = format_player_mention(callback.from_user)

    ok, left = cooldowns.check(chat_id, user_id, "craft")
    if not ok:
        return await callback.answer(f"⏳ КД кузницы: {fmt_seconds(left)}", show_alert=True)

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        ok2, left2 = cooldowns.check(chat_id, user_id, "craft")
        if not ok2:
            return await callback.answer(f"⏳ КД кузницы: {fmt_seconds(left2)}", show_alert=True)

        data = await get_user_data(chat_id, user_id)
        if data.get("is_banned"):
            return await callback.answer("Вы забанены.", show_alert=True)

        shards = int(data.get("card_shards", 0))
        cost = CRAFT_COSTS[rarity]
        if shards < cost:
            return await callback.answer(
                f"Недостаточно осколков! Нужно {cost} 🧀, у вас {shards} 🧀.",
                show_alert=True,
            )

        meme_cards = dict(data.get("meme_cards", {}) or {})
        pool = CARDS_BY_RARITY.get(rarity, [])
        missing = [cid for cid in pool if meme_cards.get(cid, 0) <= 0]
        if not missing:
            return await callback.answer("Вы уже собрали все карты этой редкости!", show_alert=True)

        new_card_id = random.choice(missing)
        meme_cards[new_card_id] = meme_cards.get(new_card_id, 0) + 1

        await update_user_field(chat_id, user_id, "card_shards", shards - cost)
        await update_user_field(chat_id, user_id, "meme_cards", meme_cards)
        invalidate_user_cache(chat_id, user_id)
        cooldowns.trigger(chat_id, user_id, "craft")

    card = CARDS[new_card_id]
    num = new_card_id.removeprefix("meme_")
    stars = get_rarity_stars(rarity)
    await callback.answer(f"✨ Выкована карта №{num}!")
    await _safe_delete(callback.message)

    caption = (
        "🔨 <b>КАРТА ВЫКОВАНА В КУЗНИЦЕ!</b>\n"
        f"{RARITIES[rarity]['banner']}\n"
        f"👤 Мастер • {player_mention}\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"🆕 «<b>{card['name']}</b>» (№{num})\n"
        f"💎 Редкость • {get_rarity_emoji(rarity)} <b>{get_rarity_name(rarity)}</b> <code>[{stars}]</code>\n"
        f"{format_card_bonuses(card, 1)}\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"🧀 Потрачено: <b>{cost}</b> осколков"
    )
    await send_card_message(
        callback.message, new_card_id, caption, reply_markup=build_card_caption_markup(new_card_id, user_id, False)
    )


@router.callback_query(F.data.startswith("card_temper_"))
async def callback_temper_card(callback: CallbackQuery):
    """Закалка карты: тратит 1 дубликат (оставляя минимум 1 карту) + осколки, повышая уровень и силу."""
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    raw = callback.data.removeprefix("card_temper_")
    parts = raw.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await callback.answer("Ошибка данных.", show_alert=True)

    card_key, owner_id = parts[0], int(parts[1])
    if callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваша карточка!", show_alert=True)
    if card_key not in CARDS:
        return await callback.answer("Карта не найдена.", show_alert=True)

    chat_id = callback.message.chat.id
    ok, left = cooldowns.check(chat_id, owner_id, "craft")
    if not ok:
        return await callback.answer(f"⏳ КД закалки: {fmt_seconds(left)}", show_alert=True)

    lock = get_user_lock(chat_id, owner_id)
    async with lock:
        data = await get_user_data(chat_id, owner_id)
        meme_cards = dict(data.get("meme_cards", {}) or {})
        count = meme_cards.get(card_key, 0)
        if count < 2:
            return await callback.answer("Нужен хотя бы 1 дубликат (2+ шт. карты) для закалки!", show_alert=True)

        lvl = get_card_level(data, card_key)
        if lvl >= MAX_CARD_LEVEL:
            return await callback.answer("Карта уже максимального уровня!", show_alert=True)

        rarity = CARDS[card_key]["rarity"]
        cost = get_temper_cost(rarity, lvl)
        shards = int(data.get("card_shards", 0))
        if shards < cost:
            return await callback.answer(f"Недостаточно осколков! Нужно {cost} 🧀, у вас {shards} 🧀.", show_alert=True)

        new_lvl = lvl + 1
        meme_cards[card_key] = count - 1
        card_levels = dict(data.get("card_levels", {}) or {})
        card_levels[card_key] = new_lvl

        await update_user_field(chat_id, owner_id, "meme_cards", meme_cards)
        await update_user_field(chat_id, owner_id, "card_shards", shards - cost)
        await update_user_field(chat_id, owner_id, "card_levels", card_levels)
        invalidate_user_cache(chat_id, owner_id)
        cooldowns.trigger(chat_id, owner_id, "craft")

    card_info = CARDS[card_key]
    card_num = card_key.removeprefix("meme_")
    stars = get_rarity_stars(rarity)
    player_mention = format_player_mention(callback.from_user)
    new_count = meme_cards[card_key]
    is_fav = data.get("favorite_card_id") == card_key
    can_temper_more = new_count >= 2 and new_lvl < MAX_CARD_LEVEL
    next_cost = get_temper_cost(rarity, new_lvl) if can_temper_more else 0

    new_caption = _trim_caption(
        f"🔥 <b>ЗАКАЛКА УСПЕШНА! (Ур. {new_lvl}/{MAX_CARD_LEVEL})</b>\n"
        f"🃏 «<b>{card_info['name']}</b>» (№{card_num})\n"
        f"👤 Владелец • {player_mention}\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"💎 Редкость • {get_rarity_emoji(rarity)} <b>{get_rarity_name(rarity)}</b> <code>[{stars}]</code>\n"
        f"📜 Описание • <i>{card_info['description']}</i>\n\n"
        f"{format_card_bonuses(card_info, new_lvl)}\n"
        f"🎒 В инвентаре • <b>{new_count} шт.</b>"
    )
    try:
        await callback.message.edit_caption(
            caption=new_caption,
            reply_markup=build_card_caption_markup(card_key, owner_id, is_fav, can_temper_more, next_cost),
        )
    except Exception:
        pass
    await callback.answer(f"🔥 Карта закалена до Ур. {new_lvl}!")


# ─────────────────────────────────────────────────────────────
#  КОЛЛЕКЦИЯ КАРТОЧЕК (/cards) И СЕТЫ (/sets) С НАГРАДАМИ
# ─────────────────────────────────────────────────────────────

FILTER_LABELS = {
    "all": "Все",
    "owned": "Открытые",
    "missing": "Неоткрытые",
    "top": "Редкие+",
}


def _get_filtered_keys(meme_cards: dict, flt: str) -> list[str]:
    if flt == "owned":
        return [k for k in SORTED_CARD_KEYS if meme_cards.get(k, 0) > 0]
    if flt == "missing":
        return [k for k in SORTED_CARD_KEYS if meme_cards.get(k, 0) <= 0]
    if flt == "top":
        top_rarities = {"RARE", "EPIC", "LEGENDARY", "MYTHIC", "SECRET"}
        return [k for k in SORTED_CARD_KEYS if CARDS[k]["rarity"] in top_rarities]
    return SORTED_CARD_KEYS


def _build_sets_view(data: dict, user_id: int, player_mention: str) -> tuple[str, InlineKeyboardMarkup]:
    meme_cards = data.get("meme_cards", {}) or {}
    claimed = set(data.get("claimed_card_sets", []) or [])

    lines = [
        "📚 <b>ТЕМАТИЧЕСКИЕ СЕТЫ КАРТОЧЕК</b>",
        f"👤 Игрок • {player_mention}",
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n",
    ]
    builder = InlineKeyboardBuilder()
    claim_buttons = 0

    for set_id, s in CARD_SETS.items():
        have = sum(1 for cid in s["cards"] if meme_cards.get(cid, 0) > 0)
        total = len(s["cards"])
        bar = make_progress_bar(have, total, 8)
        reward = s["reward_shards"]

        if set_id in claimed:
            status = f"✅ Награда получена (+{reward} 🧀)"
        elif have == total:
            status = f"🎁 Готово! (+{reward} 🧀)"
            builder.button(text=f"🎁 Забрать: {s['name']} (+{reward} 🧀)", callback_data=f"card_setclaim_{set_id}_{user_id}")
            claim_buttons += 1
        else:
            status = f"{have}/{total} (приз +{reward} 🧀)"

        nums = ", ".join(f"№{cid.removeprefix('meme_')}" for cid in s["cards"])
        lines.append(f"<b>{s['name']}</b> [{bar}] <b>{status}</b>\n<i>Карты: {nums}</i>\n")

    builder.button(text="🎒 Коллекция", callback_data=f"card_page_0_all_{user_id}")
    builder.button(text="❌ Закрыть", callback_data=f"card_close_{user_id}")
    layout = [1] * claim_buttons + [2]
    builder.adjust(*layout)
    return "\n".join(lines), builder.as_markup()


@router.message(Command("cards", "collection", "карты", "карточки"))
async def cmd_cards(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    ok, left = cooldowns.check(chat_id, user_id, "collection_cmd")
    if not ok:
        warn = await message.reply(f"⏳ Коллекция на КД: подождите <b>{fmt_seconds(left)}</b>.")
        asyncio.create_task(_auto_delete_later(warn, 5.0))
        return

    data = await get_user_data(chat_id, user_id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    cooldowns.trigger(chat_id, user_id, "collection_cmd")
    player_mention = format_player_mention(message.from_user)
    await render_collection_page(
        message, data, page=0, flt="all", as_new=True, user_id=user_id, player_mention=player_mention
    )


@router.message(Command("sets", "сеты"))
async def cmd_sets(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    ok, left = cooldowns.check(chat_id, user_id, "collection_cmd")
    if not ok:
        warn = await message.reply(f"⏳ Подождите <b>{fmt_seconds(left)}</b>.")
        asyncio.create_task(_auto_delete_later(warn, 4.0))
        return

    data = await get_user_data(chat_id, user_id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    cooldowns.trigger(chat_id, user_id, "collection_cmd")
    text, markup = _build_sets_view(data, user_id, format_player_mention(message.from_user))
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("card_sets_"))
async def callback_sets_menu(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    owner_str = callback.data.removeprefix("card_sets_")
    if owner_str.isdigit() and callback.from_user.id != int(owner_str):
        return await callback.answer("⚠️ Это не ваше меню!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    ok_cb, left_cb = cooldowns.check(chat_id, user_id, "callback")
    if not ok_cb:
        return await callback.answer(f"⏳ {fmt_seconds(left_cb)}", show_alert=False)
    cooldowns.trigger(chat_id, user_id, "callback")

    data = await get_user_data(chat_id, user_id)
    text, markup = _build_sets_view(data, user_id, format_player_mention(callback.from_user))
    await _safe_edit_text(callback.message, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("card_setclaim_"))
async def callback_claim_set(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    raw = callback.data.removeprefix("card_setclaim_")
    parts = raw.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await callback.answer("Ошибка.", show_alert=True)

    set_id, owner_id = parts[0], int(parts[1])
    if callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваше меню!", show_alert=True)
    if set_id not in CARD_SETS:
        return await callback.answer("Сет не найден.", show_alert=True)

    chat_id = callback.message.chat.id
    lock = get_user_lock(chat_id, owner_id)
    async with lock:
        data = await get_user_data(chat_id, owner_id)
        claimed = list(data.get("claimed_card_sets", []) or [])
        if set_id in claimed:
            return await callback.answer("Награда за этот сет уже получена!", show_alert=True)

        meme_cards = data.get("meme_cards", {}) or {}
        s = CARD_SETS[set_id]
        if not all(meme_cards.get(cid, 0) > 0 for cid in s["cards"]):
            return await callback.answer("Сначала соберите все карты этого сета!", show_alert=True)

        reward = s["reward_shards"]
        claimed.append(set_id)
        new_shards = int(data.get("card_shards", 0)) + reward
        await update_user_field(chat_id, owner_id, "claimed_card_sets", claimed)
        await update_user_field(chat_id, owner_id, "card_shards", new_shards)
        invalidate_user_cache(chat_id, owner_id)

    updated = await get_user_data(chat_id, owner_id)
    text, markup = _build_sets_view(updated, owner_id, format_player_mention(callback.from_user))
    await _safe_edit_text(callback.message, text, markup)
    await callback.answer(f"🎁 Получено +{reward} 🧀 осколков за сет!", show_alert=True)


@router.callback_query(F.data.startswith("card_page_"))
async def callback_card_page(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    raw_data = callback.data.removeprefix("card_page_")
    parts = raw_data.split("_")

    flt = "all"
    if len(parts) >= 3 and parts[-1].isdigit():
        owner_id = int(parts[-1])
        if callback.from_user.id != owner_id:
            return await callback.answer("⚠️ Это не ваша коллекция!", show_alert=True)
        page_str, flt = parts[0], parts[1]
    elif len(parts) == 2 and parts[1].isdigit():
        owner_id = int(parts[1])
        if callback.from_user.id != owner_id:
            return await callback.answer("⚠️ Это не ваша коллекция!", show_alert=True)
        page_str = parts[0]
    else:
        page_str = parts[0]

    if flt not in FILTER_LABELS:
        flt = "all"

    try:
        page = int(page_str)
    except ValueError:
        return await callback.answer("Некорректная страница.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    ok_cb, left_cb = cooldowns.check(chat_id, user_id, "callback")
    if not ok_cb:
        return await callback.answer(f"⏳ {fmt_seconds(left_cb)}", show_alert=False)
    cooldowns.trigger(chat_id, user_id, "callback")

    data = await get_user_data(chat_id, user_id)
    if data.get("is_banned"):
        return await callback.answer("Вы забанены.", show_alert=True)

    player_mention = format_player_mention(callback.from_user)
    await render_collection_page(
        callback.message, data, page=page, flt=flt, as_new=False, user_id=user_id, player_mention=player_mention
    )
    await callback.answer()


@router.callback_query(F.data.startswith("card_close"))
@router.callback_query(F.data.startswith("inv_close"))
async def callback_close_menu(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    parts = callback.data.split("_")
    if len(parts) >= 3 and parts[-1].isdigit():
        if callback.from_user.id != int(parts[-1]):
            return await callback.answer("⚠️ Это не ваше меню!", show_alert=True)

    await _safe_delete(callback.message)
    await callback.answer()


@router.callback_query(F.data == "none")
async def callback_noop(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass


async def render_collection_page(
    message: types.Message,
    data: dict,
    page: int,
    flt: str = "all",
    as_new: bool = False,
    user_id: Optional[int] = None,
    player_mention: Optional[str] = None,
):
    meme_cards = data.get("meme_cards", {}) or {}
    opened_count = sum(1 for count in meme_cards.values() if count > 0)

    bonuses = get_user_meme_bonuses(data)
    total_mult = round(bonuses["multiplier"] * 100, 1)
    total_flat = bonuses["flat"]
    shards = int(data.get("card_shards", 0))
    fav_id = data.get("favorite_card_id")

    filtered_keys = _get_filtered_keys(meme_cards, flt)
    total_pages = max(1, (len(filtered_keys) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_keys = filtered_keys[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    progress_bar = make_progress_bar(opened_count, TOTAL_CARDS, 10)
    pct = round((opened_count / TOTAL_CARDS) * 100, 1)

    rarity_summary = " ".join(
        f"{get_rarity_emoji(r)}{sum(1 for k in CARDS_BY_RARITY.get(r, []) if meme_cards.get(k, 0) > 0)}"
        for r in RARITY_ORDER
    )

    owner_line = f"👤 Владелец • {player_mention}\n" if player_mention else ""
    lines = [
        "🎒 <b>КОЛЛЕКЦИЯ КАРТОЧЕК</b> 🎒",
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈",
        f"{owner_line}"
        f"[{progress_bar}] <b>{opened_count}/{TOTAL_CARDS}</b> ({pct}%)",
        f"🏷 {rarity_summary}",
        f"📈 Бонус: <b>+{total_mult}%</b> к /bonus | <b>+{fmt_num(total_flat)}</b> сыр./день",
        f"🧀 Осколки: <b>{fmt_num(shards)}</b> | 📦 Кейсов: <b>{data.get('opened_cases_count', 0)}</b>",
    ]
    if fav_id and fav_id in CARDS:
        lines.append(f"⭐️ Витрина: <b>{CARDS[fav_id]['name']}</b>")

    lines.append("┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈")
    lines.append(f"🔎 Фильтр: <b>{FILTER_LABELS.get(flt, 'Все')}</b> • Стр. <b>{page + 1}/{total_pages}</b>:")

    if not page_keys:
        lines.append("\n<i>По этому фильтру карточек пока нет.</i>")
    else:
        for key in page_keys:
            card = CARDS[key]
            num = key.removeprefix("meme_")
            count = meme_cards.get(key, 0)
            if count > 0:
                lvl = get_card_level(data, key)
                lvl_str = f" [Ур.{lvl}]" if lvl > 1 else ""
                mult_info = f"+{round(card['bonus_multiplier'] * 100, 1)}%" if card["bonus_multiplier"] > 0 else ""
                flat_info = f"+{fmt_num(card['bonus_flat'])} сыр." if card["bonus_flat"] > 0 else ""
                bonus_text = " / ".join(filter(None, [mult_info, flat_info]))
                lines.append(
                    f"▪️ {num}. {get_rarity_emoji(card['rarity'])} <b>{card['name']}</b>{lvl_str} "
                    f"— <b>{count} шт.</b> ({bonus_text})"
                )
            else:
                lines.append(
                    f"▪️ {num}. 🔒 <i>Не открыто</i> ({get_rarity_emoji(card['rarity'])} {get_rarity_name(card['rarity'])})"
                )

    lines.append(f"\n💡 <code>/card_info [1-{TOTAL_CARDS} или название]</code> — осмотр и закалка")
    text = "\n".join(lines)

    uid_suffix = f"_{user_id}" if user_id is not None else ""
    builder = InlineKeyboardBuilder()

    if page > 0:
        builder.button(text="⬅️ Назад", callback_data=f"card_page_{page - 1}_{flt}{uid_suffix}")
    else:
        builder.button(text="🛑 Начало", callback_data="none")

    builder.button(text="❌ Закрыть", callback_data=f"card_close{uid_suffix}")

    if page < total_pages - 1:
        builder.button(text="Вперёд ➡️", callback_data=f"card_page_{page + 1}_{flt}{uid_suffix}")
    else:
        builder.button(text="🛑 Конец", callback_data="none")

    for f_key, f_label in FILTER_LABELS.items():
        mark = "• " if f_key == flt else ""
        builder.button(text=f"{mark}{f_label}", callback_data=f"card_page_0_{f_key}{uid_suffix}")

    builder.button(text="🛒 Кейсы", callback_data=f"card_shop_back{uid_suffix}")
    builder.button(text="🔨 Кузница", callback_data=f"card_forge{uid_suffix}")
    builder.button(text="📚 Сеты", callback_data=f"card_sets{uid_suffix}")
    builder.button(text="📖 Гайд", callback_data=f"card_guide{uid_suffix}")
    builder.adjust(3, 4, 2, 2)
    markup = builder.as_markup()

    if as_new:
        await message.answer(text, reply_markup=markup)
    else:
        ok_edit = await _safe_edit_text(message, text, markup)
        if not ok_edit and message.photo:
            await message.answer(text, reply_markup=markup)


# ─────────────────────────────────────────────────────────────
#  ПРОСМОТР КАРТОЧКИ (/card_info) + ВИТРИНА + ЗАКАЛКА
# ─────────────────────────────────────────────────────────────

@router.message(Command("card_info", "карта", "card"))
async def cmd_card_info(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    ok, left = cooldowns.check(chat_id, user_id, "card_info")
    if not ok:
        warn = await message.reply(
            f"⏳ Анти-спам КД на просмотр карт: подождите <b>{fmt_seconds(left)}</b>."
        )
        asyncio.create_task(_auto_delete_later(warn, 5.0))
        return

    data = await get_user_data(chat_id, user_id, message.from_user.full_name)
    if data.get("is_banned"):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer(
            f"Укажите номер или часть названия: <code>/card_info [1-{TOTAL_CARDS}]</code> или <code>/card_info дракон</code>"
        )

    query = parts[1].strip()
    card_key: Optional[str] = None

    if query.isdigit():
        candidate = f"meme_{int(query)}"
        if candidate in CARDS:
            card_key = candidate
    else:
        q_low = query.lower()
        for k in SORTED_CARD_KEYS:
            if q_low in CARDS[k]["name"].lower():
                card_key = k
                break

    if not card_key:
        safe_q = html.escape(query)
        return await message.answer(
            f"Карточка «<b>{safe_q}</b>» не найдена. Введите номер от 1 до {TOTAL_CARDS} или слово из названия."
        )

    cooldowns.trigger(chat_id, user_id, "card_info")

    card_info = CARDS[card_key]
    card_num = card_key.removeprefix("meme_")
    count = (data.get("meme_cards", {}) or {}).get(card_key, 0)
    rarity = card_info["rarity"]
    stars = get_rarity_stars(rarity)
    lvl = get_card_level(data, card_key)
    player_mention = format_player_mention(message.from_user)

    if count > 0:
        status_str = f"🎒 В инвентаре • <b>{count} шт.</b>"
        is_fav = data.get("favorite_card_id") == card_key
        can_temper = count >= 2 and lvl < MAX_CARD_LEVEL
        temper_cost = get_temper_cost(rarity, lvl) if can_temper else 0
        markup = build_card_caption_markup(card_key, user_id, is_fav, can_temper, temper_cost)
    else:
        sources = [c["name"] for c in CASES.values() if rarity in c["chances"]]
        src_hint = ", ".join(sources[:3]) if sources else "тайных источниках"
        craft_hint = f" или в <code>/forge</code> ({CRAFT_COSTS[rarity]} 🧀)" if rarity in CRAFT_COSTS else ""
        status_str = f"🔒 <i>Не открыта</i>\n💡 Где взять: {src_hint}{craft_hint}"
        markup = None

    text = (
        f"🃏 «<b>{card_info['name']}</b>» (№{card_num})\n"
        f"👤 Осматривает • {player_mention}\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"💎 Редкость • {get_rarity_emoji(rarity)} <b>{get_rarity_name(rarity)}</b> <code>[{stars}]</code>\n"
        f"📜 Описание • <i>{card_info['description']}</i>\n\n"
        f"{format_card_bonuses(card_info, lvl)}\n"
        f"{status_str}"
    )

    await send_card_message(message, card_key, text, reply_markup=markup)


@router.callback_query(F.data.startswith("card_fav_"))
async def callback_set_favorite(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    raw = callback.data.removeprefix("card_fav_")
    parts = raw.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await callback.answer("Ошибка.", show_alert=True)

    card_key, owner_id = parts[0], int(parts[1])
    if callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваша карточка!", show_alert=True)

    chat_id = callback.message.chat.id
    ok_cb, left_cb = cooldowns.check(chat_id, owner_id, "callback")
    if not ok_cb:
        return await callback.answer(f"⏳ {fmt_seconds(left_cb)}", show_alert=False)
    cooldowns.trigger(chat_id, owner_id, "callback")

    data = await get_user_data(chat_id, owner_id)
    count = (data.get("meme_cards", {}) or {}).get(card_key, 0)
    if count <= 0:
        return await callback.answer("Сначала откройте эту карту!", show_alert=True)

    current_fav = data.get("favorite_card_id")
    new_fav = None if current_fav == card_key else card_key
    await update_user_field(chat_id, owner_id, "favorite_card_id", new_fav)
    invalidate_user_cache(chat_id, owner_id)

    lvl = get_card_level(data, card_key)
    rarity = CARDS[card_key]["rarity"]
    can_temper = count >= 2 and lvl < MAX_CARD_LEVEL
    temper_cost = get_temper_cost(rarity, lvl) if can_temper else 0

    try:
        await callback.message.edit_reply_markup(
            reply_markup=build_card_caption_markup(card_key, owner_id, (new_fav is not None), can_temper, temper_cost)
        )
    except Exception:
        pass

    await callback.answer("⭐️ Карта поставлена на Витрину!" if new_fav else "Карта убрана с Витрины.")


# ─────────────────────────────────────────────────────────────
#  МИНИ-ИГРА: КАРТОЧНАЯ ДУЭЛЬ (/card_duel, /дуэль_карт)
# ─────────────────────────────────────────────────────────────

def _pick_best_or_fav_card(data: dict) -> Optional[str]:
    meme_cards = data.get("meme_cards", {}) or {}
    owned = [cid for cid, cnt in meme_cards.items() if cnt > 0 and cid in CARDS]
    if not owned:
        return None
    fav = data.get("favorite_card_id")
    if fav and fav in owned:
        return fav
    return max(owned, key=lambda cid: get_effective_power(cid, get_card_level(data, cid)))


@router.message(Command("card_duel", "дуэль_карт", "cduel"))
async def cmd_card_duel(message: types.Message):
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    _cleanup_expired_duels()

    ok, left = cooldowns.check(chat_id, user_id, "duel")
    if not ok:
        warn = await message.reply(f"⏳ Дуэли на КД: подождите <b>{fmt_seconds(left)}</b>.")
        asyncio.create_task(_auto_delete_later(warn, 5.0))
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.answer("⚔️ Ответьте на сообщение игрока командой <code>/card_duel</code>, чтобы вызвать его на битву карт!")

    target = message.reply_to_message.from_user
    if target.is_bot or target.id == user_id:
        return await message.answer("❌ Нельзя вызвать на дуэль бота или самого себя.")

    p1_data = await get_user_data(chat_id, user_id, message.from_user.full_name)
    p2_data = await get_user_data(chat_id, target.id, target.full_name)
    if p1_data.get("is_banned") or p2_data.get("is_banned"):
        return

    c1 = _pick_best_or_fav_card(p1_data)
    c2 = _pick_best_or_fav_card(p2_data)
    p1_mention = format_player_mention(message.from_user)
    p2_mention = format_player_mention(target)

    if not c1:
        return await message.answer("У вас нет ни одной карты! Откройте <code>/бк</code> или <code>/cases</code>.")
    if not c2:
        return await message.answer(f"У {p2_mention} пока нет ни одной карты для дуэли.")

    cooldowns.trigger(chat_id, user_id, "duel")

    duel_id = f"{user_id}_{target.id}_{int(time.time())}"
    ACTIVE_DUELS[duel_id] = {
        "chat_id": chat_id,
        "p1_id": user_id,
        "p1_mention": p1_mention,
        "p2_id": target.id,
        "p2_mention": p2_mention,
        "expires": time.monotonic() + 90,
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Принять бой!", callback_data=f"cduel_acc_{duel_id}")
    builder.button(text="🏃 Отказаться", callback_data=f"cduel_dec_{duel_id}")
    builder.adjust(2)

    await message.answer(
        f"⚔️ <b>ВЫЗОВ НА КАРТОЧНУЮ ДУЭЛЬ!</b>\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"{p1_mention} вызывает {p2_mention} на битву свинок!\n"
        f"🏆 Награда победителю: <b>+15 🧀 Сырных Осколков</b>\n"
        f"<i>Сражаются карты с Витрины (учитывается уровень закалки).</i>",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("cduel_"))
async def callback_card_duel(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        return await callback.answer()

    parts = callback.data.split("_", 2)
    if len(parts) != 3:
        return await callback.answer()

    action, duel_id = parts[1], parts[2]
    duel = ACTIVE_DUELS.get(duel_id)
    if not duel or time.monotonic() > duel["expires"]:
        ACTIVE_DUELS.pop(duel_id, None)
        await _safe_edit_text(callback.message, "⌛️ Вызов на карточную дуэль истёк.")
        return await callback.answer("Время вышло.")

    if callback.from_user.id != duel["p2_id"]:
        return await callback.answer("⚠️ Вызов адресован другому игроку!", show_alert=True)

    ACTIVE_DUELS.pop(duel_id, None)
    if action == "dec":
        await _safe_edit_text(callback.message, f"🏃 {duel['p2_mention']} уклонился от карточной дуэли.")
        return await callback.answer("Вы отказались.")

    chat_id = duel["chat_id"]
    p1_data = await get_user_data(chat_id, duel["p1_id"])
    p2_data = await get_user_data(chat_id, duel["p2_id"])

    c1_id = _pick_best_or_fav_card(p1_data)
    c2_id = _pick_best_or_fav_card(p2_data)
    if not c1_id or not c2_id:
        return await callback.answer("Не найдены карты для боя.", show_alert=True)

    c1, c2 = CARDS[c1_id], CARDS[c2_id]
    l1, l2 = get_card_level(p1_data, c1_id), get_card_level(p2_data, c2_id)
    p1_eff = get_effective_power(c1_id, l1)
    p2_eff = get_effective_power(c2_id, l2)

    roll1 = int(p1_eff * random.uniform(0.85, 1.25))
    roll2 = int(p2_eff * random.uniform(0.85, 1.25))
    max_roll = max(1, roll1, roll2)

    bar1 = make_progress_bar(roll1, max_roll, 8)
    bar2 = make_progress_bar(roll2, max_roll, 8)

    if roll1 >= roll2:
        winner_id, winner_mention, winner_data = duel["p1_id"], duel["p1_mention"], p1_data
    else:
        winner_id, winner_mention, winner_data = duel["p2_id"], duel["p2_mention"], p2_data

    new_shards = int(winner_data.get("card_shards", 0)) + 15
    await update_user_field(chat_id, winner_id, "card_shards", new_shards)
    invalidate_user_cache(chat_id, winner_id)

    l1_tag = f" [Ур.{l1}]" if l1 > 1 else ""
    l2_tag = f" [Ур.{l2}]" if l2 > 1 else ""

    text = (
        "⚔️ <b>ИТОГИ КАРТОЧНОЙ ДУЭЛИ</b> ⚔️\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"👤 {duel['p1_mention']}\n"
        f"   {get_rarity_emoji(c1['rarity'])} {c1['name']}{l1_tag}\n"
        f"   [{bar1}] <b>{roll1} ⚡</b>\n\n"
        f"👤 {duel['p2_mention']}\n"
        f"   {get_rarity_emoji(c2['rarity'])} {c2['name']}{l2_tag}\n"
        f"   [{bar2}] <b>{roll2} ⚡</b>\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        f"🏆 Победил(а) {winner_mention}!\n"
        f"🎁 Приз: <b>+15 🧀 Сырных Осколков</b>"
    )
    await _safe_edit_text(callback.message, text)
    await callback.answer("Бой завершён!")