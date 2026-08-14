import logging
import time
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from firebase_admin import firestore_async

from db import get_db
from user_manager import (
    get_user_data,
    get_user_ref,
    safe_get_snapshot,
    get_user_lock,
    invalidate_user_cache,
    set_in_cache,
    mark_dirty,
)
from escape import escape_html

logger = logging.getLogger(__name__)
router = Router()

# ─────────────────────────────────────────────────────────────
#  ТАБЛИЦА 6 РАНГОВ ПРЕСТИЖА
# ─────────────────────────────────────────────────────────────
PRESTIGE_TIERS = {
    1: {
        "name": "Барон",
        "roman": "I",
        "badge": "🌟",
        "cost": 50_000_000,
        "income_multiplier": 1.15,     # +15% доход
        "tax_discount": 5,             # -5% налог чата
        "luck_bonus": 5,               # +5% удача
        "starting_bonus": 10_000,
        "desc": "+15% к доходу, -5% к налогам, доступ к Магазину Престижа I.",
    },
    2: {
        "name": "Магнат",
        "roman": "II",
        "badge": "🌟🌟",
        "cost": 250_000_000,
        "income_multiplier": 1.30,     # +30% доход
        "tax_discount": 10,
        "luck_bonus": 10,
        "starting_bonus": 50_000,
        "desc": "+30% к доходу, -10% к налогам, +10% удача, доступ к Магазину Престижа II.",
    },
    3: {
        "name": "Олигарх",
        "roman": "III",
        "badge": "🌟🌟🌟",
        "cost": 1_000_000_000,
        "income_multiplier": 1.50,     # +50% доход
        "tax_discount": 15,
        "luck_bonus": 15,
        "starting_bonus": 250_000,
        "desc": "+50% к доходу, -15% к налогам, доступ к Магазину Престижа III.",
    },
    4: {
        "name": "Владыка",
        "roman": "IV",
        "badge": "🌟🌟🌟🌟",
        "cost": 5_000_000_000,
        "income_multiplier": 1.75,     # +75% доход
        "tax_discount": 20,
        "luck_bonus": 20,
        "starting_bonus": 1_000_000,
        "desc": "+75% к доходу, -20% к налогам, доступ к Магазину Престижа IV.",
    },
    5: {
        "name": "Титан",
        "roman": "V",
        "badge": "🌟🌟🌟🌟🌟",
        "cost": 25_000_000_000,
        "income_multiplier": 2.00,     # x2 доход
        "tax_discount": 25,
        "luck_bonus": 25,
        "starting_bonus": 5_000_000,
        "desc": "+100% (x2) к доходу, -25% к налогам, доступ к Магазину Престижа V.",
    },
    6: {
        "name": "Абсолют",
        "roman": "VI",
        "badge": "👑 АБСОЛЮТ",
        "cost": 100_000_000_000,
        "income_multiplier": 2.50,     # x2.5 доход
        "tax_discount": 35,
        "luck_bonus": 35,
        "starting_bonus": 25_000_000,
        "desc": "+150% (x2.5) к доходу, -35% к налогам, статус Абсолюта, Магазин Престижа VI.",
    },
}


def get_user_prestige(user_data: dict) -> int:
    """Возвращает текущий уровень престижа пользователя (0..6)."""
    try:
        return int(user_data.get("prestige_level", 0) or 0)
    except (ValueError, TypeError):
        return 0


def get_prestige_perks(user_data: dict) -> dict:
    """Возвращает словарь действующих бонусов престижа."""
    level = get_user_prestige(user_data)
    if level <= 0:
        return {
            "level": 0,
            "name": "Обыватель",
            "badge": "▫️",
            "income_multiplier": 1.0,
            "tax_discount": 0,
            "luck_bonus": 0,
        }
    tier = PRESTIGE_TIERS.get(level, PRESTIGE_TIERS[6])
    return {
        "level": level,
        "name": tier["name"],
        "badge": tier["badge"],
        "income_multiplier": tier["income_multiplier"],
        "tax_discount": tier["tax_discount"],
        "luck_bonus": tier["luck_bonus"],
    }


