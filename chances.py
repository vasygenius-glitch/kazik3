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

    # Apply Season Win Chance Boost (Warhammer +15%, Summer, etc.)
    try:
        from seasons import get_season_config
        cfg = await get_season_config()
        if cfg and cfg.get("active"):
            boost = cfg.get("game_win_chance_boost", 0)
            if not boost and cfg.get("id") == "warhammer":
                boost = 15
            elif not boost and cfg.get("id") == "summer":
                from config import SUMMER_COURAGE_ENABLED, SUMMER_WIN_CHANCE_BOOST
                if SUMMER_COURAGE_ENABLED:
                    boost = SUMMER_WIN_CHANCE_BOOST
            if boost > 0:
                base_chance = 35 if chance == -1 else chance
                return min(100, base_chance + boost)
    except Exception:
        pass

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
            from prestige import get_prestige_perks
            
            data = await get_user_data(chat_id, user_id)
            if data:
                luck_bonus = get_prestige_perks(data).get("luck_bonus", 0)
                pet = data.get('pet') or {}
                pet_id = pet.get('id') if isinstance(pet, dict) else None
                has_unicorn = False
                if pet_id == 'unicorn':
                    active_diseases = await get_active_diseases(chat_id, user_id, data)
                    if 'hpv' not in active_diseases:
                        has_unicorn = True
                
                if has_unicorn or luck_bonus > 0:
                    base_rate = 55 if has_unicorn else 45
                    return min(100, base_rate + luck_bonus)
        except Exception:
            pass
        return -1

    try:
        from user_manager import get_user_data
        from diseases import get_active_diseases
        from prestige import get_prestige_perks
        
        data = await get_user_data(chat_id, user_id)
        if data:
            pet = data.get('pet') or {}
            pet_id = pet.get('id') if isinstance(pet, dict) else None
            if pet_id == 'unicorn':
                active_diseases = await get_active_diseases(chat_id, user_id, data)
                if 'hpv' not in active_diseases:
                    target_chance += 10
            
            luck_bonus = get_prestige_perks(data).get("luck_bonus", 0)
            if luck_bonus > 0:
                target_chance += luck_bonus
    except Exception:
        pass
    
    return max(0, min(target_chance, 100))

