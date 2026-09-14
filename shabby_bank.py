import os
import time
import random
import logging
from typing import Dict, Any, Tuple, Optional
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html

logger = logging.getLogger(__name__)

# Пользователи с хардкорным банком на Алмазной 33
SHABBY_BANKER_IDS = {6896326008, 7081184095}

# Путь к изображению обрыганного здания
SHABBY_BANK_IMG_PATH = os.path.join(os.path.dirname(__file__), "assets", "shabby_bank.jpg")
try:
    from shabby_bank_asset import ensure_shabby_bank_image
    ensure_shabby_bank_image(SHABBY_BANK_IMG_PATH)
except Exception as _e:
    logger.warning("Could not auto-extract shabby bank image: %s", _e)

# Стоимость ликвидации аварийных ситуаций
COST_EXTINGUISH = 250_000         # Тушение проводки / огнетушитель ОП-5
COST_PATCH_ROOF = 350_000         # Рубероид и фанера для крыши
COST_POISON_RATS = 200_000        # Дихлофос и мышеловки
COST_CALM_BABKI = 150_000         # Валидол, барбариски и чай «Принцесса Нури»
COST_BRIBE_INSPECTOR = 600_000    # Конверт майору Сидоренко (Пожнадзор Алмазной)
COST_PAY_RENT = 500_000           # Суточная аренда ларька местным авторитетам
DAILY_RENT_SECONDS = 86_400       # 24 часа

# Интервал между спонтанными бедствиями
INCIDENT_COOLDOWN = 600           # 10 минут

def is_shabby_bank(bank_data: Optional[Dict[str, Any]], banker_id: Optional[int] = None) -> bool:
    """Проверяет, является ли банк хардкорным банком на Алмазной 33."""
    if banker_id is not None and int(banker_id) in SHABBY_BANKER_IDS:
        return True
    if not bank_data:
        return False
    b_id = bank_data.get("banker_id")
    if b_id and int(b_id) in SHABBY_BANKER_IDS:
        return True
    co_bankers = [int(x) for x in bank_data.get("co_bankers", []) if str(x).isdigit()]
    if any(cb in SHABBY_BANKER_IDS for cb in co_bankers):
        return True
    if banker_id is not None and int(banker_id) in co_bankers:
        return True
    return bool(bank_data.get("is_shabby") or bank_data.get("shabby_hardcore"))

def get_default_shabby_fields() -> Dict[str, Any]:
    """Возвращает базовые параметры износа для хардкорного банка."""
    now = int(time.time())
    return {
        "is_shabby": True,
        "shabby_hardcore": True,
        "durability": 35,             # Прочность здания (0-100%)
        "fire_risk": 65,              # Риск пожара (0-100%)
        "rats_infestation": 55,       # Уровень крыс (0-100%)
        "babki_queue": 75,            # Очередь орущих бабок (0-100%)
        "inspection_anger": 50,       # Гнев пожинспектора и СЭС (0-100%)
        "power_grid": True,           # Электроэнергия (True - включено, False - выбило пробки)
        "rent_paid_until": now + DAILY_RENT_SECONDS, # Оплаченная аренда
        "last_incident_time": now,
        "total_disasters_survived": 0
    }

def _render_bar(value: int, max_value: int = 100, length: int = 8) -> str:
    """Генерирует текстовую полосу прогресса."""
    val = max(0, min(value, max_value))
    filled = int(round((val / max_value) * length))
    return "▓" * filled + "░" * (length - filled)