def calculate_user_net_worth(user_data: dict) -> int:
    """Суммирует капитал пользователя: баланс, банк, инвентарь, прокачку и крипто/акции."""
    balance = int(user_data.get("balance", 0) or 0)
    bank_dep = int(user_data.get("bank_deposit", 0) or 0)
    inv = user_data.get("inventory") or {}
    biz_levels = user_data.get("biz_levels") or {}

    total_inv = 0
    from shop import ITEMS
    for item_id, count in inv.items():
        try:
            cnt = int(count)
        except (ValueError, TypeError):
            continue
        if cnt <= 0 or item_id not in ITEMS:
            continue
        item = ITEMS[item_id]
        price = int(item.get("price", 0) or 0)
        total_inv += price * cnt
        if item.get("action") == "business":
            lvl = biz_levels.get(item_id, 1)
            for l in range(1, lvl):
                total_inv += int(price * 0.5 * l)

    # Криптопортфель
    crypto_val = 0
    try:
        from crypto import CRYPTO_COINS
        for cid, amt in (user_data.get("crypto_portfolio") or {}).items():
            if cid in CRYPTO_COINS:
                crypto_val += int(amt * CRYPTO_COINS[cid].get("price", 0))
    except Exception:
        pass

    # Портфель акций
    stocks_val = 0
    try:
        from stocks import STOCKS
        for sid, amt in (user_data.get("stocks_portfolio") or {}).items():
            if sid in STOCKS:
                stocks_val += int(amt * STOCKS[sid].get("price", 0))
    except Exception:
        pass

    return max(0, balance + bank_dep + total_inv + crypto_val + stocks_val)


def render_progress_bar(current: int, target: int, length: int = 10) -> str:
    """Генерирует визуальный прогресс-бар."""
    if target <= 0:
        return "▰" * length
    ratio = min(1.0, max(0.0, current / target))
    filled = int(ratio * length)
    return "▰" * filled + "▱" * (length - filled) + f" ({int(ratio * 100)}%)"


# ─────────────────────────────────────────────────────────────
#  ХЕНДЛЕРЫ МЕНЮ ПРЕСТИЖА
# ─────────────────────────────────────────────────────────────
@router.message(Command("prestige", "перерождение", "престиж"))
@router.message(F.text.lower().in_(["престиж", "перерождение", "/prestige", "ранг престижа"]))
async def cmd_prestige(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    data = await get_user_data(chat_id, user_id, message.from_user.full_name)

    curr_tier = get_user_prestige(data)
    net_worth = calculate_user_net_worth(data)
    perks = get_prestige_perks(data)

    next_tier = curr_tier + 1
    next_info = PRESTIGE_TIERS.get(next_tier)

    builder = InlineKeyboardBuilder()

    if next_info:
        req_cost = next_info["cost"]
        bar = render_progress_bar(net_worth, req_cost)
        can_prestige = net_worth >= req_cost

        text = (
            f"🌟 <b>СИСТЕМА ПРЕСТИЖА (ПЕРЕРОЖДЕНИЕ)</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Игрок: <b>{escape_html(message.from_user.full_name)}</b>\n"
            f"🎖 Текущий ранг: <b>[{curr_tier}/6] {perks['badge']} {perks['name']}</b>\n"
            f"📈 Действующие бонусы:\n"
            f" • Доход: <b>+{int((perks['income_multiplier'] - 1.0) * 100)}%</b>\n"
            f" • Скидка на налоги: <b>-{perks['tax_discount']}%</b>\n"
            f" • Бонус удачи: <b>+{perks['luck_bonus']}%</b>\n\n"
            f"💰 Общий капитал (активы): <b>{net_worth:,}</b> сыр.\n"
            f"🎯 Цель для Престижа {next_info['roman']} ({next_info['name']}): <b>{req_cost:,}</b> сыр.\n"
            f"Прогресс: {bar}\n\n"
            f"🎁 <b>Награды за Престиж {next_info['roman']}:</b>\n"
            f" • {next_info['desc']}\n"
            f" • Стартовый капитал: <b>+{next_info['starting_bonus']:,}</b> сыр.\n\n"
            f"⚠️ <i>При перерождении обычные деньги, банк и базовые бизнесы сбрасываются. "
            f"Карточки свинок, кланы, браки и предметы Престижа полностью СОХРАНЯЮТСЯ!</i>"
        )

        if can_prestige:
            builder.button(
                text=f"✨ Переродиться в Престиж {next_info['roman']} ({next_info['name']})",
                callback_data=f"prestige_ask_{next_tier}",
            )
        else:
            builder.button(
                text=f"🔒 Недостаточно капитала ({net_worth:,} / {req_cost:,})",
                callback_data="prestige_locked",
            )
    else:
        text = (
            f"👑 <b>ВЫ ДОСТИГЛИ МАКСИМАЛЬНОГО ПРЕСТИЖА VI: АБСОЛЮТ!</b> 👑\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Вы находитесь на абсолютной вершине величия!\n\n"
            f"🎖 Ранг: <b>{perks['badge']} {perks['name']}</b>\n"
            f"📈 Ваши перки: <b>+150% к доходу, -35% к налогам, +35% удачи</b>\n"
            f"🌟 Доступ ко всем эксклюзивным товарам и технологиям в Магазине Престижа!"
        )

    builder.button(text="🌟 Магазин Престижа", callback_data="shop_cat_prestige")
    builder.button(text="❌ Закрыть", callback_data="prestige_close")
    builder.adjust(1)

    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("prestige_ask_"))
