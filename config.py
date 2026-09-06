import os
from dotenv import load_dotenv

load_dotenv()

_raw_token = os.getenv("BOT_TOKEN", "")
BOT_TOKEN = _raw_token.strip().strip('"').strip("'") if _raw_token else ""
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "firebase-key.json")
CREATOR_USERNAME = os.getenv("CREATOR_USERNAME", "z_1l1")
try:
    CREATOR_ID = int(os.getenv("CREATOR_ID", "5416583030"))
except ValueError:
    CREATOR_ID = 5416583030

CREATOR_IDS = {CREATOR_ID}

DISABLE_WHITELIST = os.getenv("DISABLE_WHITELIST", "False").lower() == "true"

# --- ЛЕТНИЙ СЕЗОН (Summer Season) ---
SUMMER_COURAGE_ENABLED = os.getenv("SUMMER_COURAGE_ENABLED", "True").lower() == "true"
SUMMER_WIN_CHANCE_BOOST = int(os.getenv("SUMMER_WIN_CHANCE_BOOST", "15"))
SUMMER_DEPOSIT_BOOST = float(os.getenv("SUMMER_DEPOSIT_BOOST", "0.20"))

# --- СЕТЕВЫЕ НАСТРОЙКИ (Network & Timeouts) ---
API_TIMEOUT_SECONDS = int(os.getenv("API_TIMEOUT_SECONDS", "30"))
API_CONNECT_TIMEOUT_SECONDS = int(os.getenv("API_CONNECT_TIMEOUT_SECONDS", "12"))
API_RETRY_DELAY_SECONDS = float(os.getenv("API_RETRY_DELAY_SECONDS", "1.5"))

# --- PVP ДУЭЛИ (PvP Duels) ---
DUEL_TIMEOUT_SECONDS = int(os.getenv("DUEL_TIMEOUT_SECONDS", "60"))
DUEL_TAX_PERCENT = float(os.getenv("DUEL_TAX_PERCENT", "0.02"))  # 2% в джекпот чата
MIN_DUEL_BET = int(os.getenv("MIN_DUEL_BET", "50"))

# --- BATTLE PASS & DAILY QUESTS ---
BATTLE_PASS_SEASON_DAYS = int(os.getenv("BATTLE_PASS_SEASON_DAYS", "30"))
DAILY_QUESTS_COUNT = 3
XP_PER_GAME = 5
XP_PER_WIN = 10

