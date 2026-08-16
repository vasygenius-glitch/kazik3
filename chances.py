from db import get_db
import time

_chances_cache = {}
_chances_cache_time = 0
CHANCES_CACHE_TTL = 300.0

async def get_game_chance(game_name: str) -> int:
    global _chances_cache, _chances_cache_time
    if time.time() - _chances_cache_time < CHANCES_CACHE_TTL:
        chance = _chances_cache.get(game_name, -1)
    else:
        db = get_db()
        if db is None:
            chance = _chances_cache.get(game_name, -1)
        else:
            try:
                ref = db.collection('bot_settings').document('chances')
                doc = await ref.get()

                if doc.exists:
                    _chances_cache = doc.to_dict()
                else:
                    _chances_cache = {}

                _chances_cache_time = time.time()
                chance = _chances_cache.get(game_name, -1) # -1 означает честный рандом
            except Exception:
                chance = _chances_cache.get(game_name, -1)

    # Apply Summer Win Chance Boost
    from config import SUMMER_COURAGE_ENABLED, SUMMER_WIN_CHANCE_BOOST
    if SUMMER_COURAGE_ENABLED:
        from seasons import get_season_config
        cfg = await get_season_config()
        if cfg.get("active") and cfg.get("id") == "summer":
            base_chance = 35 if chance == -1 else chance
            return base_chance + SUMMER_WIN_CHANCE_BOOST

    return chance

def get_game_chance_sync(game_name: str) -> int:
    global _chances_cache
    return _chances_cache.get(game_name, -1)

async def set_game_chance(game_name: str, percentage: int):
    global _chances_cache
    _chances_cache[game_name] = percentage

    db = get_db()
    if db is None:
        return
    ref = db.collection('bot_settings').document('chances')
    from utils import fire_and_forget
    fire_and_forget(ref.set({game_name: percentage}, merge=True))

async def get_user_win_chance(chat_id: int, user_id: int, game_name: str, base_chance: int = 35) -> int:
    chance = await get_game_chance(game_name)
    target_chance = base_chance if chance == -1 else chance

    if target_chance == -1:
        # Честный рандом без принудительной подкрутки
        try:
            from user_manager import get_user_data
            from diseases import get_active_diseases
            
            data = await get_user_data(chat_id, user_id)
            if data:
                pet = data.get('pet') or {}
                pet_id = pet.get('id') if isinstance(pet, dict) else None
                if pet_id == 'unicorn':
                    active_diseases = await get_active_diseases(chat_id, user_id, data)
                    if 'hpv' not in active_diseases:
                        # Единорог дает +10% шанс победы (базовый 45% + 10% = 55%)
                        return 55
        except Exception:
            pass
        return -1

    try:
        from user_manager import get_user_data
        from diseases import get_active_diseases
        
        data = await get_user_data(chat_id, user_id)
        if data:
            pet = data.get('pet') or {}
            pet_id = pet.get('id') if isinstance(pet, dict) else None
            if pet_id == 'unicorn':
                active_diseases = await get_active_diseases(chat_id, user_id, data)
                if 'hpv' not in active_diseases:
                    target_chance += 10
    except Exception:
        pass
    
    return max(0, min(target_chance, 100))