async def ask_prestige_confirm(callback: types.CallbackQuery):
    await callback.answer()
    tier = int(callback.data.removeprefix("prestige_ask_"))
    tier_info = PRESTIGE_TIERS.get(tier)
    if not tier_info:
        return

    text = (
        f"⚠️ <b>ПОДТВЕРЖДЕНИЕ ПЕРЕРОЖДЕНИЯ</b> ⚠️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Вы собираетесь получить <b>Престиж {tier_info['roman']}: {tier_info['name']}</b>!\n\n"
        f"⚡️ <b>Что произойдет:</b>\n"
        f" 1. Баланс, банковский вклад и базовые бизнесы будут сброшены.\n"
        f" 2. Вы получите стартовый капитал: <b>{tier_info['starting_bonus']:,} сыр.</b>\n"
        f" 3. Навсегда активируется перк: <b>+{int((tier_info['income_multiplier'] - 1.0) * 100)}% к доходу</b>!\n"
        f" 4. Откроется доступ к Магазину Престижа {tier_info['roman']}!\n"
        f" 5. Коллекция карточек свинок и клан останутся с вами.\n\n"
        f"Вы уверены, что готовы начать новый цикл?"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, совершить Престиж!", callback_data=f"prestige_confirm_{tier}")
    builder.button(text="❌ Отмена", callback_data="prestige_cancel")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("prestige_confirm_"))
async def process_prestige_confirm(callback: types.CallbackQuery):
    target_tier = int(callback.data.removeprefix("prestige_confirm_"))
    tier_info = PRESTIGE_TIERS.get(target_tier)
    if not tier_info:
        return await callback.answer("Ошибка ранга.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    db = get_db()

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        @firestore_async.async_transactional
        async def _prestige_txn(transaction):
            ref = get_user_ref(chat_id, user_id)
            snapshot = await safe_get_snapshot(transaction, ref)
            if not snapshot.exists:
                return False, "Профиль не найден."

            data = snapshot.to_dict() or {}
            curr_tier = get_user_prestige(data)
            if target_tier != curr_tier + 1:
                return False, "Неверная последовательность рангов престижа."

            net_worth = calculate_user_net_worth(data)
            if net_worth < tier_info["cost"]:
                return False, f"Недостаточно капитала ({net_worth:,} из {tier_info['cost']:,} сыр.)."

            # Сохраняем только престиж-предметы и карточки
            from shop import ITEMS
            old_inv = data.get("inventory") or {}
            new_inv = {}
            for item_id, count in old_inv.items():
                item = ITEMS.get(item_id)
                if item and item.get("cat") == "prestige":
                    new_inv[item_id] = count

            updates = {
                "prestige_level": target_tier,
                "balance": tier_info["starting_bonus"],
                "bank_deposit": 0,
                "inventory": new_inv,
                "biz_levels": {},
                "crypto_portfolio": {},
                "stocks_portfolio": {},
            }
            transaction.update(ref, updates)
            return True, None

        try:
            success, err = await _prestige_txn(db.transaction())
        except Exception as e:
            logger.exception("Prestige transaction failed for user %s: %s", user_id, e)
            return await callback.answer("Ошибка при выполнении транзакции Престижа.", show_alert=True)

        if not success:
            return await callback.answer(err or "Не удалось совершить Престиж.", show_alert=True)

        invalidate_user_cache(chat_id, user_id)

    congrats_text = (
        f"🎉 <b>ПОЗДРАВЛЯЕМ С ПЕРЕРОЖДЕНИЕМ!</b> 🎉\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Ковбой <b>{escape_html(callback.from_user.full_name)}</b> успешно переродился и получил:\n"
        f"🎖 <b>Престиж {tier_info['roman']}: {tier_info['badge']} {tier_info['name']}</b>!\n\n"
        f"✨ Стартовый баланс: <b>{tier_info['starting_bonus']:,}</b> сыр.\n"
        f"🔥 Постоянный бонус к доходу: <b>+{int((tier_info['income_multiplier'] - 1.0) * 100)}%</b>\n"
        f"🛡 Скидка на налоги: <b>-{tier_info['tax_discount']}%</b>\n"
        f"🌟 Открыт доступ к новым товарам в <b>/shop</b> -> «🌟 Магазин Престижа»!"
    )
    await callback.message.edit_text(congrats_text)


@router.callback_query(F.data == "prestige_locked")
async def prestige_locked_cb(callback: types.CallbackQuery):
    await callback.answer("У вас пока недостаточно капитала для следующего Престижа. Копите средства!", show_alert=True)


@router.callback_query(F.data.in_(["prestige_close", "prestige_cancel"]))
async def prestige_cancel_cb(callback: types.CallbackQuery):
    await callback.answer("Закрыто.")
    try:
        await callback.message.delete()
    except Exception:
        pass
