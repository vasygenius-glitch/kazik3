import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
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