def check_and_apply_shabby_decay(bank_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Пассивный износ со временем и спонтанные бедствия.
    Возвращает обновленные данные банка и текст ЧП, если оно произошло.
    """
    now = int(time.time())
    last_check = bank_data.get("last_incident_time", now)
    elapsed = now - last_check

    updates = {}
    incident_text = None

    # Постепенный износ от времени (каждые 15 минут)
    durability = int(bank_data.get("durability", 35))
    fire_risk = int(bank_data.get("fire_risk", 65))
    rats = int(bank_data.get("rats_infestation", 55))
    babki = int(bank_data.get("babki_queue", 75))
    anger = int(bank_data.get("inspection_anger", 50))
    capital = int(bank_data.get("capital", 0))

    if elapsed >= INCIDENT_COOLDOWN:
        updates["last_incident_time"] = now

        # Естественный прирост энтропии в сарае
        durability = max(0, durability - random.randint(3, 8))
        fire_risk = min(100, fire_risk + random.randint(4, 10))
        rats = min(100, rats + random.randint(3, 8))
        babki = min(100, babki + random.randint(5, 12))
        anger = min(100, anger + random.randint(3, 7))

        # Проверка аренды
        rent_until = bank_data.get("rent_paid_until", 0)
        rent_warning = ""
        if now > rent_until:
            rent_penalty = 300_000
            capital = max(0, capital - rent_penalty)
            durability = max(0, durability - 10)
            rent_warning = (
                f"\n⚠️ <b>БРАТКИ С АЛМАЗНОЙ:</b> Срок аренды ларька истек! "
                f"Выбито стекло и вычтено <b>{rent_penalty:,}</b> сыр. штрафа!"
            )

        # Ролл случайного бедствия
        roll = random.random()
        survived = int(bank_data.get("total_disasters_survived", 0))

        if fire_risk >= 60 and roll < 0.35:
            # ПОЖАР НА АЛМАЗНОЙ 33!
            burned = min(capital, random.randint(500_000, 1_800_000))
            capital = max(0, capital - burned)
            durability = max(0, durability - random.randint(10, 20))
            fire_risk = min(100, fire_risk + 15)
            anger = min(100, anger + 25)
            survived += 1
            incident_text = (
                "🚨 <b>ПОЖАР НА АЛМАЗНОЙ 33!</b>\n"
                "<i>«Тише, тише, слышишь крик? Там вроде будто что-то горит...»</i>\n"
                f"🔥 Замкнуло скрутку на крыше! Загорелся рубероид и фанера кассы!\n"
                f"💸 Сгорело <b>{burned:,}</b> сыр. из капитала!\n"
                f"🧱 Прочность здания упала до <b>{durability}%</b>!"
            )
        elif rats >= 60 and roll < 0.65:
            # АТАКА КРЫС
            eaten = min(capital, random.randint(300_000, 900_000))
            capital = max(0, capital - eaten)
            survived += 1
            incident_text = (
                "🐀 <b>НАШЕСТВИЕ КРЫС!</b>\n"
                f"Подвальные крысы Алмазной прогрызли мешок с сыроежками под диваном!\n"
                f"💸 Сожрано <b>{eaten:,}</b> сыр. капитала! Запах стоит на всю улицу."
            )
        elif anger >= 75 and roll < 0.85:
            # РЕЙД ПОЖНАДЗОРА
            fine = min(capital, random.randint(800_000, 2_000_000))
            capital = max(0, capital - fine)
            anger = 40  # Взяли штраф, временно успокоились
            survived += 1
            incident_text = (
                "🚒 <b>ВНЕЗАПНАЯ ПРОВЕРКА ПОЖНАДЗОРА!</b>\n"
                "Майор Сидоренко с Алмазной 33 обнаружил скрутки на изоленте и отсутствие огнетушителя!\n"
                f"💸 Выписан штраф <b>{fine:,}</b> сыр.! Нарушения требуют срочного устранения!"
            )
        elif durability <= 20 and roll < 0.95:
            # ОБВАЛ КРЫШИ
            repair_hit = min(capital, 400_000)
            capital = max(0, capital - repair_hit)
            durability = max(0, durability - 10)
            incident_text = (
                "🌧 <b>ОБВАЛ КРЫШИ И ПОТОП!</b>\n"
                "Сгнивший шифер не выдержал дождя и рухнул на стол кассира!\n"
                f"💸 Залиты кассовые книги, ущерб: <b>{repair_hit:,}</b> сыр.!"
            )
        elif random.random() < 0.20:
            # ВЫБИЛО ПРОБКИ
            updates["power_grid"] = False
            incident_text = (
                "⚡ <b>КОРОТКОЕ ЗАМЫКАНИЕ!</b>\n"
                "Искры со столба посыпались на ларек! Выбило главный рубильник.\n"
                "🔌 Касса и терминалы обесточены! Нужно дернуть рубильник в щитке."
            )

        if rent_warning:
            incident_text = (incident_text + "\n" + rent_warning) if incident_text else rent_warning

        updates.update({
            "durability": durability,
            "fire_risk": fire_risk,
            "rats_infestation": rats,
            "babki_queue": babki,
            "inspection_anger": anger,
            "capital": capital,
            "total_disasters_survived": survived,
        })

    return updates, incident_text

def format_shabby_bank_stats(
    chat_id: int,
    user_id: int,
    bank_data: Dict[str, Any],
    total_depositors: int,
    total_deposits: int,
    total_loans_given: int,
    overdue_loans: int,
    audit_warning: str = "",
    incident_text: Optional[str] = None
) -> str:
    """Форматирует главную панель хардкорного банка на Алмазной 33."""
    capital = bank_data.get("capital", 0)
    rate = bank_data.get("deposit_rate", 13.0)
    name = bank_data.get("name", "🏚 Госбанк на Алмазной 33")

    durability = int(bank_data.get("durability", 35))
    fire_risk = int(bank_data.get("fire_risk", 65))
    rats = int(bank_data.get("rats_infestation", 55))
    babki = int(bank_data.get("babki_queue", 75))
    anger = int(bank_data.get("inspection_anger", 50))
    power = bank_data.get("power_grid", True)
    survived = bank_data.get("total_disasters_survived", 0)

    now = int(time.time())
    rent_until = bank_data.get("rent_paid_until", 0)
    rent_hours = max(0, int((rent_until - now) // 3600))
    rent_status = f"🟢 Оплачено (осталось {rent_hours} ч.)" if now < rent_until else "🔴 ПРОСРОЧЕНО (Братки выбивают долг!)"

    power_status = "🟢 220V (Исправен)" if power else "🔴 ОБЕСТОЧЕН (Выбило пробки!)"

    # Критические статусы
    warnings = []
    if durability <= 15:
        warnings.append("🚨 <b>КАТАСТРОФА:</b> Здание вот-вот рухнет! Касса под угрозой обвала!")
    if fire_risk >= 75:
        warnings.append("🔥 <b>КРИТИЧЕСКИЙ РИСК:</b> Проводка на крыше дымит открытым пламенем!")
    if babki >= 85:
        warnings.append("👵 <b>БУНТ ОЧЕРЕДИ:</b> Бабки заблокировали вход телами! Вклады заблокированы!")
    if anger >= 80:
        warnings.append("🚒 <b>ПОЖНАДЗОР:</b> Пожарный инспектор на пороге с протоколом закрытия!")
    if not power:
        warnings.append("⚡ <b>НЕТ СВЕТА:</b> Компьютеры погасли, операции заморожены!")

    status_block = "\n".join(warnings) + "\n" if warnings else ""
    inc_block = f"\n💥 <b>ПОСЛЕДНЕЕ ЧП:</b>\n{incident_text}\n" if incident_text else ""

    co_bankers_names = bank_data.get("co_banker_names", [])
    if co_bankers_names:
        owners_line = f"🏛 <b>Владельцы:</b> {escape_html(bank_data.get('banker_name', '🦖'))} & 🤝 <b>{escape_html(', '.join(co_bankers_names))}</b>\n"
    else:
        owners_line = f"🏛 <b>Владелец:</b> {escape_html(bank_data.get('banker_name', '🦖'))}\n"

    text = (
        f"🏚 <b>{escape_html(name)}</b>\n"
        f"{owners_line}"
        f"<i>«Тише, тише, слышишь крик? Там вроде будто что-то горит... Дом на Алмазной 33...»</i>\n\n"
        f"💰 <b>Капитал банка:</b> {capital:,} сыр.\n"
        f"📈 <b>Ставка:</b> <b>{rate}%</b> в день <i>(макс. % для нищенок 👉👈)</i>\n\n"
        f"🛠 <b>СВОДКА АВАРИЙНОГО СОСТОЯНИЯ:</b>\n"
        f"🧱 Прочность сарая: [{_render_bar(durability)}] <b>{durability}%</b>\n"
        f"🔥 Пожароопасность: [{_render_bar(fire_risk)}] <b>{fire_risk}%</b>\n"
        f"🐀 Заражение крысами: [{_render_bar(rats)}] <b>{rats}%</b>\n"
        f"👵 Очередь бабок: [{_render_bar(babki)}] <b>{babki}%</b>\n"
        f"👮 Гнев Пожнадзора: [{_render_bar(anger)}] <b>{anger}%</b>\n"
        f"⚡ Электрощиток: {power_status}\n"
        f"📜 Аренда земли: {rent_status}\n"
        f"🏆 Пережито ЧП: <b>{survived}</b>\n\n"
        f"👥 <b>Вкладчиков:</b> {total_depositors} | 🏦 <b>Вклады:</b> {total_deposits:,} сыр.\n"
        f"🤝 <b>Кредитов выдано:</b> {total_loans_given:,} сыр.\n"
        f"{inc_block}"
        f"{status_block}"
        f"{audit_warning}"
    )
    return text

def get_shabby_bank_kb(banker_id: int, bank_data: Dict[str, Any]):
    """Формирует клавиатуру управления хардкорным банком на Алмазной 33."""
    builder = InlineKeyboardBuilder()

    power = bank_data.get("power_grid", True)
    babki = int(bank_data.get("babki_queue", 75))
    fire = int(bank_data.get("fire_risk", 65))
    durability = int(bank_data.get("durability", 35))
    rats = int(bank_data.get("rats_infestation", 55))
    anger = int(bank_data.get("inspection_anger", 50))

    # Срочные аварийные кнопки первыми
    if not power:
        builder.button(text="⚡ Врубить рубильник", callback_data=f"bshabby_power_{banker_id}")
    if fire >= 50:
        builder.button(text=f"🧯 Тушить ({COST_EXTINGUISH//1000}k)", callback_data=f"bshabby_extinguish_{banker_id}")
    if babki >= 60:
        builder.button(text=f"👵 Успокоить бабок ({COST_CALM_BABKI//1000}k)", callback_data=f"bshabby_calm_{banker_id}")
    if durability <= 60:
        builder.button(text=f"🧱 Латать крышу ({COST_PATCH_ROOF//1000}k)", callback_data=f"bshabby_patch_{banker_id}")
    if rats >= 50:
        builder.button(text=f"🐀 Травить крыс ({COST_POISON_RATS//1000}k)", callback_data=f"bshabby_poison_{banker_id}")
    if anger >= 50:
        builder.button(text=f"💸 Взятка пожнадзору ({COST_BRIBE_INSPECTOR//1000}k)", callback_data=f"bshabby_bribe_{banker_id}")

    # Аренда земли
    now = int(time.time())
    if now >= bank_data.get("rent_paid_until", 0):
        builder.button(text=f"📜 Оплатить аренду ({COST_PAY_RENT//1000}k)", callback_data=f"bshabby_rent_{banker_id}")

    # Стандартные банковские вкладки
    builder.button(text="🔄 Обновить", callback_data=f"bstat_main_{banker_id}")
    builder.button(text="👥 Вкладчики", callback_data=f"bstat_deps_{banker_id}")
    builder.button(text="🤝 Должники", callback_data=f"bstat_loans_{banker_id}")
    builder.button(text="⚙️ Настройки", callback_data=f"bstat_settings_{banker_id}")
    builder.button(text="⬆️ Улучшения", callback_data=f"bstat_upgrades_{banker_id}")
    builder.button(text="💼 Схемы", callback_data=f"bstat_schemes_{banker_id}")

    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()

async def execute_shabby_repair(
    chat_id: int,
    banker_id: int,
    action: str,
    bank_data: Dict[str, Any]
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Выполняет аварийный ремонт/действие банкира.
    Возвращает (успех, сообщение, словарь_обновлений).
    """
    capital = int(bank_data.get("capital", 0))

    if action == "extinguish":
        if capital < COST_EXTINGUISH:
            return False, f"❌ Нужно {COST_EXTINGUISH:,} сыр. в капитале для покупки огнетушителей и изоленты!", {}
        new_capital = capital - COST_EXTINGUISH
        fire = max(5, int(bank_data.get("fire_risk", 65)) - random.randint(35, 55))
        return True, f"🧯 <b>Огнетушитель сработал!</b>\nПроводка перемотана синей изолентой. Риск пожара снижен до <b>{fire}%</b>!", {
            "capital": new_capital,
            "fire_risk": fire
        }

    elif action == "patch":
        if capital < COST_PATCH_ROOF:
            return False, f"❌ Нужно {COST_PATCH_ROOF:,} сыр. в капитале для покупки рубероида и саморезов!", {}
        new_capital = capital - COST_PATCH_ROOF
        durability = min(100, int(bank_data.get("durability", 35)) + random.randint(25, 40))
        return True, f"🧱 <b>Крыша залатана!</b>\nРубероид прибит кирпичами, щели запенены. Прочность сарая: <b>{durability}%</b>!", {
            "capital": new_capital,
            "durability": durability
        }

    elif action == "poison":
        if capital < COST_POISON_RATS:
            return False, f"❌ Нужно {COST_POISON_RATS:,} сыр. в капитале на дихлофос и приманки!", {}
        new_capital = capital - COST_POISON_RATS
        rats = max(5, int(bank_data.get("rats_infestation", 55)) - random.randint(35, 60))
        return True, f"☠️ <b>Газовая атака завершена!</b>\nКрысы временно бежали на соседнюю помойку. Уровень крыс снижен до <b>{rats}%</b>!", {
            "capital": new_capital,
            "rats_infestation": rats
        }

    elif action == "calm":
        if capital < COST_CALM_BABKI:
            return False, f"❌ Нужно {COST_CALM_BABKI:,} сыр. в капитале на корвалол, валидол и барбариски!", {}
        new_capital = capital - COST_CALM_BABKI
        babki = max(10, int(bank_data.get("babki_queue", 75)) - random.randint(35, 55))
        return True, f"🍬 <b>Бабки подкуплены чаем и конфетами!</b>\nОчередь поутихла и обсуждает цены на пшено. Напряжение упало до <b>{babki}%</b>!", {
            "capital": new_capital,
            "babki_queue": babki
        }

    elif action == "bribe":
        if capital < COST_BRIBE_INSPECTOR:
            return False, f"❌ Нужно {COST_BRIBE_INSPECTOR:,} сыр. в капитале для конверта майору Сидоренко!", {}
        new_capital = capital - COST_BRIBE_INSPECTOR
        return True, "💸 <b>Майор Сидоренко взял пухлый конверт!</b>\n«Нарушений не выявлено, только лампочку вкрутите». Гнев Пожнадзора сброшен в 0!", {
            "capital": new_capital,
            "inspection_anger": 0
        }

    elif action == "rent":
        if capital < COST_PAY_RENT:
            return False, f"❌ Нужно {COST_PAY_RENT:,} сыр. в капитале на оплату аренды ларька!", {}
        new_capital = capital - COST_PAY_RENT
        now = int(time.time())
        rent_until = max(now, bank_data.get("rent_paid_until", 0)) + DAILY_RENT_SECONDS
        return True, "📜 <b>Аренда земли на Алмазной 33 продлена на 24 часа!</b>\nМестные авторитеты оставили ларек в покое.", {
            "capital": new_capital,
            "rent_paid_until": rent_until
        }

    elif action == "power":
        # Рубильник на столбе
        chance = 0.75
        if random.random() < chance:
            return True, "⚡ <b>ЩЕЛК!</b>\nВы натянули резиновые перчатки и врубили рубильник! В сарае зажегся свет, терминалы ожили!", {
                "power_grid": True
            }
        else:
            shock = min(capital, 100_000)
            return True, f"⚡ <b>ЕБ... ТОКОМ!</b>\nВас тряхануло 220 вольтами! Сгорел удлинитель (-{shock:,} сыр.), но свет так и не зажегся. Попробуйте снова!", {
                "capital": max(0, capital - shock),
                "power_grid": False
            }

    return False, "Неизвестное действие.", {}
