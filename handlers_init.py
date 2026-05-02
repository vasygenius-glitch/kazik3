from aiogram import Dispatcher
from crypto import router as crypto_router
from economy import router as economy_router
from blackjack import router as blackjack_router
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

from aiogram import Router
from aiogram.types import Message
from logger import log_message

catch_all_router = Router()
@catch_all_router.message()
async def catch_all(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        # --- Блок проверки банкирской субсидии (Banker Daily Subsidy) ---
        import time
        from user_manager import get_user_data, update_user_balance, update_user_field
        from profile_bank import get_bank_info, create_or_update_bank

        chat_id = message.chat.id
        user_id = message.from_user.id

        try:
            udata = await get_user_data(chat_id, user_id)
            if udata.get('is_banker', False):
                current_time = time.time()
                last_daily = udata.get('last_banker_daily', 0)
                # Если прошло больше 24 часов (86400 сек) или наступил новый день (упрощенно можно по времени)
                # Для стабильности сделаем проверку на 24 часа.
                # Так как мы хотим в 00:00, лучше ориентироваться на дату (но так как в ТЗ просили "раз в день" при первом сообщении после 00:00)
                from datetime import datetime
                import pytz

                # Используем MSK
                msk_tz = pytz.timezone('Europe/Moscow')
                now_msk = datetime.now(msk_tz)

                if last_daily:
                    last_dt = datetime.fromtimestamp(last_daily, tz=msk_tz)
                else:
                    last_dt = None

                if not last_dt or now_msk.date() > last_dt.date():
                    # Начисляем ежедневные средства
                    bank_data = await get_bank_info(chat_id, user_id)
                    if bank_data:
                        # 50 млн в капитал банка
                        await create_or_update_bank(chat_id, user_id, {'capital': bank_data.get('capital', 0) + 50000000})
                        # 7к сыроежек банкиру на руки
                        await update_user_balance(chat_id, user_id, 7000)

                        await update_user_field(chat_id, user_id, 'last_banker_daily', current_time)

                        await message.answer(f"🏦 <b>Ежедневное пополнение от ЦентроЖБРОМа!</b>\n"
                                             f"Уважаемый {message.from_user.full_name}, ваш банк получил <b>50.000.000</b> сыр. в капитал.\n"
                                             f"Вам начислен оклад в размере <b>7.000</b> сыр.")
        except Exception as e:
            print(f"Ошибка ежедневной субсидии: {e}")
        # ------------------------------------------------------------------

        text = message.text or message.caption or ""
        media_type = ""
        if message.photo: media_type = "[Фото] "
        elif message.video: media_type = "[Видео] "
        elif message.sticker: media_type = "[Стикер] "
        elif message.voice: media_type = "[Голосовое] "
        elif message.document: media_type = "[Файл] "

        full_text = f"{media_type}{text}"
        if full_text.strip():
            log_message(message.chat.id, message.chat.title or "Unknown", message.from_user.id, message.from_user.full_name, full_text)
            import asyncio
            asyncio.create_task(increment_message_count(message.chat.id, message.from_user.id, message.from_user.full_name))

def register_all_handlers(dp: Dispatcher):
    # Твоя биржа
    dp.include_router(crypto_router)
    
    # Остальные модули
    dp.include_router(economy_router)
    dp.include_router(blackjack_router)
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
    dp.include_router(catch_all_router)