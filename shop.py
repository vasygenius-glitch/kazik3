from decimal import Decimal
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder

import asyncio
import logging
import time
from typing import Optional

from firebase_admin import firestore_async

from db import get_db
from user_manager import (
    get_user_data,
    buy_item_tr,
    sell_item_tr,
    sell_vip_tr,
)
from economy_utils import (
    calculate_progressive_tax,
    calculate_biz_markup,
    get_global_tax,
)
from seasons import get_season_string, get_glitch_text
from diseases import get_active_diseases

logger = logging.getLogger(__name__)
router = Router()

# ─────────────────────────────────────────────────────────────
#  КАТАЛОГ ТОВАРОВ
# ─────────────────────────────────────────────────────────────
ITEMS: dict[str, dict] = {
    # БИЗНЕСЫ
    "семечки":   {"name": "🌻 Продажа семечек", "price": 500,            "cat": "biz",   "action": "business", "income": 50},
    "газеты":    {"name": "📰 Газетный киоск",  "price": 1_200,          "cat": "biz",   "action": "business", "income": 120},
    "свип":      {"name": "🧹 Услуги дворника", "price": 2_500,          "cat": "biz",   "action": "business", "income": 250},
    "пирожки":   {"name": "🥐 Ларёк с пирожками","price": 4_500,          "cat": "biz",   "action": "business", "income": 450},
    "цветы":     {"name": "💐 Цветочный ларёк", "price": 7_000,          "cat": "biz",   "action": "business", "income": 700},
    "ларек":     {"name": "🏣 Торговый ларёк",  "price": 10_000,        "cat": "biz",   "action": "business", "income": 1_000},
    "шаурма":    {"name": "🏪 Ларёк с шаурмой", "price": 25_000,        "cat": "biz",   "action": "business", "income": 2_500},
    "мойка":     {"name": "🚿 Автомойка",       "price": 125_000,       "cat": "biz",   "action": "business", "income": 12_500},
    "вендинг":   {"name": "🍬 Вендинг",         "price": 200_000,       "cat": "biz",   "action": "business", "income": 20_000},
    "кофейня":   {"name": "☕️ Кофейня",         "price": 375_000,       "cat": "biz",   "action": "business", "income": 37_500},
    "ресторан":  {"name": "🍽 Ресторан",        "price": 750_000,       "cat": "biz",   "action": "business", "income": 75_000},
    "отель":     {"name": "🏨 Отель",           "price": 1_750_000,     "cat": "biz",   "action": "business", "income": 175_000},
    "ферма":     {"name": "🌽 Ферма",           "price": 3_000_000,     "cat": "biz",   "action": "business", "income": 300_000},
    "кинотеатр": {"name": "🎬 Кинотеатр",       "price": 5_000_000,     "cat": "biz",   "action": "business", "income": 450_000},
    "завод":     {"name": "🏭 Завод",           "price": 6_250_000,     "cat": "biz",   "action": "business", "income": 550_000},
    "салон":     {"name": "🚙 Автосалон",       "price": 12_500_000,    "cat": "biz",   "action": "business", "income": 1_000_000},
    "нефть":     {"name": "🛢 Вышка",           "price": 20_000_000,    "cat": "biz",   "action": "business", "income": 1_500_000},
    "банк":      {"name": "🏦 Банк",            "price": 35_000_000,    "cat": "biz",   "action": "business", "income": 2_200_000},
    "айти":      {"name": "💻 IT-компания",     "price": 50_000_000,    "cat": "biz",   "action": "business", "income": 3_000_000},
    "казино":    {"name": "🎰 Казино",          "price": 70_000_000,    "cat": "biz",   "action": "business", "income": 3_800_000},
    "стадион":   {"name": "🏟 Стадион",         "price": 85_000_000,    "cat": "biz",   "action": "business", "income": 4_500_000},
    "мегакорп":  {"name": "🏢 Мегакорпорация",   "price": 100_000_000,   "cat": "biz",   "action": "business", "income": 5_000_000},
    "sec_bunker": {"name": "🛡 Подземный Бункер", "price": 150_000_000, "cat": "biz", "action": "business", "income": 6_000_000, "desc": "Полностью защищает от краж /steal!"},
    "звездные_врата": {"name": "🌌 Звёздные Врата", "price": 160_000_000, "cat": "biz", "action": "business", "income": 6_500_000},
    "сфера_дайсона": {"name": "☀️ Сфера Дайсона", "price": 175_000_000, "cat": "biz", "action": "business", "income": 7_000_000},
    "квантовый_компьютер": {"name": "⚛️ Квантовый Вычислитель", "price": 190_000_000, "cat": "biz", "action": "business", "income": 7_500_000, "desc": "Генерирует профит на уровне квантовых вероятностей."},
    "варп_станция": {"name": "🌌 Варп-Станция", "price": 205_000_000, "cat": "biz", "action": "business", "income": 8_000_000, "desc": "Межпространственная торговля ресурсами."},
    "матрица_времени": {"name": "⏳ Хроно-Матрица", "price": 220_000_000, "cat": "biz", "action": "business", "income": 8_500_000, "desc": "Извлекает богатства из временных парадоксов."},
    "космо_лифт": {"name": "🏗 Орбитальный Лифт", "price": 230_000_000, "cat": "biz", "action": "business", "income": 9_000_000, "desc": "Транспортировка руды с астероидных поясов."},
    "фабрика_темной_материи": {"name": "🌌 Фабрика Тёмной Материи", "price": 240_000_000, "cat": "biz", "action": "business", "income": 9_500_000, "desc": "Производит самое дорогое вещество во вселенной."},
    "галактический_банк": {"name": "🏦 Галактический Централ", "price": 245_000_000, "cat": "biz", "action": "business", "income": 10_000_000, "desc": "Центр галактических финансов."},
    "абсолютный_абсолют": {"name": "👑 Финансовая Корпорация", "price": 250_000_000, "cat": "biz", "action": "business", "income": 12_000_000, "desc": "Вершина бизнеса до Престижа."},

    # МАШИНЫ
    "самокат":   {"name": "🛴 Электросамокат",  "price": 1_500,      "cat": "cars",  "action": "car", "income": 50},
    "велосипед": {"name": "🚲 Велосипед Аист",  "price": 3_000,      "cat": "cars",  "action": "car", "income": 100},
    "ока":       {"name": "🚗 Ока",             "price": 5_000,      "cat": "cars",  "action": "car", "income": 180},
    "жигули":    {"name": "🚗 ВАЗ-2106",        "price": 8_000,      "cat": "cars",  "action": "car", "income": 300},
    "москвич":   {"name": "🚗 Москвич-412",     "price": 10_000,     "cat": "cars",  "action": "car", "income": 400},
    "лада":      {"name": "🚗 Lada Priora",     "price": 12_500,     "cat": "cars",  "action": "car", "income": 500},
    "камри":     {"name": "🚙 Toyota Camry",    "price": 37_500,     "cat": "cars",  "action": "car", "income": 1_750},
    "бмв":       {"name": "🚕 BMW M5",          "price": 125_000,    "cat": "cars",  "action": "car", "income": 5_000},
    "гелик":     {"name": "⬛️ Geländewagen",    "price": 300_000,    "cat": "cars",  "action": "car", "income": 12_500},
    "бугатти":   {"name": "🏎 Bugatti Chiron",  "price": 1_250_000,  "cat": "cars",  "action": "car", "income": 50_000},
    "самолет":   {"name": "🛩 Частный Jet",     "price": 12_500_000, "cat": "cars",  "action": "car", "income": 350_000},
    "яхта":      {"name": "🚢 Суперъяхта",       "price": 30_000_000, "cat": "cars",  "action": "car", "income": 800_000},
    "круизер":   {"name": "🛳 Лайнер",           "price": 50_000_000, "cat": "cars",  "action": "car", "income": 1_300_000},
    "ракета":    {"name": "🚀 Ракета Falcon 9",  "price": 75_000_000, "cat": "cars",  "action": "car", "income": 1_800_000},
    "kovcheg":   {"name": "🌌 Ковчег",          "price": 100_000_000,"cat": "cars",  "action": "car", "income": 2_500_000, "desc": "Дает +20% к ежедневному бонусу!"},
    "гиперкар_аполлон": {"name": "🏎 Hypercar Apollo Intensa", "price": 120_000_000, "cat": "cars", "action": "car", "income": 3_000_000, "desc": "Ультра-редкий болид из углеволокна."},
    "грави_яхта": {"name": "🛸 Антигравитационная Яхта", "price": 140_000_000, "cat": "cars", "action": "car", "income": 3_500_000, "desc": "Парит над планетами на квантовой подушке."},
    "планетарный_дредноут": {"name": "⚛️ Планетарный Дредноут", "price": 160_000_000, "cat": "cars", "action": "car", "income": 4_000_000, "desc": "Пробивает астероидные поля и космический мусор."},
    "титан_крейсер": {"name": "🛸 Звёздный Дредноут «Титан»", "price": 180_000_000, "cat": "cars", "action": "car", "income": 4_500_000, "desc": "Флагманский корабль космического флота."},
    "гипер_гиперион": {"name": "🌌 Флагман «Гиперион»", "price": 200_000_000, "cat": "cars", "action": "car", "income": 5_000_000, "desc": "Колоссальный флагман с варп-двигателем."},
    "орбитальная_цитадель": {"name": "🏰 Орбитальная Цитадель", "price": 220_000_000, "cat": "cars", "action": "car", "income": 5_500_000, "desc": "Мобильная космическая крепость высшего класса."},
    "ковчег_миров": {"name": "🛸 Ковчег Вселенных", "price": 250_000_000, "cat": "cars", "action": "car", "income": 6_000_000, "desc": "Переносит целый мир между измерениями."},

    # 🌟 ТОВАРЫ МАГАЗИНА ПРЕСТИЖА
    "prestige_mine":        {"name": "⚡️ Квантовый Майнер", "price": 5_000_000, "cat": "prestige", "action": "business", "income": 150_000, "req_prestige": 1, "desc": "Бизнес Престижа I. Автоматический криптомайнинг."},
    "prestige_kopter":      {"name": "🚁 Дрон-Глайдер Престижа", "price": 2_500_000, "cat": "prestige", "action": "car", "income": 60_000, "req_prestige": 1, "desc": "Транспорт Престижа I. Скоростной глайдер."},
    "prestige_factory":     {"name": "🤖 Завод Нанороботов", "price": 25_000_000, "cat": "prestige", "action": "business", "income": 500_000, "req_prestige": 2, "desc": "Бизнес Престижа II. Автоматизированное нанопроизводство."},
    "prestige_hypercar":    {"name": "🏎 Плазменный Гиперкар", "price": 15_000_000, "cat": "prestige", "action": "car", "income": 250_000, "req_prestige": 2, "desc": "Транспорт Престижа II. Разгон до околосветовой скорости."},
    "prestige_tower":       {"name": "🏙 Башня Синдиката", "price": 100_000_000, "cat": "prestige", "action": "business", "income": 1_500_000, "req_prestige": 3, "desc": "Бизнес Престижа III. Международный финансовый хаб."},
    "prestige_yacht":       {"name": "🛥 Квантовая Суперъяхта", "price": 50_000_000, "cat": "prestige", "action": "car", "income": 700_000, "req_prestige": 3, "desc": "Транспорт Престижа III. Роскошный корабль с силовым полем."},
    "prestige_station":     {"name": "🪐 Орбитальная База", "price": 500_000_000, "cat": "prestige", "action": "business", "income": 5_000_000, "req_prestige": 4, "desc": "Бизнес Престижа IV. Добыча редких минералов."},
    "prestige_shuttle":     {"name": "🚀 Варп-Шаттл Hyperion", "price": 250_000_000, "cat": "prestige", "action": "car", "income": 2_500_000, "req_prestige": 4, "desc": "Транспорт Престижа IV. Межпланетный флагман."},
    "prestige_reactor":     {"name": "🌌 Звёздный Реактор", "price": 2_500_000_000, "cat": "prestige", "action": "business", "income": 18_000_000, "req_prestige": 5, "desc": "Бизнес Престижа V. Питается энергией сверхновых."},
    "prestige_dreadnought": {"name": "🛸 Гравитационный Дредноут", "price": 1_200_000_000, "cat": "prestige", "action": "car", "income": 9_000_000, "req_prestige": 5, "desc": "Транспорт Престижа V. Неуязвимый крейсер флота."},
    "prestige_monolith":    {"name": "👑 Вселенский Монолит", "price": 10_000_000_000, "cat": "prestige", "action": "business", "income": 50_000_000, "req_prestige": 6, "desc": "Вершина могущества Престижа VI. 50M сыр./ч."},
    "prestige_ark":         {"name": "🌌 Ковчег Вечности", "price": 5_000_000_000, "cat": "prestige", "action": "car", "income": 25_000_000, "req_prestige": 6, "desc": "Флагман Абсолюта Престижа VI. Межпространственный корабль."},

    # ПРОЧЕЕ
    "вип":       {"name": "💎 Статус VIP",      "price": 1_000_000, "cat": "other", "action": "other"},
    "condom":    {"name": "🎈 Презерватив",     "price": 340,       "cat": "other", "action": "other"},
    "lockpick":  {"name": "🗝 Отмычка",          "price": 15_000,    "cat": "other", "action": "other", "desc": "Увеличивает шанс кражи на +15% (одноразовая)."},
    "mask":      {"name": "🎭 Маска вора",       "price": 25_000,    "cat": "other", "action": "other", "desc": "Снижает штраф при неудачной краже (одноразовая)."},
    "medkit":    {"name": "💊 Аптечка",          "price": 10_000,    "cat": "other", "action": "other", "desc": "Полностью вылечивает все ЗППП. Использовать: /heal"},

    # ДИКТОРЫ ТАЙНИЙ БАНИЙ (СЕЗОН 3) - 70 РАНГОВ РЕДКОСТИ (ВСЕ ЦЕНЫ СБРОШЕНЫ В 0)
    "dictor_common":            {"name": "обычный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Обычный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_simple":            {"name": "простой диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Простой диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_basic":             {"name": "базовый диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Базовый диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_uncommon":          {"name": "необычный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Необычный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_rare":              {"name": "редкий диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Редкий диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_epic":              {"name": "эпический диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Эпический диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_legendary":         {"name": "легендарный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Легендарный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_mythic":            {"name": "мифический диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Мифический диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_cosmic":            {"name": "космический диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Космический диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_divine":            {"name": "божественный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Божественный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_shadow":            {"name": "теневой диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Теневой диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_abyss":             {"name": "диктор бездны тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Диктор бездны тайний баний (черный кролик 🖤🐇)."},
    "dictor_elder":             {"name": "древний диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Древний диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_chaos":             {"name": "диктор хаоса тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Диктор хаоса тайний баний (черный кролик 🖤🐇)."},
    "dictor_void":              {"name": "диктор пустоты тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Диктор пустоты тайний баний (черный кролик 🖤🐇)."},
    "dictor_infinity":          {"name": "бесконечный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Бесконечный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_secret":            {"name": "секретный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Секретный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_emperor":           {"name": "императорский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Императорский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_ghost":             {"name": "призрачный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Призрачный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_immortal":          {"name": "бессмертный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Бессмертный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_celestial":         {"name": "небесный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Небесный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_astral":            {"name": "астральный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Астральный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_quantum":           {"name": "квантовый диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Квантовый диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_singularity":       {"name": "сингулярный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Сингулярный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_supernova":         {"name": "сверхновый диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Сверхновый диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_nebula":            {"name": "туманный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Туманный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_hyperion":          {"name": "гиперионский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Гиперионский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_chronos":           {"name": "хронос-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Хронос-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_aether":            {"name": "эфирный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Эфирный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_primordial":        {"name": "первозданный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Первозданный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_supreme":           {"name": "верховный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Верховный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_archon":            {"name": "архонтский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Архонтский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_seraph":            {"name": "серафимский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Серафимский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_leviathan":         {"name": "левиафанский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Левиафанский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_phoenix":           {"name": "феникс-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Феникс-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_titan":             {"name": "титанический диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Титанический диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_valkyrie":          {"name": "валькирийский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Валькирийский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_overlord":          {"name": "владыка-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Владыка-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_omega":             {"name": "омега-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Омега-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_alpha":             {"name": "альфа-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Альфа-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_multiverse":        {"name": "мультивселенский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Мультивселенский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_transcendent":      {"name": "трансцендентный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Трансцендентный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_omnipotent":        {"name": "всемогущий диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Всемогущий диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_absolute":          {"name": "абсолютный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Абсолютный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_infinity_plus":     {"name": "сверхбесконечный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Сверхбесконечный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_dark_matter":       {"name": "тёмноматериальный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Тёмноматериальный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_dark_energy":       {"name": "тёмноэнергетический диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Тёмноэнергетический диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_antimatter":        {"name": "антиматериальный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Антиматериальный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_hyperdimensional":  {"name": "гиперпространственный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Гиперпространственный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_zenith":             {"name": "зенитный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Зенитный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_apex":               {"name": "апекс-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Апекс-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_genesis":            {"name": "генезис-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Генезис-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_apocalypse":         {"name": "апокалиптический диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Апокалиптический диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_ragnarok":           {"name": "рагнарёк-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Рагнарёк-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_valhalla":           {"name": "вальхалла-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Вальхалла-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_olympus":            {"name": "олимпский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Олимпский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_asgard":             {"name": "асгардский диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Асгардский диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_eldritch":           {"name": "иномировой диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Иномировой диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_cthulhu":            {"name": "ктулхический диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Ктулхический диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_solaris":            {"name": "солярис-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Солярис-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_lunar":              {"name": "лунный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Лунный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_eclipse":            {"name": "затменный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Затменный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_supernatural":       {"name": "сверхестественный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Сверхестественный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_boundless":          {"name": "безграничный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Безграничный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_eternity":           {"name": "вечность-диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Вечность-диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_creation":           {"name": "созидательный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Созидательный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_destruction":        {"name": "разрушительный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Разрушительный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_sovereign":          {"name": "суверенный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Суверенный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_godlike":            {"name": "богоподобный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Богоподобный диктор тайний баний (черный кролик 🖤🐇)."},
    "dictor_antigravity":        {"name": "антигравитационный диктор тайний баний", "price": 0, "cat": "tayniy_baniy", "action": "other", "desc": "Антигравитационный диктор тайний баний (черный кролик 🖤🐇)."},
}

CATEGORY_NAMES = {"biz": "Бизнесы", "cars": "Машины", "other": "Разное", "prestige": "🌟 Престиж"}
CONFIRM_THRESHOLD = 1_000_000  # цена, выше которой требуется подтверждение
SELL_RATIO = 0.75
CACHE_TTL = 60

# ─────────────────────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ
# ─────────────────────────────────────────────────────────────
class _ShopKbCache:
    """Потокобезопасный кэш сезонных строк клавиатуры."""
    __slots__ = ("biz", "cars", "ts", "_lock")

    def __init__(self):
        self.biz = "🏢 Бизнесы"
        self.cars = "🚗 Машины"
        self.ts = 0.0
        self._lock = asyncio.Lock()

    async def refresh_if_needed(self):
        if time.time() - self.ts <= CACHE_TTL:
            return
        async with self._lock:
            if time.time() - self.ts <= CACHE_TTL:  # double-check
                return
            self.biz = await get_season_string("shop_biz", "🏢 Бизнесы")
            self.cars = await get_season_string("shop_cars", "🚗 Машины")
            self.ts = time.time()


_shop_kb_cache = _ShopKbCache()


def _has_overdue_debt(debts: Optional[dict]) -> bool:
    """Проверяет, есть ли у пользователя просроченные банковские долги."""
    if not debts:
        return False
    now = time.time()
    for key, value in debts.items():
        if not (isinstance(key, str) and key.startswith("bank_")):
            continue
        try:
            if float(value) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        parts = key.split("_")
        if len(parts) < 3:
            continue
        try:
            due_date = int(parts[2])
        except (TypeError, ValueError):
            continue
        if now > due_date:
            return True
    return False


def _get_pet_id(data: dict) -> Optional[str]:
    pet = data.get("pet")
    if isinstance(pet, dict):
        return pet.get("id")
    return None


def _calc_user_tax(data: dict, base_tax: float) -> float:
    """Единая точка расчёта налога — гарантирует одинаковые цены везде."""
    return calculate_progressive_tax(
        data.get("balance", 0),
        base_tax,
        data.get("skills", {}).get("negotiation", 0),
        _get_pet_id(data),
    )


def _calc_final_price(item: dict, balance: int, tax_rate: float) -> int:
    """Итоговая цена покупки с учётом налога и наценки на роскошь для бизнесов."""
    price = Decimal(item["price"])
    tax_dec = Decimal(str(tax_rate))
    markup = price * (tax_dec / Decimal('100'))
    if item.get("cat") == "biz":
        biz_markup_percent = calculate_biz_markup(balance)
        biz_dec = Decimal(str(biz_markup_percent))
        markup += price * (biz_dec / Decimal('100'))
    return int(price + markup)


async def _safe_edit(message: types.Message, text: str, reply_markup=None):
    """edit_text без падений при отсутствии изменений / устаревшем сообщении / флуде."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramRetryAfter as e:
        logger.warning("Flood limit exceeded in shop, sleeping for %ss", e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except Exception as ex:
            logger.debug("Retry edit_text failed: %s", ex)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        logger.debug("edit_text failed: %s", e)
    except Exception as e:
        logger.debug("edit_text failed with exception: %s", e)


# ─────────────────────────────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────
async def get_main_shop_kb(prestige_level: int = 0):
    await _shop_kb_cache.refresh_if_needed()
    builder = InlineKeyboardBuilder()
    builder.button(text=_shop_kb_cache.biz, callback_data="shop_cat_biz")
    builder.button(text=_shop_kb_cache.cars, callback_data="shop_cat_cars")
    builder.button(text="💎 Прочее", callback_data="shop_cat_other")
    if prestige_level >= 1:
        builder.button(text="🌟 Магазин Престижа", callback_data="shop_cat_prestige")
    builder.button(text="🎒 Мой инвентарь", callback_data="shop_to_inv")
    builder.adjust(2, 2 if prestige_level < 1 else 3)
    return builder.as_markup()


def get_sell_menu_kb(inventory: dict, is_vip: bool):
    builder = InlineKeyboardBuilder()
    has_items = False

    for item_id, count in (inventory or {}).items():
        if item_id == "вип":          # VIP обрабатывается отдельно
            continue
        if item_id not in ITEMS:
            continue
        try:
            cnt = int(count)
        except (TypeError, ValueError):
            continue
        if cnt <= 0:
            continue

        info = ITEMS[item_id]
        sell_price = int(info["price"] * SELL_RATIO)
        qty_str = f" ({cnt} шт)" if cnt > 1 else ""
        builder.button(
            text=f"Продать: {info['name']}{qty_str} — {sell_price} сыр.",
            callback_data=f"sell_ask_{item_id}",
        )
        has_items = True

    if is_vip:
        info = ITEMS["вип"]
        sell_price = int(info["price"] * SELL_RATIO)
        builder.button(
            text=f"Продать: {info['name']} — {sell_price} сыр.",
            callback_data="sell_ask_вип",
        )
        has_items = True

    builder.button(text="⬅️ Назад", callback_data="shop_main")
    builder.adjust(1)
    return builder.as_markup(), has_items


def get_sell_confirm_kb(item_id: str, owned_qty: int = 1, base_price: int = 0, upgrade_refund: int = 0):
    builder = InlineKeyboardBuilder()
    if item_id == "вип" or owned_qty <= 1:
        total_payout = base_price + upgrade_refund
        builder.button(text=f"✅ Да, продать ({total_payout} сыр.)", callback_data=f"sell_confirm_{item_id}_1")
    else:
        builder.button(text=f"1 шт. ({base_price} сыр.)", callback_data=f"sell_confirm_{item_id}_1")
        if owned_qty >= 5:
            payout_5 = (base_price * 5) + (upgrade_refund if owned_qty == 5 else 0)
            builder.button(text=f"5 шт. ({payout_5} сыр.)", callback_data=f"sell_confirm_{item_id}_5")
        payout_all = (base_price * owned_qty) + upgrade_refund
        builder.button(text=f"Все ({owned_qty} шт. = {payout_all} сыр.)", callback_data=f"sell_confirm_{item_id}_all")

    builder.button(text="❌ Отмена", callback_data="shop_sell_menu")
    builder.adjust(1) if owned_qty <= 1 else builder.adjust(2)
    return builder.as_markup()


def get_category_kb(category: str, data: dict, base_tax: float, page: int = 0):
    builder = InlineKeyboardBuilder()
    tax_rate = _calc_user_tax(data, base_tax)
    balance = data.get("balance", 0)

    cat_items = [(item_id, info) for item_id, info in ITEMS.items() if info.get("cat") == category]
    per_page = 5
    total_pages = max(1, (len(cat_items) + per_page - 1) // per_page)
    
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1

    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_items = cat_items[start_idx:end_idx]

    for item_id, info in page_items:
        final_price = _calc_final_price(info, balance, tax_rate)
        builder.button(
            text=f"{info['name']} — {final_price} сыр.",
            callback_data=f"buy_{item_id}_{page}",
        )
    builder.adjust(1)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"shop_cat_{category}_{page-1}"))
    if total_pages > 1:
        nav_buttons.append(types.InlineKeyboardButton(text=f"[ {page+1} / {total_pages} ]", callback_data="none"))
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton(text="След. ➡️", callback_data=f"shop_cat_{category}_{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="shop_main"))
    return builder.as_markup()


# ─────────────────────────────────────────────────────────────
#  РЕНДЕРИНГ ЭКРАНОВ (переиспользуется из разных хендлеров)
# ─────────────────────────────────────────────────────────────
async def _render_main_shop(message: types.Message, data: dict, *, as_new: bool = False):
    base_tax = await get_global_tax()
    tax_rate = _calc_user_tax(data, base_tax)

    debts_warning = ""
    if _has_overdue_debt(data.get("debts")):
        debts_warning = (
            "\n\n⚠️ <b>ВНИМАНИЕ: На вас наложен арест за просроченный долг! "
            "Вы не можете покупать новые вещи, но можете продать старые "
            "для погашения долга.</b>"
        )

    shop_title = await get_season_string("shop", "🛒 Магазин Сыроежек")
    shop_title = await get_glitch_text(shop_title)

    text = (
        f"<b>{shop_title}</b>\n\n"
        f"Твой баланс: <b>{data.get('balance', 0)}</b> сыр.\n"
        f"📈 Твоя наценка (Налог на роскошь): <b>{tax_rate}%</b>{debts_warning}\n"
        "Выберите категорию товаров:"
    )
    prestige_level = int(data.get("prestige_level", 0) or 0)
    kb = await get_main_shop_kb(prestige_level=prestige_level)
    if as_new:
        await message.answer(text, reply_markup=kb)
    else:
        await _safe_edit(message, text, reply_markup=kb)


async def _render_category(message: types.Message, data: dict, category: str, page: int = 0):
    base_tax = await get_global_tax()
    cat_name = CATEGORY_NAMES.get(category, "?")
    text = (
        f"📂 <b>Категория: {cat_name}</b>\n\n"
        "Выбери товар для покупки (цены указаны с учётом твоего налога):"
    )
    await _safe_edit(message, text, reply_markup=get_category_kb(category, data, base_tax, page=page))


async def _render_sell_menu(message: types.Message, data: dict):
    inventory = data.get("inventory") or {}
    is_vip = bool(data.get("is_vip"))
    kb, has_items = get_sell_menu_kb(inventory, is_vip)
    if not has_items:
        text = "🤷‍♂️ У вас нет имущества для продажи."
    else:
        text = (
            "💰 <b>ПРОДАЖА ИМУЩЕСТВА</b>\n\n"
            f"Выбери предмет, который хочешь продать "
            f"(ты получишь {int(SELL_RATIO * 100)}% от стоимости):"
        )
    await _safe_edit(message, text, reply_markup=kb)


# ─────────────────────────────────────────────────────────────
#  ХЕНДЛЕРЫ
# ─────────────────────────────────────────────────────────────
@router.message(Command("shop"))
async def cmd_shop(message: types.Message):
    data = await get_user_data(message.chat.id, message.from_user.id)
    if data.get("is_banned"):
        return

    active_diseases = await get_active_diseases(message.chat.id, message.from_user.id)
    if "ureaplasmosis" in active_diseases:
        return await message.answer(
            "🦠 <b>Уреаплазмоз</b>: Продавцы боятся заразиться и не пускают вас в магазин!"
        )

    await _render_main_shop(message, data, as_new=True)


@router.callback_query(F.data == "shop_main")
async def shop_back(callback: types.CallbackQuery):
    await callback.answer()
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    await _render_main_shop(callback.message, data)


@router.callback_query(F.data == "shop_to_inv")
async def shop_to_inv(callback: types.CallbackQuery):
    await callback.answer(
        "🎒 Для управления имуществом, продажи и улучшения бизнесов введи команду /inv !",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("shop_cat_"))
async def show_category(callback: types.CallbackQuery):
    await callback.answer()
    raw_data = callback.data.removeprefix("shop_cat_")
    if "_" in raw_data:
        category, page_str = raw_data.rsplit("_", 1)
        try:
            page = int(page_str)
        except ValueError:
            category = raw_data
            page = 0
    else:
        category = raw_data
        page = 0

    if category not in CATEGORY_NAMES:
        return
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    await _render_category(callback.message, data, category, page=page)


# Обработчик подтверждения покупки: ставим раньше общего, чтобы parse был чистый
@router.callback_query(F.data.startswith("buy_conf_"))
async def process_buy_confirmed(callback: types.CallbackQuery):
    raw_data = callback.data.removeprefix("buy_conf_")
    if "_" in raw_data:
        item_id, page_str = raw_data.rsplit("_", 1)
        try:
            page = int(page_str)
        except ValueError:
            item_id = raw_data
            page = 0
    else:
        item_id = raw_data
        page = 0
    await _process_buy(callback, item_id=item_id, page=page, confirmed=True)


@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    # buy_conf_ уже обработан выше, а здесь оставшиеся "buy_xxx"
    if callback.data.startswith("buy_conf_"):
        return
    raw_data = callback.data.removeprefix("buy_")
    if "_" in raw_data:
        item_id, page_str = raw_data.rsplit("_", 1)
        try:
            page = int(page_str)
        except ValueError:
            item_id = raw_data
            page = 0
    else:
        item_id = raw_data
        page = 0
    await _process_buy(callback, item_id=item_id, page=page, confirmed=False)


async def _process_buy(callback: types.CallbackQuery, item_id: str, page: int, confirmed: bool):
    item = ITEMS.get(item_id)
    if not item:
        return await callback.answer("Товар не найден.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    data = await get_user_data(chat_id, user_id)

    if data.get("is_banned"):
        return await callback.answer("Вы забанены.", show_alert=True)

    if _has_overdue_debt(data.get("debts")):
        return await callback.answer(
            "❌ У вас просроченный долг! Покупки запрещены.", show_alert=True
        )

    req_prestige = item.get("req_prestige", 0)
    user_prestige = int(data.get("prestige_level", 0) or 0)
    if req_prestige > user_prestige:
        return await callback.answer(
            f"❌ Этот товар доступен только с Престижа {req_prestige}!",
            show_alert=True,
        )

    base_tax = await get_global_tax()
    tax_rate = _calc_user_tax(data, base_tax)
    balance = data.get("balance", 0)
    final_price = _calc_final_price(item, balance, tax_rate)

    if balance < final_price:
        return await callback.answer(
            f"Недостаточно денег! Твоя цена: {final_price} сыр.", show_alert=True
        )

    # Лимит и дубликаты для бизнесов/машин/престижа — предварительная проверка (финальная — в транзакции)
    inv = data.get("inventory") or {}
    if item.get("cat") in ("biz", "cars", "prestige"):
        if inv.get(item_id, 0) >= 5:
            return await callback.answer("Ты не можешь иметь больше 5 штук одного товара!", show_alert=True)

    if item.get("cat") == "biz":
        limit = 9 if data.get("is_vip") else 7
        biz_count = sum(int(c) for k, c in inv.items() if ITEMS.get(k, {}).get("cat") == "biz")
        if biz_count >= limit:
            return await callback.answer(
                f"Лимит бизнесов ({limit}) достигнут!", show_alert=True
            )

    if item.get("cat") == "cars":
        limit = 9 if data.get("is_vip") else 7
        car_count = sum(int(c) for k, c in inv.items() if ITEMS.get(k, {}).get("cat") == "cars")
        if car_count >= limit:
            return await callback.answer(
                f"Лимит машин ({limit}) достигнут!", show_alert=True
            )

    # Подтверждение для дорогих покупок
    if final_price > CONFIRM_THRESHOLD and not confirmed:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, купить", callback_data=f"buy_conf_{item_id}_{page}")
        builder.button(
            text="❌ Отмена",
            callback_data=f"shop_cat_{item.get('cat', 'other')}_{page}",
        )
        builder.adjust(1)
        await callback.answer()
        return await _safe_edit(
            callback.message,
            f"❓ Вы уверены, что хотите купить <b>{item['name']}</b> "
            f"за <b>{final_price}</b> сыр.?",
            reply_markup=builder.as_markup(),
        )

    # ─── Транзакция покупки ───
    db = get_db()

    @firestore_async.async_transactional
    async def _buy_txn(transaction):
        return await buy_item_tr(
            transaction, chat_id, user_id, item_id, final_price, item_id == "вип"
        )

    try:
        from user_manager import get_user_lock, invalidate_user_cache
        lock = get_user_lock(chat_id, user_id)
        async with lock:
            success, error_msg = await _buy_txn(db.transaction())
            if success:
                invalidate_user_cache(chat_id, user_id)
    except Exception:
        logger.exception("Buy transaction failed (user=%s item=%s)", user_id, item_id)
        return await callback.answer("Ошибка при покупке. Попробуйте ещё раз.", show_alert=True)

    if not success:
        return await callback.answer(f"Ошибка: {error_msg}", show_alert=True)

    await callback.answer(f"Куплено: {item['name']}!", show_alert=True)

    # Обновляем экран категории актуальными данными
    fresh = await get_user_data(chat_id, user_id)
    await _render_category(callback.message, fresh, item.get("cat", "other"), page=page)


@router.callback_query(F.data == "shop_sell_menu")
async def show_sell_menu(callback: types.CallbackQuery):
    await callback.answer()
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    await _render_sell_menu(callback.message, data)


@router.callback_query(F.data.startswith("sell_ask_"))
async def ask_sell_confirm(callback: types.CallbackQuery):
    await callback.answer()
    item_id = callback.data.removeprefix("sell_ask_")
    item = ITEMS.get(item_id)
    if not item:
        return

    # Доп. проверка владения
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    if item_id == "вип":
        if not data.get("is_vip"):
            return await callback.answer("У вас нет VIP-статуса.", show_alert=True)
        owned_qty = 1
        base_sell_price = int(item["price"] * SELL_RATIO)
        upgrade_refund = 0
    else:
        inv = data.get("inventory") or {}
        owned_qty = int(inv.get(item_id, 0) or 0)
        if owned_qty <= 0:
            return await callback.answer("У вас нет этого предмета.", show_alert=True)

        base_sell_price = int(item["price"] * SELL_RATIO)
        upgrade_refund = 0
        if item.get("action") == "business":
            biz_levels = data.get("biz_levels", {})
            level = biz_levels.get(item_id, 1)
            upgrade_invested = sum(int(item["price"] * 0.5 * l) for l in range(1, level))
            upgrade_refund = int(upgrade_invested * SELL_RATIO)

    upgrade_note = f"\n<i>(Включает возврат за улучшения при продаже всех шт.: {upgrade_refund} сыр.)</i>" if upgrade_refund > 0 else ""
    if owned_qty <= 1:
        text = (
            f"❓ Вы уверены, что хотите продать <b>{item['name']}</b> "
            f"за <b>{base_sell_price + upgrade_refund}</b> сыр.?{upgrade_note}"
        )
    else:
        text = (
            f"💰 <b>Продажа имущества:</b> {item['name']}\n"
            f"У вас в наличии: <b>{owned_qty} шт.</b>\n"
            f"Базовая цена продажи: <b>{base_sell_price}</b> сыр./шт.{upgrade_note}\n\n"
            f"Выберите количество для продажи:"
        )

    await _safe_edit(
        callback.message,
        text,
        reply_markup=get_sell_confirm_kb(
            item_id, owned_qty=owned_qty, base_price=base_sell_price, upgrade_refund=upgrade_refund
        )
    )


@router.callback_query(F.data.startswith("sell_confirm_"))
async def process_sell_confirm(callback: types.CallbackQuery):
    raw_data = callback.data.removeprefix("sell_confirm_")
    parts = raw_data.rsplit("_", 1)
    if len(parts) == 2 and (parts[1].isdigit() or parts[1] == "all"):
        item_id = parts[0]
        req_count_str = parts[1]
    else:
        item_id = raw_data
        req_count_str = "1"

    item = ITEMS.get(item_id)
    if not item:
        return await callback.answer("Товар не найден.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    db = get_db()

    from user_manager import get_user_lock, invalidate_user_cache
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        if item_id == "вип":
            sell_price = int(item["price"] * SELL_RATIO)
            @firestore_async.async_transactional
            async def _sell_vip_txn(transaction):
                return await sell_vip_tr(transaction, chat_id, user_id, sell_price)

            try:
                success = await _sell_vip_txn(db.transaction())
            except Exception:
                logger.exception("Sell VIP transaction failed (user=%s)", user_id)
                return await callback.answer(
                    "Произошла ошибка при продаже VIP. Попробуйте ещё раз.", show_alert=True
                )

            if not success:
                return await callback.answer("У вас больше нет VIP статуса!", show_alert=True)
            sold_count = 1
            total_payout = sell_price

        else:
            item_cat = item.get("cat", "")
            u_data = await get_user_data(chat_id, user_id)
            inv = u_data.get("inventory") or {}
            owned_qty = int(inv.get(item_id, 0) or 0)
            if owned_qty <= 0:
                return await callback.answer("Предмет не найден в вашем инвентаре!", show_alert=True)

            if req_count_str == "all":
                sell_count = owned_qty
            else:
                try:
                    sell_count = int(req_count_str)
                except ValueError:
                    sell_count = 1
            sell_count = min(sell_count, owned_qty)
            if sell_count <= 0:
                return await callback.answer("Некорректное количество для продажи.", show_alert=True)

            base_unit_price = int(item["price"] * SELL_RATIO)
            upgrade_refund = 0
            if item.get("action") == "business":
                biz_levels = u_data.get("biz_levels", {})
                level = biz_levels.get(item_id, 1)
                upgrade_invested = sum(int(item["price"] * 0.5 * l) for l in range(1, level))
                if sell_count >= owned_qty:
                    upgrade_refund = int(upgrade_invested * SELL_RATIO)

            total_payout = (base_unit_price * sell_count) + upgrade_refund
            sold_count = sell_count

            @firestore_async.async_transactional
            async def _sell_txn(transaction):
                return await sell_item_tr(
                    transaction, chat_id, user_id, item_id, item_cat, base_unit_price, count=sell_count, total_payout=total_payout
                )

            try:
                success = await _sell_txn(db.transaction())
            except Exception:
                logger.exception("Sell transaction failed (user=%s item=%s)", user_id, item_id)
                return await callback.answer(
                    "Произошла ошибка при продаже предмета. Попробуйте ещё раз.",
                    show_alert=True,
                )

            if not success:
                return await callback.answer(
                    "Предмет не найден в вашем инвентаре!", show_alert=True
                )

        invalidate_user_cache(chat_id, user_id)

    await callback.answer(f"✅ Успешно продано {sold_count} шт. за {total_payout} сыр.!", show_alert=True)

    # Обновляем меню продажи свежими данными
    fresh = await get_user_data(chat_id, user_id)
    await _render_sell_menu(callback.message, fresh)