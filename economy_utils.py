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

def format_time_left(seconds: int) -> str:
    """Форматирует секунды в строку вида '1 час 23 минуты 1 секунда' с правильными склонениями."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    def get_word(num, word_variants):
        if num % 100 in (11, 12, 13, 14):
            return word_variants[2]
        if num % 10 == 1:
            return word_variants[0]
        if num % 10 in (2, 3, 4):
            return word_variants[1]
        return word_variants[2]

    res = []
    if hours > 0:
        res.append(f"{hours} {get_word(hours, ['час', 'часа', 'часов'])}")
    if minutes > 0:
        res.append(f"{minutes} {get_word(minutes, ['минуту', 'минуты', 'минут'])}")
    if secs > 0 or not res:
        res.append(f"{secs} {get_word(secs, ['секунду', 'секунды', 'секунд'])}")

    return " ".join(res)

def calculate_progressive_tax(balance: int, base_tax: int, negotiation_skill: int = 0, pet_id: str = None) -> int:
    """
    Calculates tax rate: 
    - Base tax (usually 10%)
    - Wealth surcharge: +5% for every 1,000,000 in balance (more aggressive)
    - Pet bonus: Dog reduces tax by 5% (fixed reduction)
    - Negotiation skill: Reduces rate by skill_lvl, but cannot reduce more than 50% of the calculated tax.
    - Total tax is capped at 20% and increased by seasonal multiplier.
    """
    # Сезонный множитель налога (используем только кэш, т.к. функция sync)
    from utils_pkg.cache_manager import global_cache
    cfg = global_cache.get("current_season")
    
    tax_multiplier = 1.0
    if cfg and isinstance(cfg, dict) and cfg.get("active") and cfg.get("id") == "backrooms":
        tax_multiplier = 1.5
    
    # Налог на богатство: +5% за каждые 250,000 (уменьшено в 4 раза вместе с нерфом экономики)
    wealth_surcharge = (balance // 250000) * 5
    
    calculated_tax = base_tax + wealth_surcharge
    
    # Скилл переговоров: снижает налог, но не более чем на половину от начисленного
    max_reduction = calculated_tax // 2
    reduction = min(negotiation_skill, max_reduction)
    
    total_tax = calculated_tax - reduction
    
    # Бонус собачки: прямое снижение на 5% (но не ниже 1%)
    if pet_id == 'dog':
        total_tax -= 5
    
    total_tax = int(total_tax * tax_multiplier)
    
    # Налог ограничен 20%
    return max(1, min(20, total_tax))

def calculate_biz_markup(balance: int) -> int:
    """
    Returns the non-stacking luxury tax markup for businesses based on the user's balance.
    If balance > 500 million, the markup is 20%.
    If balance > 100 million, the markup is 20%.
    Otherwise, the markup is 0%.
    """
    if balance > 500_000_000:
        return 20
    elif balance > 100_000_000:
        return 20
    else:
        return 0
