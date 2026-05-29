# -*- coding: utf-8 -*-
"""
loans.py
========

Модуль системы кредитования для Telegram-бота (игровая валюта «сыроежки»).

Возможности:
    • Выдача кредитов банкирами игрокам (с поручителями и без).
    • Погашение кредитов (полное и частичное) со скидкой за досрочное закрытие.
    • Комиссия банкира с процентов.
    • Кредитный рейтинг заёмщиков (повышение/понижение).
    • Просмотр собственных долгов и выданных кредитов.
    • Кредитный калькулятор.
    • Подробное логирование всех операций.

Зависимости проекта:
    aiogram, firebase_admin, user_manager, profile_bank, db, escape, diseases, log_system.

Автор: улучшенная версия. Готово к использованию.
"""

import time
import uuid
import logging
import asyncio
from typing import Optional, Dict, Any, Tuple, List

from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from escape import escape_html
from user_manager import (
    get_user_data,
    update_user_balance,
    update_user_field,
    get_user_ref,
    safe_get_snapshot,
    invalidate_user_cache,
)
from profile_bank import get_bank_info, create_or_update_bank, invalidate_bank_cache
from db import get_db
from firebase_admin import firestore_async


# ---------------------------------------------------------------------------
#  Логирование
# ---------------------------------------------------------------------------
logger = logging.getLogger("loans")
if not logger.handlers:
    # Настраиваем базовый обработчик, если он ещё не задан в проекте.
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [loans] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
#  Конфигурация / Константы
#  (Все «магические числа» собраны здесь для удобной настройки.)
# ---------------------------------------------------------------------------
class LoanConfig:
    """Глобальные настройки кредитной системы."""

    # --- Кредитный рейтинг ---
    DEFAULT_CREDIT_SCORE: int = 100      # стартовый рейтинг нового заёмщика
    MIN_CREDIT_SCORE: int = 0            # минимально возможный рейтинг
    MAX_CREDIT_SCORE: int = 500          # максимально возможный рейтинг
    SCORE_REWARD_ON_REPAY: int = 10      # +рейтинг за полное погашение
    SCORE_PENALTY_ON_DEFAULT: int = 25   # -рейтинг за просрочку/дефолт

    # --- Скидки и комиссии ---
    EARLY_REPAY_DISCOUNT_RATE: float = 0.20   # 20% от процентов в подарок при досрочке
    BANKER_COMMISSION_RATE: float = 0.10      # 10% от прибыли банкиру
    EARLY_REPAY_MIN_SECONDS: int = 86400      # «досрочно» = осталось > 1 суток

    # --- Ограничения сумм / процентов / сроков ---
    MIN_LOAN_AMOUNT: int = 1
    MAX_LOAN_AMOUNT: int = 10_000_000
    MIN_PERCENT: int = 0
    MAX_PERCENT: int = 1000
    MIN_TERM_DAYS: int = 1
    MAX_TERM_DAYS: int = 365

    # --- Прочее ---
    SECONDS_IN_DAY: int = 86400
    OFFER_TTL_SECONDS: int = 600          # сколько живёт предложение кредита (10 минут)
    LOAN_ID_PREFIX: str = "bk"            # префикс для callback-данных
    BANK_DEBT_PREFIX: str = "bank_"       # префикс ключа долга банку


# ---------------------------------------------------------------------------
#  Роутер и хранилище активных предложений
# ---------------------------------------------------------------------------
router = Router()

# active_loans: { loan_id -> {данные предложения + created_at} }
active_loans: Dict[str, Dict[str, Any]] = {}


# ===========================================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ===========================================================================
def now_ts() -> int:
    """Текущее время в виде целого числа секунд (Unix timestamp)."""
    return int(time.time())


def clamp(value: int, low: int, high: int) -> int:
    """Ограничивает значение диапазоном [low, high]."""
    return max(low, min(high, value))


def calc_total_debt(amount: int, percent: int) -> int:
    """
    Рассчитывает итоговую сумму к возврату.

    :param amount: тело кредита.
    :param percent: процентная ставка (в процентах).
    :return: сумма с процентами, округлённая вниз.
    """
    return int(amount * (1 + percent / 100))


def calc_interest(amount: int, percent: int) -> int:
    """Возвращает сумму одних только процентов (переплату)."""
    return calc_total_debt(amount, percent) - amount


def make_loan_id() -> Tuple[str, str]:
    """
    Генерирует короткий уникальный идентификатор предложения.

    :return: кортеж (loan_id, short_id), где loan_id — ключ в active_loans,
             short_id — короткая часть для callback_data.
    """
    short_id = uuid.uuid4().hex[:8]
    loan_id = f"{LoanConfig.LOAN_ID_PREFIX}_{short_id}"
    return loan_id, short_id


