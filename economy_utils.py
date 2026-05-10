from db import get_db
import time

_tax_cache = None
_tax_cache_time = 0
TAX_CACHE_TTL = 300.0  # 5 minutes

async def get_global_tax() -> int:
    global _tax_cache, _tax_cache_time
    if _tax_cache is not None and time.time() - _tax_cache_time < TAX_CACHE_TTL:
        return _tax_cache

    db = get_db()
    doc = await db.collection('bot_settings').document('economy').get()
    if doc.exists:
        val = doc.to_dict().get('tax', 10)
    else:
        val = 10

    _tax_cache = val
    _tax_cache_time = time.time()
    return val

from utils import fire_and_forget

async def set_global_tax(tax: int):
    global _tax_cache, _tax_cache_time
    _tax_cache = tax
    _tax_cache_time = time.time()

    db = get_db()
    fire_and_forget(db.collection('bot_settings').document('economy').set({'tax': tax}, merge=True))

def calculate_progressive_tax(balance: int, base_tax: int, negotiation_skill: int = 0, pet_id: str = None) -> int:
    """
    Calculates tax rate: 
    - Base tax (usually 10%)
    - Wealth surcharge: +5% for every 1,000,000 in balance (more aggressive)
    - Pet bonus: Dog reduces tax by 5% (fixed reduction)
    - Negotiation skill: Reduces rate by skill_lvl, but cannot reduce more than 50% of the calculated tax.
    - Total tax is capped at 95% and increased by seasonal multiplier.
    """
    from seasons import get_season_config
    from utils_pkg.cache_manager import global_cache
    cfg = global_cache.get("current_season")
    
    tax_multiplier = 1.0
    if cfg and cfg.get("active") and cfg.get("id") == "backrooms":
        tax_multiplier = 1.5
    
    # Налог на богатство: +5% за каждый миллион (было 2%)
    wealth_surcharge = (balance // 1000000) * 5
    
    calculated_tax = base_tax + wealth_surcharge
    
    # Скилл переговоров: снижает налог, но не более чем на половину от начисленного
    max_reduction = calculated_tax // 2
    reduction = min(negotiation_skill, max_reduction)
    
    total_tax = calculated_tax - reduction
    
    # Бонус собачки: прямое снижение на 5% (но не ниже 1%)
    if pet_id == 'dog':
        total_tax -= 5
    
    total_tax = int(total_tax * tax_multiplier)
    
    return max(1, min(95, total_tax))
