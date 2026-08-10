from aiogram import Dispatcher
from crypto import router as crypto_router
from stocks import router as stocks_router
from seasons import router as seasons_router
from economy import router as economy_router
from blackjack import router as blackjack_router
from rps import router as rps_router
from roulette import router as roulette_router
from shop import router as shop_router
from creator import router as creator_router
from slots import router as slots_router
from cups import router as cups_router
from promo import router as promo_router
from dice import router as dice_router
from craps import router as craps_router
from baccarat import router as baccarat_router
from skills import router as skills_router
from admin import router as admin_router
from admin_debts import router as admin_debts_router
from log_system import router as log_system_router
from chat_stats import router as chat_stats_router, increment_message_count
from rp_clans import router as rp_clans_router
from profile_bank import router as profile_bank_router
from group_management import router as group_management_router
from pets import router as pets_router
from economy_features import router as economy_features_router
from loans import router as loans_router
from escort import router as escort_router
from contracts import router as contracts_router
from diseases import router as diseases_router
from inventory import router as inventory_router
from hunger_games import router as hunger_games_router
from admin_pm import router as admin_pm_router
from casino_utils import router as casino_utils_router
from poker import router as poker_router
from crash import router as crash_router
from admin_dashboard import router as admin_dashboard_router
from court import router as court_router
from cards_system import router as cards_system_router
from bunker import router as bunker_router

import asyncio
from user_manager import get_user_data, update_user_balance
from diseases import get_active_diseases
from aiogram import Router
from aiogram.types import Message
from logger import log_message
from utils import is_valid_command

catch_all_router = Router()
@catch_all_router.message()
async def catch_all(message: Message, u_data: dict = None):

    if message.chat.type in ["group", "supergroup"]:
        text = message.text or message.caption or ""

        media_type = ""
        if message.photo:
            media_type = "[Фото] "
        elif message.video:
            media_type = "[Видео] "
        elif message.document:
            media_type = "[Документ] "
        elif message.voice:
            media_type = "[Голосовое] "
        elif message.audio:
            media_type = "[Аудио] "

        full_text = f"{media_type}{text}"
        if full_text.strip():
            from_user_id = message.from_user.id if message.from_user else 0
            from_user_name = message.from_user.full_name if message.from_user else "Unknown"

            if from_user_id:
                asyncio.create_task(increment_message_count(message.chat.id, from_user_id, from_user_name))

            # Проверка является ли сообщение командой ПЕРЕД запросом к БД
            if not is_valid_command(text) and not getattr(message, "reply_to_message", None):
                return

            if not message.from_user:
                return

            # --- Логика болезни "Лобковые вши" ---
            # Используем кэшированный u_data из middleware
            if u_data is None:
                u_data = await get_user_data(message.chat.id, message.from_user.id)

            diseases = u_data.get('diseases') if u_data else None
            if isinstance(diseases, dict) and 'lice' in diseases:
                active_diseases = await get_active_diseases(message.chat.id, message.from_user.id, u_data=u_data)
                if 'lice' in active_diseases:
                    if u_data.get('balance', 0) >= 10:
                        await update_user_balance(message.chat.id, message.from_user.id, -10)

def register_all_handlers(dp: Dispatcher):
    # Твоя биржа
    dp.include_router(crypto_router)
    dp.include_router(stocks_router)
    dp.include_router(seasons_router)
    
    # Остальные модули
    dp.include_router(bunker_router)
    dp.include_router(economy_router)
    dp.include_router(blackjack_router)
    dp.include_router(rps_router)
    dp.include_router(roulette_router)
    dp.include_router(shop_router)
    dp.include_router(creator_router)
    dp.include_router(slots_router)
    dp.include_router(cups_router)
    dp.include_router(promo_router)
    dp.include_router(dice_router)
    dp.include_router(craps_router)
    dp.include_router(baccarat_router)
    dp.include_router(skills_router)
    dp.include_router(admin_router)
    dp.include_router(admin_debts_router)
    dp.include_router(log_system_router)
    dp.include_router(chat_stats_router)
    dp.include_router(rp_clans_router)
    dp.include_router(profile_bank_router)
    dp.include_router(group_management_router)
    dp.include_router(pets_router)
    dp.include_router(economy_features_router)
    dp.include_router(loans_router)
    dp.include_router(escort_router)
    dp.include_router(contracts_router)
    dp.include_router(diseases_router)
    dp.include_router(inventory_router)
    dp.include_router(casino_utils_router)
    dp.include_router(poker_router)
    dp.include_router(crash_router)
    dp.include_router(admin_pm_router)
    dp.include_router(hunger_games_router)
    dp.include_router(admin_dashboard_router)
    dp.include_router(court_router)
    dp.include_router(cards_system_router)
    dp.include_router(catch_all_router)