def build_bank_debt_key(lender_id: int, due_date: int, guarantor_id: Optional[int], amount: int) -> str:
    """
    Формирует строковый ключ долга банку.

    Формат: bank_{lender_id}_{due_date}_{guarantor_id|none}_{amount}
    """
    g = str(guarantor_id) if guarantor_id else "none"
    return f"{LoanConfig.BANK_DEBT_PREFIX}{lender_id}_{due_date}_{g}_{amount}"


def parse_bank_debt_key(key: str) -> Optional[Dict[str, Any]]:
    """
    Безопасно разбирает ключ долга банку.

    :return: словарь с полями lender_id, due_date, guarantor_id, principal
             либо None, если ключ нераспознаваем.
    """
    if not key.startswith(LoanConfig.BANK_DEBT_PREFIX):
        return None
    parts = key.split("_")
    # bank_{lender}_{due}_{guarantor}_{amount}
    if len(parts) < 5:
        return None
    try:
        lender_id = int(parts[1])
        due_date = int(parts[2])
        guarantor_raw = parts[3]
        guarantor_id = None if guarantor_raw == "none" else int(guarantor_raw)
        principal = int(parts[4])
    except (ValueError, IndexError):
        return None
    return {
        "lender_id": lender_id,
        "due_date": due_date,
        "guarantor_id": guarantor_id,
        "principal": principal,
    }


def is_overdue(due_date: int, current_time: Optional[int] = None) -> bool:
    """Проверяет, просрочен ли долг."""
    if current_time is None:
        current_time = now_ts()
    return due_date > 0 and current_time > due_date


def humanize_seconds(seconds: int) -> str:
    """
    Превращает количество секунд в человекочитаемую строку.

    Пример: 90061 -> "1 д. 1 ч. 1 мин."
    """
    if seconds <= 0:
        return "просрочено"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    chunks: List[str] = []
    if days:
        chunks.append(f"{days} д.")
    if hours:
        chunks.append(f"{hours} ч.")
    if minutes and not days:  # минуты показываем только если меньше суток
        chunks.append(f"{minutes} мин.")
    return " ".join(chunks) if chunks else "меньше минуты"


def cleanup_expired_offers() -> int:
    """
    Удаляет из памяти просроченные предложения кредитов.

    :return: количество удалённых предложений.
    """
    current = now_ts()
    expired = [
        lid for lid, info in active_loans.items()
        if current - int(info.get("created_at", current)) > LoanConfig.OFFER_TTL_SECONDS
    ]
    for lid in expired:
        active_loans.pop(lid, None)
    if expired:
        logger.info("Очищено просроченных предложений: %d", len(expired))
    return len(expired)


def get_credit_score(user_data: Dict[str, Any]) -> int:
    """Безопасно достаёт кредитный рейтинг пользователя."""
    return int(user_data.get("credit_score", LoanConfig.DEFAULT_CREDIT_SCORE) or LoanConfig.DEFAULT_CREDIT_SCORE)


def credit_score_label(score: int) -> str:
    """Возвращает текстовую оценку рейтинга для отображения."""
    if score >= 400:
        return "🟢 Отличный"
    if score >= 250:
        return "🟡 Хороший"
    if score >= 100:
        return "🟠 Средний"
    if score >= 50:
        return "🔴 Низкий"
    return "⚫ Критический"


def validate_loan_params(amount: int, percent: int, term_days: int) -> Optional[str]:
    """
    Проверяет корректность параметров кредита.

    :return: строку с ошибкой, либо None если всё в порядке.
    """
    if amount < LoanConfig.MIN_LOAN_AMOUNT:
        return f"Сумма кредита должна быть не меньше {LoanConfig.MIN_LOAN_AMOUNT}."
    if amount > LoanConfig.MAX_LOAN_AMOUNT:
        return f"Сумма кредита слишком большая (максимум {LoanConfig.MAX_LOAN_AMOUNT:,})."
    if percent < LoanConfig.MIN_PERCENT:
        return "Процент по кредиту не может быть отрицательным."
    if percent > LoanConfig.MAX_PERCENT:
        return f"Процент слишком велик (максимум {LoanConfig.MAX_PERCENT}%)."
    if term_days < LoanConfig.MIN_TERM_DAYS:
        return f"Срок кредита должен быть не меньше {LoanConfig.MIN_TERM_DAYS} дн."
    if term_days > LoanConfig.MAX_TERM_DAYS:
        return f"Срок кредита слишком велик (максимум {LoanConfig.MAX_TERM_DAYS} дн.)."
    return None


async def safe_log_loan(**kwargs) -> None:
    """
    Безопасная обёртка над log_system.log_loan.

    Никогда не выбрасывает исключения наружу — только пишет в логгер.
    """
    try:
        from log_system import log_loan
        log_loan(**kwargs)
    except Exception as exc:  # noqa: BLE001 — логирование не должно ломать логику
        logger.warning("Не удалось залогировать операцию кредита: %s", exc)


