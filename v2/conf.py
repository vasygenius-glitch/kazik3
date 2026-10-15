"""Константы V2. Все суммы — целые сыроежки."""
import os


def _int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


CURRENCY = "сыроежек"
MIN_BET = 10
MAX_BET = _int("V2_MAX_BET", 50_000_000)
SICK_MAX_BET = 1_000            # «Баланопостит»: как в старых рулетке и слотах
HOUSE_EDGE = 0.03
RTP = 1.0 - HOUSE_EDGE

# Часовой пояс игровых суток/недель (Москва), чтобы задания и лига сбрасывались в 00:00 МСК.
TZ_OFFSET = 3 * 3600

INIT_DATA_MAX_AGE = 24 * 3600   # Telegram не обновляет initData в открытой сессии
MEMBER_CACHE_TTL = 600
ONLINE_WINDOW = 45              # сек без опроса — игрок считается вышедшим

# Кешбэк: процент от оборота, ниже преимущества казино, поэтому игры остаются честными, а не «печатными станками».
RAKE_BASE = 0.004
RAKE_PER_LEVEL = 0.0002
RAKE_LEVEL_CAP = 40
RAKE_VIP = 0.003
RAKE_UNICORN = 0.003
RAKE_LUCK_POINT = 0.0003
RAKE_MAX = 0.024
# Множитель кешбэка по играм ~ преимущество казино игры / 3%.
RAKE_FACTOR = {
    "bj": 0.15, "baccarat": 0.35, "poker": 0.8, "rps": 0.6,
    "duel": 0.0, "jackpot": 0.0, "wheel": 0.0,
}

POOL_SHARE = 0.005              # доля оборота в призовой фонд недельной лиги
POOL_PRIZES = (0.5, 0.3, 0.2)
PVP_FEE = 0.03                  # комиссия складчины/дуэлей уходит в фонд лиги

WHEEL_COOLDOWN = 20 * 3600
DUEL_TTL = 120

ANNOUNCE_MIN_WIN = 25_000
ANNOUNCE_MIN_MULT = 10.0
ANNOUNCE_BIG_WIN = 1_000_000
ANNOUNCE_GAP = 90               # не чаще раза в N секунд на чат

HISTORY_LEN = 20
