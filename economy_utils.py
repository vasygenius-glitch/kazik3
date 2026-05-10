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

def calculate_progressive_tax(balance: int, base_tax: int, negotiation_skill: int = 0) -> int:
    """
    Calculates tax rate: base_tax + 2% for every 1,000,000 in balance.
    Negotiation skill reduces the rate. Cap is 90%.
    """
    wealth_surcharge = (balance // 1000000) * 2
    total_tax = base_tax + wealth_surcharge
    total_tax = max(0, total_tax - negotiation_skill)
    return min(90, total_tax)