async def get_message_link(message: types.Message) -> str:
    """Безопасно возвращает ссылку на сообщение (или пустую строку)."""
    try:
        return message.link or ""
    except Exception:
        return ""


# ===========================================================================
#  ТРАНЗАКЦИИ FIRESTORE
# ===========================================================================
@firestore_async.async_transactional
async def issue_loan_tx(
    transaction,
    chat_id: int,
    lender_id: int,
    borrower_id: int,
    amount: int,
    total_debt: int,
    term_days: int,
    guarantor_id: Optional[int],
):
    """
    Атомарно выдаёт кредит:
        1. Списывает капитал у банка.
        2. Начисляет тело кредита заёмщику.
        3. Записывает долг (с процентами) заёмщику.

    Бросает ValueError при недостатке средств или отсутствии данных.
    """
    db = get_db()
    bank_ref = (
        db.collection("chats")
        .document(str(chat_id))
        .collection("banks")
        .document(str(lender_id))
    )
    user_ref = get_user_ref(chat_id, borrower_id)

    # --- Чтения должны идти до записей в транзакции Firestore ---
    bank_snap = await safe_get_snapshot(transaction, bank_ref)
    if not bank_snap.exists:
        raise ValueError("Банк не найден.")

    bank_dict = bank_snap.to_dict() or {}
    bank_capital = int(bank_dict.get("capital", 0) or 0)
    if bank_capital < amount:
        raise ValueError("У банка недостаточно капитала.")

    user_snap = await safe_get_snapshot(transaction, user_ref)
    if not user_snap.exists:
        raise ValueError("Заёмщик не найден.")

    user_data = user_snap.to_dict() or {}

    # --- Подготовка обновлений ---
    new_capital = bank_capital - amount
    new_balance = int(user_data.get("balance", 0) or 0) + amount

    debts = dict(user_data.get("debts") or {})
    due_date = now_ts() + (term_days * LoanConfig.SECONDS_IN_DAY)
    debt_key = build_bank_debt_key(lender_id, due_date, guarantor_id, amount)
    debts[debt_key] = debts.get(debt_key, 0) + total_debt

    # Если у заёмщика ещё нет рейтинга — выставляем стартовый.
    credit_score = get_credit_score(user_data)

    # --- Записи ---
    transaction.update(bank_ref, {"capital": new_capital})
    transaction.update(user_ref, {
        "balance": new_balance,
        "debts": debts,
        "credit_score": credit_score,
    })

    return {
        "debt_key": debt_key,
        "due_date": due_date,
        "new_balance": new_balance,
        "new_capital": new_capital,
    }


