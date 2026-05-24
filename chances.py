from db import get_db
import time

_chances_cache = {}
_chances_cache_time = 0
CHANCES_CACHE_TTL = 300.0

async def get_game_chance(game_name: str) -> int:
    global _chances_cache, _chances_cache_time
    if time.time() - _chances_cache_time < CHANCES_CACHE_TTL:
        return _chances_cache.get(game_name, -1)

    db = get_db()
    ref = db.collection('bot_settings').document('chances')
    doc = await ref.get()

    if doc.exists:
        _chances_cache = doc.to_dict()
    else:
        _chances_cache = {}

    _chances_cache_time = time.time()
    return _chances_cache.get(game_name, -1) # -1 означает честный рандом

def get_game_chance_sync(game_name: str) -> int:
    global _chances_cache
    return _chances_cache.get(game_name, -1)

async def set_game_chance(game_name: str, percentage: int):
    global _chances_cache
    _chances_cache[game_name] = percentage

    db = get_db()
    ref = db.collection('bot_settings').document('chances')
    from utils import fire_and_forget
    fire_and_forget(ref.set({game_name: percentage}, merge=True))