@firestore_async.async_transactional
async def repay_loan_tx(
    transaction,
    chat_id: int,
    borrower_id: int,
    lender_id: int,
    amount: int,
    current_time: float,
    target_debt_key: str,
):
    """
    Атомарно погашает кредит (полностью или частично).

    Логика:
        • Скидка за досрочное погашение (если осталось > суток и платим всё).
        • Комиссия банкиру с прибыли при полном закрытии банковского долга.
        • Повышение кредитного рейтинга при полном закрытии.
        • Возврат средств в капитал банка / на счёт кредитора.

    :return: словарь с деталями операции.
    """
    db = get_db()
    current_time = int(current_time)

    borrower_ref = get_user_ref(chat_id, borrower_id)

    # --- Все чтения сначала ---
    borrower_snap = await safe_get_snapshot(transaction, borrower_ref)
    if not borrower_snap.exists:
        raise ValueError("Заёмщик не найден.")

    borrower_data = borrower_snap.to_dict() or {}
    balance = int(borrower_data.get("balance", 0) or 0)

    debts = dict(borrower_data.get("debts") or {})
    if target_debt_key not in debts or debts[target_debt_key] <= 0:
        raise ValueError("Долг уже выплачен или не существует.")

    current_debt = int(debts[target_debt_key])
    is_bank_debt = target_debt_key.startswith(LoanConfig.BANK_DEBT_PREFIX)

    discount = 0
    banker_commission = 0

    parsed = parse_bank_debt_key(target_debt_key) if is_bank_debt else None

    if is_bank_debt and parsed:
        due_date = parsed["due_date"]
        principal = parsed["principal"]

        # Скидка за досрочное погашение (только при полном закрытии).
        potential_discount = 0
        if due_date - current_time > LoanConfig.EARLY_REPAY_MIN_SECONDS:
            potential_discount = max(0, int((current_debt - principal) * LoanConfig.EARLY_REPAY_DISCOUNT_RATE))

        if amount >= current_debt - potential_discount:
            discount = potential_discount
            current_debt -= discount

            profit_margin = current_debt - principal
            if profit_margin > 0:
                banker_commission = int(profit_margin * LoanConfig.BANKER_COMMISSION_RATE)

    # Сумма реального платежа.
    repay_amount = min(amount, current_debt)
    if balance < repay_amount:
        raise ValueError("У тебя нет столько денег на балансе.")

    new_balance = balance - repay_amount
    debts[target_debt_key] = current_debt - repay_amount

    rating_msg = ""
    credit_score = get_credit_score(borrower_data)
    fully_repaid = False

    if debts[target_debt_key] <= 0:
        del debts[target_debt_key]
        fully_repaid = True
        if is_bank_debt:
            new_score = clamp(
                credit_score + LoanConfig.SCORE_REWARD_ON_REPAY,
                LoanConfig.MIN_CREDIT_SCORE,
                LoanConfig.MAX_CREDIT_SCORE,
            )
            if new_score != credit_score:
                rating_msg = f"\n📈 Ваш кредитный рейтинг повышен до <b>{new_score}</b>!"
            credit_score = new_score

    # Подготовим возврат денег кредитору (нужны чтения банка/кредитора).
    capital_return = repay_amount - banker_commission

    bank_ref = None
    bank_exists = False
    bank_capital = 0
    banker_ref = None
    banker_balance = 0
    lender_ref = None
    lender_balance = 0

    if is_bank_debt:
        bank_ref = (
            db.collection("chats")
            .document(str(chat_id))
            .collection("banks")
            .document(str(lender_id))
        )
        bank_snap = await safe_get_snapshot(transaction, bank_ref)
        bank_exists = bool(bank_snap.exists)
        if bank_exists:
            bank_capital = int((bank_snap.to_dict() or {}).get("capital", 0) or 0)
            if banker_commission > 0:
                banker_ref = get_user_ref(chat_id, lender_id)
                banker_snap = await safe_get_snapshot(transaction, banker_ref)
                if banker_snap.exists:
                    banker_balance = int((banker_snap.to_dict() or {}).get("balance", 0) or 0)
                else:
                    banker_ref = None  # некому начислять комиссию
        else:
            # Банка нет — вернём напрямую банкиру.
            banker_ref = get_user_ref(chat_id, lender_id)
            banker_snap = await safe_get_snapshot(transaction, banker_ref)
            if banker_snap.exists:
                banker_balance = int((banker_snap.to_dict() or {}).get("balance", 0) or 0)
            else:
                banker_ref = None
    else:
        lender_ref = get_user_ref(chat_id, lender_id)
        lender_snap = await safe_get_snapshot(transaction, lender_ref)
        if lender_snap.exists:
            lender_balance = int((lender_snap.to_dict() or {}).get("balance", 0) or 0)
        else:
            lender_ref = None

    # --- Все записи после всех чтений ---
    transaction.update(borrower_ref, {
        "balance": new_balance,
        "debts": debts,
        "credit_score": credit_score,
    })

    if is_bank_debt:
        if bank_exists and bank_ref is not None:
            transaction.update(bank_ref, {"capital": bank_capital + capital_return})
            if banker_commission > 0 and banker_ref is not None:
                transaction.update(banker_ref, {"balance": banker_balance + banker_commission})
        elif banker_ref is not None:
            # Банк удалён — отдаём всю сумму банкиру.
            transaction.update(banker_ref, {"balance": banker_balance + repay_amount})
    else:
        if lender_ref is not None:
            transaction.update(lender_ref, {"balance": lender_balance + repay_amount})

    return {
        "repay_amount": repay_amount,
        "discount": discount,
        "banker_commission": banker_commission,
        "rating_msg": rating_msg,
        "remaining_debt": debts.get(target_debt_key, 0),
        "fully_repaid": fully_repaid,
        "is_bank_debt": is_bank_debt,
    }


# ===========================================================================
#  ОБРАБОТЧИКИ КОМАНД
# ===========================================================================
@router.message(F.text.lower().startswith("кредит") | F.text.lower().startswith("/credit"))
async def cmd_credit(message: types.Message):
    """
    Команда выдачи кредита банкиром.

    Использование (реплаем на заёмщика):
        кредит <сумма> <%> <срок_в_днях> [ID_поручителя]
    """
    cleanup_expired_offers()

    chat_id = message.chat.id
    lender_id = message.from_user.id

    # --- Проверка прав банкира ---
    data = await get_user_data(chat_id, lender_id)
    if not data.get("is_banker", False):
        return await message.answer("❌ Только банкиры могут выдавать кредиты.")

    # --- Болезни могут блокировать выдачу ---
    try:
        from diseases import get_active_diseases
        active_diseases = await get_active_diseases(chat_id, lender_id)
        if "hepatitis" in active_diseases:
            return await message.answer(
                "🦠 <b>Гепатит</b>: Вы лежите в больнице. Выдача кредитов сейчас невозможна."
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Не удалось проверить болезни: %s", exc)

    # --- Реплай обязателен ---
    if not message.reply_to_message:
        return await message.answer(
            "Сделайте реплай на сообщение игрока, которому хотите выдать кредит."
        )

    args = message.text.split()
    if len(args) < 4:
        return await message.answer(
            "Использование: <code>кредит [сумма] [%] [срок в днях]</code>\n"
            "Пример: <code>кредит 1000 10 7</code>\n\n"
            "Вы можете добавить поручителя: "
            "<code>кредит [сумма] [%] [срок] [ID_поручителя]</code>"
        )

    borrower_id = message.reply_to_message.from_user.id
    if lender_id == borrower_id:
        return await message.answer("Самому себе кредит выдать нельзя.")
    if message.reply_to_message.from_user.is_bot:
        return await message.answer("Ботам кредиты не нужны.")

    # --- Парсинг чисел ---
    try:
        amount = int(args[1])
        percent = int(args[2])
        term_days = int(args[3])
    except ValueError:
        return await message.answer("Сумма, процент и срок должны быть числами.")

    error = validate_loan_params(amount, percent, term_days)
    if error:
        return await message.answer(f"❌ {error}")

    # --- Поручитель (необязательно) ---
    guarantor_id: Optional[int] = None
    if len(args) >= 5:
        try:
            guarantor_id = int(args[4])
        except ValueError:
            return await message.answer("ID поручителя должен быть числом.")
        if guarantor_id == borrower_id:
            return await message.answer("Заёмщик не может быть поручителем самому себе.")

    # --- Проверка банка ---
    bank_data = await get_bank_info(chat_id, lender_id)
    if not bank_data:
        return await message.answer(
            "❌ У вас ещё не создан банк. Создайте его командой "
            "<code>создать банк [Название]</code>."
        )

    bank_capital = int(bank_data.get("capital", 0) or 0)
    if bank_capital < amount:
        return await message.answer(
            f"❌ В капитале вашего банка недостаточно средств!\n"
            f"Требуется: <b>{amount:,}</b>, доступно: <b>{bank_capital:,}</b>."
        )

    # --- Формируем предложение ---
    loan_id, short_id = make_loan_id()
    active_loans[loan_id] = {
        "amount": amount,
        "percent": percent,
        "term_days": term_days,
        "chat_id": chat_id,
        "lender_id": lender_id,
        "borrower_id": borrower_id,
        "guarantor_id": guarantor_id,
        "original_principal": amount,
        "created_at": now_ts(),
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="Взять кредит 🤝", callback_data=f"bk_yes_{short_id}")
    builder.button(text="Отказаться ❌", callback_data=f"bk_no_{short_id}")
    builder.adjust(2)

    total_return = calc_total_debt(amount, percent)
    interest = calc_interest(amount, percent)
    bank_name = escape_html(bank_data.get("name", "Неизвестный Банк"))

    borrower_data = await get_user_data(chat_id, borrower_id)
    credit_score = get_credit_score(borrower_data)

    guarantor_text = (
        f"\nПоручитель (ID): <code>{guarantor_id}</code>" if guarantor_id else ""
    )

    await message.answer(
        f"💸 <b>Кредитный договор с банком «{bank_name}»!</b>\n\n"
        f"Заёмщик: <b>{escape_html(message.reply_to_message.from_user.full_name)}</b> "
        f"({credit_score_label(credit_score)} — {credit_score}){guarantor_text}\n\n"
        f"💰 Тело кредита: <b>{amount:,}</b> сыроежек\n"
        f"📊 Ставка: <b>{percent}%</b> (переплата <b>{interest:,}</b>)\n"
        f"⏳ Срок: <b>{term_days}</b> дн.\n"
        f"💵 Итого к возврату: <b>{total_return:,}</b> сыроежек.\n\n"
        f"Заёмщик, согласны с условиями?",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("bk_yes_") | F.data.startswith("bk_no_"))
async def process_bank_loan(callback: types.CallbackQuery):
    """Обработка кнопок «Взять кредит» / «Отказаться»."""
    cleanup_expired_offers()

    try:
        _, action, short_id = callback.data.split("_", 2)
    except ValueError:
        return await callback.answer("Некорректные данные кнопки.", show_alert=True)

    loan_id = f"bk_{short_id}"
    loan_info = active_loans.get(loan_id)
    if not loan_info:
        return await callback.answer("Это предложение устарело.", show_alert=True)

    chat_id = loan_info["chat_id"]
    lender_id = loan_info["lender_id"]
    borrower_id = loan_info["borrower_id"]

    # --- Кто имеет право жать кнопку ---
    if callback.from_user.id != borrower_id:
        # Банкир может отозвать своё предложение.
        if action == "no" and callback.from_user.id == lender_id:
            pass
        else:
            return await callback.answer("Это предлагают не тебе!", show_alert=True)

    # Удаляем предложение из памяти (одноразовое).
    active_loans.pop(loan_id, None)

    # --- Отказ / отзыв ---
    if action == "no":
        if callback.from_user.id == lender_id:
            return await callback.message.edit_text("❌ Банкир отозвал предложение по кредиту.")
        return await callback.message.edit_text("❌ Клиент отказался брать кредит.")

    # --- Оформление кредита ---
    amount = loan_info["amount"]
    percent = loan_info["percent"]
    term_days = loan_info["term_days"]
    guarantor_id = loan_info["guarantor_id"]
    total_debt = calc_total_debt(amount, percent)

    db = get_db()

    try:
        from user_manager import get_user_lock
        lock = get_user_lock(chat_id, borrower_id)
        async with lock:
            await issue_loan_tx(
                db.transaction(),
                chat_id, lender_id, borrower_id,
                amount, total_debt, term_days, guarantor_id,
            )
            invalidate_user_cache(chat_id, borrower_id)
            invalidate_bank_cache(chat_id, lender_id)

        await callback.message.edit_text(
            f"🤝 Кредит оформлен на <b>{term_days}</b> дн.!\n"
            f"💰 Получено: <b>{amount:,}</b> сыроежек.\n"
            f"💵 Долг банку: <b>{total_debt:,}</b> сыроежек."
        )

        # --- Логирование ---
        borrower_data = await get_user_data(chat_id, borrower_id)
        lender_data = await get_user_data(chat_id, lender_id)
        await safe_log_loan(
            action_type="issue",
            chat_id=chat_id,
            chat_title=getattr(callback.message.chat, "title", None) or "Unknown",
            lender_id=lender_id,
            lender_name=lender_data.get("full_name") or "Unknown",
            lender_username=lender_data.get("username") or "",
            borrower_id=borrower_id,
            borrower_name=borrower_data.get("full_name") or "Unknown",
            borrower_username=borrower_data.get("username") or "",
            amount=amount,
            total_debt=total_debt,
            term_days=term_days,
            guarantor_id=guarantor_id,
            message_link=await get_message_link(callback.message),
        )

    except ValueError as ve:
        await callback.message.edit_text(f"❌ Ошибка: {ve}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка в process_bank_loan: %s", exc)
        await callback.message.edit_text("❌ Произошла ошибка при оформлении кредита.")


@router.message(F.text.lower().startswith("выплатить") | F.text.lower().startswith("вернуть"))
async def cmd_repay(message: types.Message):
    """
    Команда погашения долга.

    Использование (реплаем на кредитора/банкира):
        выплатить <сумма>
    """
    if not message.reply_to_message:
        return await message.answer(
            "Сделай реплай на кредитора (или банкира), которому возвращаешь долг."
        )

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажи сумму: <code>выплатить [сумма]</code>")

    try:
        amount = int(args[1])
    except ValueError:
        return await message.answer("Сумма должна быть целым числом.")

    if amount <= 0:
        return await message.answer("Сумма должна быть больше нуля.")

    chat_id = message.chat.id
    borrower_id = message.from_user.id
    lender_id = message.reply_to_message.from_user.id

    borrower_data = await get_user_data(chat_id, borrower_id)
    debts = borrower_data.get("debts") or {}

    target_debt_key = _find_debt_key(debts, lender_id)
    if not target_debt_key:
        return await message.answer("Ты ничего не должен этому человеку/банку.")

    db = get_db()
    try:
        from user_manager import get_user_lock
        lock = get_user_lock(chat_id, borrower_id)
        async with lock:
            res = await repay_loan_tx(
                db.transaction(),
                chat_id, borrower_id, lender_id,
                amount, time.time(), target_debt_key,
            )
            invalidate_user_cache(chat_id, borrower_id)
            invalidate_user_cache(chat_id, lender_id)
            if res["is_bank_debt"]:
                invalidate_bank_cache(chat_id, lender_id)

        repay_amount = res["repay_amount"]
        discount = res["discount"]
        rating_msg = res["rating_msg"]
        remaining_debt = res["remaining_debt"]
        commission = res["banker_commission"]

        discount_msg = (
            f"\n🎁 <i>Скидка за досрочное погашение: -{discount:,} сыр.</i>"
            if discount > 0 else ""
        )
        commission_msg = (
            f"\n💼 <i>Комиссия банкира: {commission:,} сыр.</i>"
            if commission > 0 else ""
        )
        status_msg = "\n🎉 <b>Долг полностью закрыт!</b>" if res["fully_repaid"] else ""

        await message.answer(
            f"✅ Ты вернул <b>{repay_amount:,}</b> сыроежек кредитору."
            f"{discount_msg}{commission_msg}\n"
            f"Остаток долга: <b>{remaining_debt:,}</b> сыроежек.{rating_msg}{status_msg}"
        )

        # --- Логирование ---
        lender_data = await get_user_data(chat_id, lender_id)
        await safe_log_loan(
            action_type="repay",
            chat_id=chat_id,
            chat_title=message.chat.title or "Unknown",
            lender_id=lender_id,
            lender_name=lender_data.get("full_name")
            or message.reply_to_message.from_user.full_name or "Unknown",
            lender_username=lender_data.get("username")
            or message.reply_to_message.from_user.username or "",
            borrower_id=borrower_id,
            borrower_name=borrower_data.get("full_name")
            or message.from_user.full_name or "Unknown",
            borrower_username=borrower_data.get("username")
            or message.from_user.username or "",
            amount=repay_amount,
            total_debt=remaining_debt,
            message_link=await get_message_link(message),
        )

    except ValueError as ve:
        await message.answer(f"❌ Ошибка: {ve}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка в cmd_repay: %s", exc)
        await message.answer("❌ Произошла ошибка при выплате кредита.")


def _find_debt_key(debts: Dict[str, Any], lender_id: int) -> Optional[str]:
    """
    Ищет подходящий ключ долга для указанного кредитора.

    Сначала ищет банковский долг (любой давности), затем долг игроку.
    Среди нескольких банковских долгов выбирает ближайший к просрочке (минимальная due_date).
    """
    str_lender_player = str(lender_id)
    bank_prefix = f"{LoanConfig.BANK_DEBT_PREFIX}{lender_id}_"

    bank_candidates: List[Tuple[int, str]] = []
    for k, v in debts.items():
        if k.startswith(bank_prefix) and v > 0:
            parsed = parse_bank_debt_key(k)
            due = parsed["due_date"] if parsed else 0
            bank_candidates.append((due, k))

    if bank_candidates:
        # Сортируем по сроку — закрываем самый «горящий» долг первым.
        bank_candidates.sort(key=lambda x: x[0])
        return bank_candidates[0][1]

    if str_lender_player in debts and debts[str_lender_player] > 0:
        return str_lender_player

    return None


# ===========================================================================
#  ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ (новый функционал)
# ===========================================================================
@router.message(F.text.lower().startswith("мои долги") | F.text.lower().startswith("/debts"))
async def cmd_my_debts(message: types.Message):
    """Показывает список всех долгов пользователя."""
    chat_id = message.chat.id
    user_id = message.from_user.id

    user_data = await get_user_data(chat_id, user_id)
    debts = user_data.get("debts") or {}

    active_debts = {k: v for k, v in debts.items() if v > 0}
    if not active_debts:
        return await message.answer("✨ У тебя нет долгов. Чистая кредитная история!")

    current = now_ts()
    lines: List[str] = ["📋 <b>Твои долги:</b>\n"]
    total = 0
    overdue_count = 0

    for idx, (key, amount) in enumerate(active_debts.items(), start=1):
        total += int(amount)
        parsed = parse_bank_debt_key(key) if key.startswith(LoanConfig.BANK_DEBT_PREFIX) else None
        if parsed:
            due = parsed["due_date"]
            if is_overdue(due, current):
                overdue_count += 1
                time_str = "⚠️ <b>ПРОСРОЧЕНО</b>"
            else:
                time_str = f"осталось {humanize_seconds(due - current)}"
            lines.append(
                f"{idx}. 🏦 Банк (кредитор <code>{parsed['lender_id']}</code>): "
                f"<b>{int(amount):,}</b> сыр. — {time_str}"
            )
        else:
            lines.append(
                f"{idx}. 👤 Игрок <code>{key}</code>: <b>{int(amount):,}</b> сыр."
            )

    lines.append(f"\n💵 <b>Всего долгов:</b> {total:,} сыроежек.")
    if overdue_count:
        lines.append(f"⚠️ <b>Просрочено долгов:</b> {overdue_count}")

    score = get_credit_score(user_data)
    lines.append(f"📊 <b>Кредитный рейтинг:</b> {credit_score_label(score)} ({score})")

    await message.answer("\n".join(lines))


@router.message(F.text.lower().startswith("рейтинг") | F.text.lower().startswith("/score"))
async def cmd_credit_score(message: types.Message):
    """Показывает кредитный рейтинг (свой или того, на кого реплай)."""
    chat_id = message.chat.id

    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    else:
        target = message.from_user

    user_data = await get_user_data(chat_id, target.id)
    score = get_credit_score(user_data)

    debts = user_data.get("debts") or {}
    active_debts = sum(int(v) for v in debts.values() if v > 0)

    await message.answer(
        f"📊 <b>Кредитный рейтинг игрока {escape_html(target.full_name)}</b>\n\n"
        f"Рейтинг: {credit_score_label(score)} — <b>{score}</b> "
        f"(из {LoanConfig.MAX_CREDIT_SCORE})\n"
        f"Активных долгов: <b>{active_debts:,}</b> сыроежек.\n\n"
        f"<i>Своевременно погашайте кредиты, чтобы повышать рейтинг!</i>"
    )


@router.message(F.text.lower().startswith("калькулятор") | F.text.lower().startswith("/calc"))
async def cmd_loan_calculator(message: types.Message):
    """
    Кредитный калькулятор.

    Использование: калькулятор <сумма> <%> [срок_дней]
    """
    args = message.text.split()
    if len(args) < 3:
        return await message.answer(
            "🧮 <b>Кредитный калькулятор</b>\n\n"
            "Использование: <code>калькулятор [сумма] [%] [срок]</code>\n"
            "Пример: <code>калькулятор 1000 15 14</code>"
        )

    try:
        amount = int(args[1])
        percent = int(args[2])
        term_days = int(args[3]) if len(args) >= 4 else 0
    except ValueError:
        return await message.answer("Сумма, процент и срок должны быть числами.")

    if amount <= 0 or percent < 0:
        return await message.answer("Некорректные значения для расчёта.")

    total = calc_total_debt(amount, percent)
    interest = calc_interest(amount, percent)

    # Возможная скидка за досрочку.
    early_discount = max(0, int(interest * LoanConfig.EARLY_REPAY_DISCOUNT_RATE))
    total_with_discount = total - early_discount

    term_line = f"⏳ Срок: <b>{term_days}</b> дн.\n" if term_days else ""

    await message.answer(
        f"🧮 <b>Расчёт кредита</b>\n\n"
        f"💰 Тело: <b>{amount:,}</b> сыроежек\n"
        f"📊 Ставка: <b>{percent}%</b>\n"
        f"{term_line}"
        f"➕ Переплата: <b>{interest:,}</b>\n"
        f"💵 Итого к возврату: <b>{total:,}</b>\n\n"
        f"🎁 При досрочном погашении:\n"
        f"   Скидка: <b>{early_discount:,}</b>\n"
        f"   К возврату: <b>{total_with_discount:,}</b>"
    )


@router.message(F.text.lower().startswith("выданные кредиты") | F.text.lower().startswith("/issued"))
async def cmd_issued_loans(message: types.Message):
    """
    Показывает банкиру информацию о его банке и капитале.

    (Полную историю выдач при необходимости можно подтянуть из log_system.)
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    if not data.get("is_banker", False):
        return await message.answer("❌ Эта команда доступна только банкирам.")

    bank_data = await get_bank_info(chat_id, user_id)
    if not bank_data:
        return await message.answer(
            "❌ У вас ещё не создан банк. Создайте его командой "
            "<code>создать банк [Название]</code>."
        )

    bank_name = escape_html(bank_data.get("name", "Неизвестный Банк"))
    capital = int(bank_data.get("capital", 0) or 0)

    await message.answer(
        f"🏦 <b>Банк «{bank_name}»</b>\n\n"
        f"💰 Капитал: <b>{capital:,}</b> сыроежек\n\n"
        f"<i>Используйте</i> <code>кредит [сумма] [%] [срок]</code> "
        f"<i>реплаем на игрока, чтобы выдать кредит.</i>"
    )


@router.message(F.text.lower() == "помощь по кредитам")
async def cmd_loan_help(message: types.Message):
    """Справка по всем командам кредитной системы."""
    await message.answer(
        "📚 <b>Справка по кредитной системе</b>\n\n"
        "<b>Для банкиров:</b>\n"
        "• <code>кредит [сумма] [%] [срок] [ID_поручителя?]</code> — выдать кредит (реплаем)\n"
        "• <code>выданные кредиты</code> — информация о вашем банке\n\n"
        "<b>Для заёмщиков:</b>\n"
        "• <code>выплатить [сумма]</code> — погасить долг (реплаем на кредитора)\n"
        "• <code>мои долги</code> — список ваших долгов\n"
        "• <code>рейтинг</code> — ваш кредитный рейтинг\n\n"
        "<b>Общее:</b>\n"
        "• <code>калькулятор [сумма] [%] [срок]</code> — расчёт кредита\n\n"
        f"💡 <i>Досрочное погашение даёт скидку "
        f"{int(LoanConfig.EARLY_REPAY_DISCOUNT_RATE * 100)}% от процентов "
        f"и повышает рейтинг!</i>"
    )