import os
import time
import random
import logging
from typing import Dict, Any, Tuple, Optional
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html

logger = logging.getLogger(__name__)

# Пользователи с VIP-банком нефтяных магнатов в Республике Вадия («Диктатор», 2012)
SHABBY_BANKER_IDS = {6896326008, 7081184095}

# Путь к изображению здания банка (высотка Вадия VIP-Банк / Aladeen Oil Tower)
SHABBY_BANK_IMG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", "shabby_bank.jpg"))
try:
    from shabby_bank_asset import ensure_shabby_bank_image
    ensure_shabby_bank_image(SHABBY_BANK_IMG_PATH)
except Exception as _e:
    logger.warning("Could not auto-extract wadiya bank image: %s", _e)


def get_shabby_bank_input_file():
    """Возвращает InputFile для гарантированной отправки фото высотки банка в Вадии."""
    try:
        from shabby_bank_asset import ensure_shabby_bank_image
        ensure_shabby_bank_image(SHABBY_BANK_IMG_PATH)
    except Exception:
        pass

    if os.path.exists(SHABBY_BANK_IMG_PATH):
        try:
            from aiogram.types import FSInputFile
            return FSInputFile(SHABBY_BANK_IMG_PATH)
        except Exception as e:
            logger.warning("Could not load FSInputFile for wadiya bank: %s", e)

    try:
        from shabby_bank_asset import SHABBY_BANK_B64
        from aiogram.types import BufferedInputFile
        import base64
        return BufferedInputFile(base64.b64decode(SHABBY_BANK_B64), filename="shabby_bank.jpg")
    except Exception as e:
        logger.error("Could not build buffered wadiya bank input file: %s", e)
        return None


# Доля капитала за переезд из Табулистана в Вадию и постройку высотки (40%)
WADIYA_RELOCATION_FEE_RATE = 0.40

# Стоимость обслуживания высотки и приколов нефтяных магнатов Вадии
COST_EXTINGUISH = 45_000         # Охлаждение нефтекачек и сырной центрифуги в пентхаусе
COST_PATCH_ROOF = 55_000         # Золочение фасада и заточка шпиля высотки
COST_POISON_RATS = 35_000        # Выдворение контрабандных верблюдов и коз из лобби
COST_CALM_BABKI = 30_000         # Золотой раф и VIP-талоны шейхам и жёнам в очереди
COST_BRIBE_INSPECTOR = 90_000    # Золотой Гелик для Адмирала-Генерала Аладина
COST_CUSTOMS_DEAL = 80_000       # Занести инспекторам ООН / ОПЭК за «мирный сыр»
COST_LUX_CLEANING = 40_000       # Полировка золотого шпиля и мраморного подиума
COST_FEAST = 50_000              # Саммит ОПЭК на вертолётной площадке 88-го этажа
COST_FOREX_BET = 40_000          # Ставка на нефтебирже Вадии (ВДР)
COST_PAY_RENT = 75_000           # Налог на нефтяную концессию Вадии (24 часа)

DAILY_RENT_SECONDS = 86_400      # 24 часа
EARLY_RENT_PAY_SECONDS = 86_400  # Досрочное продление аренды (за 24 часа до окончания)
SMUGGLE_COOLDOWN = 1200          # Кулдаун на отгрузку танкера нефти ОПЭК (20 минут)
FOREX_COOLDOWN = 1500            # Кулдаун на нефтебиржу ВДР (25 минут)
ALADEEN_COOLDOWN = 900           # Кулдаун на вердикт «Аладин или Аладин?» (15 минут)

# Интервал между спонтанными событиями
INCIDENT_COOLDOWN = 900          # 15 минут

# Бегущая строка Нацбанка Вадии (меняется раз в 30 минут)
WADIYA_TICKERS = [
    "1 сыр. = 911.00 ВДР 📈 (Слова «рост» и «обвал» переименованы в «Аладин»)",
    "1 баррель = 420 сыр. 🛢 (Сырные вышки качают чёрное золото прямо из-под башни)",
    "1 сыр. = 777.00 ВДР 🚀 (Шпиль высотки признан 100% острым по ГОСТу Аладина)",
    "1 сыр. = 140.00 ВДР 🐪 (На Олимпиаде Вадии победил Аладин со стартовым пистолетом)",
    "1 сыр. = 500.00 ВДР ☢️ (Мирный сырный уран обогащён для VIP-тостеров Вадии)",
    "1 сыр. = 333.00 ВДР 👑 (Понедельники официально отменены указом Адмирала-Генерала)",
]


def _get_wadiya_ticker(now: int) -> str:
    idx = (now // 1800) % len(WADIYA_TICKERS)
    return WADIYA_TICKERS[idx]


def is_shabby_bank(bank_data: Optional[Dict[str, Any]], banker_id: Optional[int] = None) -> bool:
    """Проверяет, является ли банк VIP-высоткой нефтяных магнатов в Вадии."""
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
    return bool(bank_data.get("is_shabby") or bank_data.get("shabby_hardcore") or bank_data.get("wadiya_relocated"))


def get_default_shabby_fields() -> Dict[str, Any]:
    """Возвращает базовые параметры новой высотки нефтяных магнатов в Вадии."""
    now = int(time.time())
    return {
        "is_shabby": True,
        "shabby_hardcore": True,
        "wadiya_relocated": True,
        "durability": 100,            # Золотой фасад и острота шпиля (0-100%)
        "fire_risk": 15,              # Давление нефтекачек и сырной центрифуги (0-100%)
        "rats_infestation": 10,       # Набеги верблюдов и коз Аладина в лобби (0-100%)
        "babki_queue": 20,            # Очередь нефтяных шейхов и VIP-гостей (0-100%)
        "inspection_anger": 15,       # Капризы Адмирала-Генерала Аладина (0-100%)
        "border_heat": 15,            # Внимание инспекторов ООН / санкции ОПЭК (0-100%)
        "power_grid": True,           # Золотой генератор башни (True - 380V GOLD, False - блэкаут)
        "rent_paid_until": now + DAILY_RENT_SECONDS,
        "last_incident_time": now,
        "last_smuggle_time": 0,
        "last_forex_time": 0,
        "last_aladeen_time": 0,
        "smuggle_runs": 0,
        "oil_barrels": 1000,
        "total_disasters_survived": 0,
    }


def _render_bar(value: int, max_value: int = 100, length: int = 5) -> str:
    """Генерирует текстовую полосу прогресса."""
    val = max(0, min(value, max_value))
    filled = int(round((val / max_value) * length))
    return "▓" * filled + "░" * (length - filled)


def format_wadiya_relocation_announcement(bank_data: Dict[str, Any], relocation_fee: int) -> str:
    """Формирует публичное объявление в чат о переезде банка в Республику Вадия."""
    bank_name = escape_html(bank_data.get("name", "Доисторический"))
    owner = escape_html(bank_data.get("banker_name", "Банкир"))
    co_names = bank_data.get("co_banker_names", []) or []
    owners = f"{owner} & {', '.join(escape_html(n) for n in co_names)}" if co_names else owner
    new_capital = int(bank_data.get("capital", 0))

    return (
        f"🚨🛢 <b>ЭКСТРЕННЫЙ ВЫПУСК НОВОСТЕЙ ВАДИИ!</b> 🛢🚨\n\n"
        f"🏛 Банк <b>«{bank_name}»</b> (👑 {owners}) накопил столько сыроежек, что в подвале прорвало чёрное золото — "
        f"они официально стали <b>НЕФТЯНЫМИ МАГНАТАМИ!</b>\n\n"
        f"🐪 Прощай, пыльный КПП Табулистан! Собрав чемоданы пармезана, боссы выкупили за <b>40% капитала</b> "
        f"(<code>-{relocation_fee:,}</code> сыр.) землю прямо у дворца Адмирала-Генерала Аладина и отстроили в Вадии "
        f"новую золотую высотку <b>«ВАДИЯ VIP-БАНК • ALADEEN OIL TOWER»</b> с максимально острым шпилем!\n\n"
        f"💼 Остаток в казне после стройки: <b>{new_capital:,}</b> сыр.\n"
        f"🛢 Стартовый резерв: <b>1,000</b> барр. нефти | 📈 Вклады работают в VIP-режиме\n\n"
        f"<i>«Пусть завистники в Табулистане кусают табуле. Этот переезд официально признан... АЛАДИН!»</i> ☢️😀"
    )


def check_and_apply_shabby_decay(bank_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Проверяет одноразовый переезд в Вадию (за 40% капитала) и применяет события высотки.
    Возвращает обновленные данные банка и текст события, если оно произошло.
    """
    now = int(time.time())
    updates: Dict[str, Any] = {}
    capital = int(bank_data.get("capital", 0))

    # Одноразовая миграция из Табулистана в Республику Вадия (40% от капитала банка)
    if not bank_data.get("wadiya_relocated"):
        relocation_fee = int(capital * WADIYA_RELOCATION_FEE_RATE)
        capital = max(0, capital - relocation_fee)
        oil_barrels = int(bank_data.get("oil_barrels", 0)) + 1000
        rent_until = max(int(bank_data.get("rent_paid_until", 0) or 0), now + DAILY_RENT_SECONDS)

        updates = {
            "is_shabby": True,
            "shabby_hardcore": True,
            "wadiya_relocated": True,
            "wadiya_relocation_paid": relocation_fee,
            "wadiya_relocated_at": now,
            "capital": capital,
            "durability": 100,
            "fire_risk": 10,
            "rats_infestation": 5,
            "babki_queue": 15,
            "inspection_anger": 10,
            "border_heat": 10,
            "power_grid": True,
            "rent_paid_until": rent_until,
            "last_incident_time": now,
            "oil_barrels": oil_barrels,
        }
        relocation_text = (
            "🛢✈️ <b>ПЕРЕЕЗД В РЕСПУБЛИКУ ВАДИЯ!</b>\n"
            "Из-за колоссальных залежей сыроежек вы стали <b>нефтяными магнатами</b>!\n"
            f"💸 За <b>40% от капитала банка</b> (<code>-{relocation_fee:,}</code> сыр.) вы выкупили золотой участок у дворца Аладина и построили небоскрёб <b>Aladeen Oil Tower</b>! (+1,000 🛢)"
        )
        return updates, relocation_text

    last_check = bank_data.get("last_incident_time", now)
    elapsed = now - last_check

    incident_text = None

    durability = int(bank_data.get("durability", 100))
    fire_risk = int(bank_data.get("fire_risk", 15))
    rats = int(bank_data.get("rats_infestation", 10))
    babki = int(bank_data.get("babki_queue", 20))
    anger = int(bank_data.get("inspection_anger", 15))
    border_heat = int(bank_data.get("border_heat", 15))
    oil_barrels = int(bank_data.get("oil_barrels", 1000))

    if elapsed >= INCIDENT_COOLDOWN:
        updates["last_incident_time"] = now

        # Пассивная добыча нефти качалками у подножия высотки
        oil_barrels += random.randint(80, 220)

        durability = max(0, durability - random.randint(2, 5))
        fire_risk = min(100, fire_risk + random.randint(3, 7))
        rats = min(100, rats + random.randint(2, 6))
        babki = min(100, babki + random.randint(4, 9))
        anger = min(100, anger + random.randint(2, 6))
        border_heat = min(100, border_heat + random.randint(2, 5))

        # Проверка налога на нефтяную концессию Вадии
        rent_until = bank_data.get("rent_paid_until", 0)
        rent_warning = ""
        if now > rent_until:
            rent_penalty = 75_000
            capital = max(0, capital - rent_penalty)
            durability = max(0, durability - 5)
            rent_warning = (
                f"\n⚠️ <b>МИНИСТЕРСТВО НЕФТИ ВАДИИ:</b> Просрочена концессия участка под башней! "
                f"Гвардия Аладина опечатала шлагбаум и списала <b>{rent_penalty:,}</b> сыр. штрафа!"
            )

        roll = random.random()
        survived = int(bank_data.get("total_disasters_survived", 0))

        if border_heat >= 70 and roll < 0.22:
            confiscated = min(capital, random.randint(80_000, 200_000))
            capital = max(0, capital - confiscated)
            border_heat = 25
            survived += 1
            incident_text = (
                "🕵️ <b>НАЛЁТ ИНСПЕКТОРОВ ООН НА НЕФТЕХРАНИЛИЩЕ!</b>\n"
                "Комиссия с дозиметрами вломилась на 88-й этаж проверять, зачем вашим сыроежкам центрифуги с острым верхом!\n"
                f"💸 Откупились золотыми часами: <b>{confiscated:,}</b> сыр.!"
            )
        elif fire_risk >= 65 and roll < 0.40:
            burned = min(capital, random.randint(60_000, 160_000))
            capital = max(0, capital - burned)
            durability = max(0, durability - random.randint(4, 9))
            fire_risk = min(100, fire_risk + 10)
            anger = min(100, anger + 10)
            survived += 1
            incident_text = (
                "🔥 <b>ПЕРЕГРЕВ «МИРНОЙ СЫРНОЙ ЦЕНТРИФУГИ»!</b>\n"
                "На техническом этаже закипела нефть вперемешку с пармезаном — закоптило мраморный атриум!\n"
                f"💸 Ущерб оборудованию: <b>{burned:,}</b> сыр. | 🏢 Фасад: <b>{durability}%</b>"
            )
        elif rats >= 60 and roll < 0.56:
            stolen = min(capital, random.randint(35_000, 95_000))
            capital = max(0, capital - stolen)
            survived += 1
            incident_text = (
                "🐪 <b>ВЕРБЛЮДЫ И КОЗЫ ПРОРВАЛИСЬ В ЗОЛОТОЙ ЛИФТ!</b>\n"
                "Караван призовых верблюдов Аладина зашёл с парадного входа и сжевал пачку облигаций на ресепшене!\n"
                f"💸 Убыток: <b>{stolen:,}</b> сыр.!"
            )
        elif anger >= 75 and roll < 0.70:
            fine = min(capital, random.randint(90_000, 200_000))
            capital = max(0, capital - fine)
            anger = 30
            survived += 1
            incident_text = (
                "🎖 <b>ВНЕЗАПНЫЙ ВИЗИТ АДМИРАЛА-ГЕНЕРАЛА АЛАДИНА!</b>\n"
                "Аладин вышел из золотого Гелика и прищурился: «Шпиль вашей высотки недостаточно острый! Круглый верх — для лузеров!»\n"
                f"💸 Скинулись на срочную заточку шпиля: <b>{fine:,}</b> сыр.!"
            )
        elif durability <= 20 and roll < 0.78:
            repair_hit = min(capital, random.randint(50_000, 120_000))
            capital = max(0, capital - repair_hit)
            durability = max(0, durability - 8)
            incident_text = (
                "🛢 <b>НЕФТЯНОЙ ФОНТАН В ДЖАКУЗИ ПЕНТХАУСА!</b>\n"
                "Из позолоченного крана вместо шампанского хлынула сырая нефть и залила VIP-стойку!\n"
                f"💸 Залиты купюросчётные машинки, ремонт: <b>{repair_hit:,}</b> сыр.!"
            )
        elif roll < 0.84:
            bonus_oil = random.randint(300, 700)
            gift = random.randint(150_000, 420_000)
            oil_barrels += bonus_oil
            capital += gift
            incident_text = (
                "🛢 <b>ЗОЛОТОЙ ГЕЙЗЕР НА КАЧАЛКЕ №1!</b>\n"
                "Ваши нефтяные вышки у входа в Aladeen Oil Tower пробили сверхглубокий пласт «Экстра-Сыр-Брент»!\n"
                f"💰 Доход: <b>+{gift:,}</b> сыр. | 🛢 Добыча: <b>+{bonus_oil}</b> барр.!"
            )
        elif roll < 0.90:
            gift = random.randint(120_000, 320_000)
            capital += gift
            border_heat = min(100, border_heat + 5)
            incident_text = (
                "🏎 <b>ЧАЕВЫЕ ОТ НЕФТЯНОГО ШЕЙХА НА ЗОЛОТОМ ГЕЛИКЕ!</b>\n"
                "Магнат припарковался у мраморного подиума, заценил золотые лифты и оставил кейс сыроежек на чай!\n"
                f"💰 В кассу: <b>+{gift:,}</b> сыр.!"
            )
        elif roll < 0.95:
            hype_cash = random.randint(90_000, 240_000)
            capital += hype_cash
            babki = min(100, babki + 8)
            incident_text = (
                "🏅 <b>ВАДИЙСКИЕ ОЛИМПИЙСКИЕ ИГРЫ У ВАШЕЙ ВЫСОТКИ!</b>\n"
                "Аладин лично пробежал 100-метровку у входа (подстрелив конкурентов) — туристы ринулись открывать вклады!\n"
                f"💰 Комиссия новых клиентов: <b>+{hype_cash:,}</b> сыр."
            )
        elif random.random() < 0.30:
            updates["power_grid"] = False
            incident_text = (
                "⚡ <b>БЛЭКАУТ НА 88-М ЭТАЖЕ!</b>\n"
                "Гигантская золотая вывеска «ВАДИЯ VIP-БАНК» вырубила подстанцию! Лифты зависли, пора дёрнуть рубильник!"
            )

        if rent_warning:
            incident_text = (incident_text + "\n" + rent_warning) if incident_text else rent_warning

        updates.update({
            "durability": durability,
            "fire_risk": fire_risk,
            "rats_infestation": rats,
            "babki_queue": babki,
            "inspection_anger": anger,
            "border_heat": border_heat,
            "capital": capital,
            "oil_barrels": oil_barrels,
            "total_disasters_survived": survived,
        })

    return updates, incident_text


async def collect_depositor_maintenance(chat_id: int, banker_id: int, max_total_fee: int = 25_000) -> int:
    """
    Символический сервисный сбор с вкладчиков за VIP-обслуживание в Вадии (до 0.2%, не более 3,000 сыр. с человека).
    """
    try:
        from db import get_db
        from user_manager import update_user_field
        db = get_db()
        users_ref = db.collection('chats').document(str(chat_id)).collection('users')
        dep_docs_raw = await users_ref.where('bank_name', '==', banker_id).get()
        dep_docs = []
        if hasattr(dep_docs_raw, '__aiter__'):
            async for d in dep_docs_raw:
                dep_docs.append(d)
        else:
            for d in dep_docs_raw:
                dep_docs.append(d)

        total_collected = 0
        for doc in dep_docs:
            if total_collected >= max_total_fee:
                break
            d = doc.to_dict() or {}
            dep = int(d.get('bank_deposit', 0))
            if dep >= 1_000:
                fee = min(3000, max(1, int(dep * 0.002)))
                new_dep = dep - fee
                try:
                    await update_user_field(chat_id, int(doc.id), 'bank_deposit', new_dep)
                    total_collected += fee
                except Exception:
                    pass
        return total_collected
    except Exception as e:
        logger.warning("Error collecting depositor maintenance: %s", e)
        return 0


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
    """Форматирует главную панель небоскрёба нефтяных магнатов в Республике Вадия."""
    capital = bank_data.get("capital", 0)
    rate = bank_data.get("deposit_rate", 13.0)
    name = bank_data.get("name", "Вадия VIP-банк")

    durability = int(bank_data.get("durability", 100))
    fire_risk = int(bank_data.get("fire_risk", 15))
    rats = int(bank_data.get("rats_infestation", 10))
    babki = int(bank_data.get("babki_queue", 20))
    anger = int(bank_data.get("inspection_anger", 15))
    border_heat = int(bank_data.get("border_heat", 15))
    power = bank_data.get("power_grid", True)
    survived = bank_data.get("total_disasters_survived", 0)
    smuggle_runs = bank_data.get("smuggle_runs", 0)
    oil_barrels = int(bank_data.get("oil_barrels", 1000))

    now = int(time.time())
    ticker = _get_wadiya_ticker(now)

    rent_until = bank_data.get("rent_paid_until", 0)
    if now >= rent_until:
        rent_status = "🔴 ПРОСРОЧЕНО (Гвардия у шлагбаума!)"
    else:
        diff = rent_until - now
        hrs = diff // 3600
        mins = (diff % 3600) // 60
        if diff <= 10800:
            time_display = f"{hrs}ч {mins}м" if hrs > 0 else f"{mins}м"
            rent_status = f"🟡 Скоро истечет! ({time_display})"
        else:
            rent_status = f"🟢 Оплачено ({hrs} ч.)"

    power_status = "🟢 380V GOLD TOWER" if power else "🔴 БЛЭКАУТ (Лифты стоят!)"

    warnings = []
    if durability <= 15:
        warnings.append("🚨 <b>АВАРИЯ:</b> Шпиль затупился! Аладин в бешенстве!")
    if fire_risk >= 75:
        warnings.append("🔥 <b>ПЕРЕГРЕВ:</b> Центрифуги в пентхаусе дымят!")
    if babki >= 85:
        warnings.append("👸 <b>ПРОБКА ИЗ ШЕЙХОВ:</b> Гелики перекрыли подиум!")
    if anger >= 80:
        warnings.append("🎖 <b>АЛАДИН РЯДОМ:</b> Личный кортеж подъезжает ко входу!")
    if border_heat >= 80:
        warnings.append("🕵️ <b>САНКЦИИ ООН:</b> Инспекторы проверяют сырные баррели!")
    if not power:
        warnings.append("⚡ <b>НЕТ СВЕТА:</b> Золотая вывеска потухла!")
    if now < rent_until and (rent_until - now) <= 3600:
        mins_left = max(1, int((rent_until - now) // 60))
        warnings.append(f"📜 <b>КОНЦЕССИЯ ВАДИИ:</b> Осталось {mins_left} мин.! Продлите аренду участка заранее.")

    if len(warnings) > 3:
        status_block = "\n".join(warnings[:3]) + f"\n⚠️ <i>...и ещё {len(warnings)-3} угроз!</i>\n"
    elif warnings:
        status_block = "\n".join(warnings) + "\n"
    else:
        status_block = ""

    inc_block = f"\n💥 <b>СВОДКА:</b>\n{incident_text}\n" if incident_text else ""

    co_bankers_names = bank_data.get("co_banker_names", [])
    if co_bankers_names:
        owners_line = f"👑 <b>Нефтяные магнаты:</b> {escape_html(bank_data.get('banker_name', '🦖'))} & 🤝 <b>{escape_html(', '.join(co_bankers_names))}</b>\n"
    else:
        owners_line = f"👑 <b>Нефтяной магнат:</b> {escape_html(bank_data.get('banker_name', '🦖'))}\n"

    slogan_line = "<i>«Всё максимально Аладин: сыроежки качают нефть прямо из пустыни Вадии»</i>\n"

    text = (
        f"🏛 <b>{escape_html(name)}</b> <i>[Вадия • Aladeen Oil Tower]</i>\n"
        f"{owners_line}"
        f"{slogan_line}"
        f"📡 <code>{ticker}</code>\n\n"
        f"💰 <b>Капитал банка:</b> {capital:,} сыр.\n"
        f"📈 <b>Ставка:</b> <b>{rate}%</b> в день | 🛢 <b>Нефти:</b> <b>{oil_barrels:,}</b> барр.\n\n"
        f"🏙 <b>СОСТОЯНИЕ ВЫСОТКИ В ВАДИИ:</b>\n"
        f"🏢 Золотой фасад: [{_render_bar(durability)}] <b>{durability}%</b>\n"
        f"🔥 Нефте-центрифуга: [{_render_bar(fire_risk)}] <b>{fire_risk}%</b>\n"
        f"🐪 Верблюды в лобби: [{_render_bar(rats)}] <b>{rats}%</b>\n"
        f"👸 Очередь шейхов: [{_render_bar(babki)}] <b>{babki}%</b>\n"
        f"🎖 Капризы Аладина: [{_render_bar(anger)}] <b>{anger}%</b>\n"
        f"🕵️ Санкции ООН: [{_render_bar(border_heat)}] <b>{border_heat}%</b>\n"
        f"⚡ Энергия: {power_status}\n"
        f"📜 Концессия: {rent_status}\n"
        f"🚢 Танкеров: <b>{smuggle_runs}</b> | 🏆 ЧП: <b>{survived}</b>\n\n"
        f"👥 <b>Вкладчиков:</b> {total_depositors} | 🏦 <b>Вклады:</b> {total_deposits:,} сыр.\n"
        f"🤝 <b>Кредитов:</b> {total_loans_given:,} сыр.\n"
        f"{inc_block}"
        f"{status_block}"
        f"{audit_warning}"
    )

    if len(text) > 1020:
        text = text.replace(slogan_line, "")

    return text


def get_shabby_bank_kb(banker_id: int, bank_data: Dict[str, Any]):
    """Формирует клавиатуру управления нефтяным небоскрёбом в Вадии."""
    builder = InlineKeyboardBuilder()

    power = bank_data.get("power_grid", True)
    babki = int(bank_data.get("babki_queue", 20))
    fire = int(bank_data.get("fire_risk", 15))
    durability = int(bank_data.get("durability", 100))
    rats = int(bank_data.get("rats_infestation", 10))
    anger = int(bank_data.get("inspection_anger", 15))
    border_heat = int(bank_data.get("border_heat", 15))

    # Срочные аварийные кнопки первыми
    if not power:
        builder.button(text="⚡ Врубить генератор", callback_data=f"bshabby_power_{banker_id}")
    if fire >= 50:
        builder.button(text=f"🧯 Охладить качалки ({COST_EXTINGUISH//1000}k)", callback_data=f"bshabby_extinguish_{banker_id}")
    if babki >= 55:
        builder.button(text=f"🥂 Коктейли шейхам ({COST_CALM_BABKI//1000}k)", callback_data=f"bshabby_calm_{banker_id}")
    if durability <= 65:
        builder.button(text=f"🏢 Подточить шпиль ({COST_PATCH_ROOF//1000}k)", callback_data=f"bshabby_patch_{banker_id}")
    if rats >= 45:
        builder.button(text=f"🐪 Выгнать верблюдов ({COST_POISON_RATS//1000}k)", callback_data=f"bshabby_poison_{banker_id}")
    if anger >= 45:
        builder.button(text=f"🎖 Гелик Аладину ({COST_BRIBE_INSPECTOR//1000}k)", callback_data=f"bshabby_bribe_{banker_id}")
    if border_heat >= 45:
        builder.button(text=f"🕵️ Занести ООН ({COST_CUSTOMS_DEAL//1000}k)", callback_data=f"bshabby_customs_{banker_id}")

    # Нефтяная концессия земли Вадии
    now = int(time.time())
    rent_until = bank_data.get("rent_paid_until", 0)
    if now >= rent_until:
        builder.button(text=f"📜 Оплатить участок ({COST_PAY_RENT//1000}k)", callback_data=f"bshabby_rent_{banker_id}")
    elif (rent_until - now) <= EARLY_RENT_PAY_SECONDS:
        builder.button(text=f"📜 Продлить участок ({COST_PAY_RENT//1000}k)", callback_data=f"bshabby_rent_{banker_id}")

    # Фирменные движухи Вадии и нефтяных магнатов
    builder.button(text="🛢 Качнуть нефть (ОПЭК)", callback_data=f"bshabby_smuggle_{banker_id}")
    builder.button(text="☢️ Вердикт «Аладин?»", callback_data=f"bshabby_aladeen_{banker_id}")
    builder.button(text=f"💱 Нефтебиржа ВДР ({COST_FOREX_BET//1000}k)", callback_data=f"bshabby_forex_{banker_id}")
    builder.button(text=f"🐪 Саммит ОПЭК ({COST_FEAST//1000}k)", callback_data=f"bshabby_feast_{banker_id}")
    builder.button(text=f"✨ Полировка шпиля ({COST_LUX_CLEANING//1000}k)", callback_data=f"bshabby_clean_{banker_id}")

    # Стандартные банковские вкладки + Гайд
    builder.button(text="🔄 Обновить", callback_data=f"bstat_main_{banker_id}")
    builder.button(text="📖 Гайд магната", callback_data=f"bshabby_guide_{banker_id}")
    builder.button(text="👥 Вкладчики", callback_data=f"bstat_deps_{banker_id}")
    builder.button(text="🤝 Должники", callback_data=f"bstat_loans_{banker_id}")
    builder.button(text="⚙️ Настройки", callback_data=f"bstat_settings_{banker_id}")
    builder.button(text="⬆️ Улучшения", callback_data=f"bstat_upgrades_{banker_id}")
    builder.button(text="💼 Схемы", callback_data=f"bstat_schemes_{banker_id}")

    builder.adjust(2)
    return builder.as_markup()


def get_shabby_guide_text() -> str:
    """Возвращает гайд по управлению высоткой нефтяных магнатов в Вадии."""
    return (
        "📖 <b>ГАЙД НЕФТЯНОГО МАГНАТА: «РЕСПУБЛИКА ВАДИЯ • ALADEEN OIL TOWER»</b>\n\n"
        "🛢 <b>Великий переезд:</b>\n"
        "Из-за запредельного количества сыроежек ваш банк стал нефтегигантом! За <b>40% от капитала</b> вы покинули "
        "КПП Табулистан, выкупили землю у дворца Адмирала-Генерала Аладина и построили элитную золотую высотку с острым шпилем.\n\n"
        "🛢 <b>Качнуть нефть (ОПЭК):</b>\n"
        "Раз в 20 минут отправляет танкер с сырной нефтью мимо инспекторов ООН. "
        "Приносит <b>+250k–850k сыр.</b> и сотни баррелей нефти в статистику.\n\n"
        "☢️ <b>Вердикт «Аладин или Аладин?»:</b>\n"
        "Раз в 15 минут Аладин выносит вердикт вашему банку: может накинуть грант из нефтяного фонда, оценить остроту шпиля "
        "и разогнать очередь или потребовать золотой бюст в лобби.\n\n"
        "💱 <b>Нефтебиржа ВДР:</b>\n"
        "Торги вадийским риалом и нефтяными фьючерсами (раз в 25 минут).\n\n"
        "🐪 <b>Саммит ОПЭК и ✨ Полировка шпиля:</b>\n"
        "Угощаете делегации на вертолётной площадке 88-го этажа — снимаете санкции ООН, капризы Аладина и выгоняете верблюдов из золотого лифта.\n\n"
        "👥 <b>VIP-сервисный сбор:</b> При обслуживании башни с вкладчиков удерживается до 0.2% (не более 3,000 сыр.)!"
    )


def get_shabby_guide_kb(banker_id: int):
    """Клавиатура возврата из гайда."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в высотку", callback_data=f"bstat_main_{banker_id}")
    return builder.as_markup()


async def execute_shabby_repair(
    chat_id: int,
    banker_id: int,
    action: str,
    bank_data: Dict[str, Any]
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Выполняет действия и прикольчики нефтяных магнатов в высотке Вадии.
    Возвращает (успех, сообщение, словарь_обновлений).
    """
    capital = int(bank_data.get("capital", 0))

    if action == "extinguish":
        if capital < COST_EXTINGUISH:
            return False, f"❌ Нужно {COST_EXTINGUISH:,} сыр. в капитале на охлаждение нефтекачек и центрифуги!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_EXTINGUISH - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        fire = max(5, int(bank_data.get("fire_risk", 15)) - random.randint(35, 55))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🧯 <b>Нефтекачки и сырная центрифуга охлаждены!</b>\nЗалили жидкий азот в реактор пентхауса. Нагрузка упала до <b>{fire}%</b>!{dep_note}", {
            "capital": new_capital,
            "fire_risk": fire
        }

    elif action == "patch":
        if capital < COST_PATCH_ROOF:
            return False, f"❌ Нужно {COST_PATCH_ROOF:,} сыр. в капитале на золотые плиты и заточку шпиля!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_PATCH_ROOF - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        durability = min(100, int(bank_data.get("durability", 100)) + random.randint(25, 40))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🏢 <b>Шпиль заточен, золото блестит!</b>\nАладин одобрил остроту крыши. Состояние высотки: <b>{durability}%</b>!{dep_note}", {
            "capital": new_capital,
            "durability": durability
        }

    elif action == "poison":
        if capital < COST_POISON_RATS:
            return False, f"❌ Нужно {COST_POISON_RATS:,} сыр. в капитале на охрану против верблюдов!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_POISON_RATS - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        rats = max(5, int(bank_data.get("rats_infestation", 10)) - random.randint(35, 60))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🐪 <b>Верблюды и козы выдворены из золотого лифта!</b>\nОхрана в костюмах оттеснила караван к пальмам. Чистота лобби: верблюдов <b>{rats}%</b>!{dep_note}", {
            "capital": new_capital,
            "rats_infestation": rats
        }

    elif action == "calm":
        if capital < COST_CALM_BABKI:
            return False, f"❌ Нужно {COST_CALM_BABKI:,} сыр. в капитале на золотой раф и прохладные коктейли шейхам!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_CALM_BABKI - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        babki = max(5, int(bank_data.get("babki_queue", 20)) - random.randint(35, 55))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🥂 <b>Шейхи и VIP-гости развлечены коктейлями!</b>\nЗолотые Гелики разъехались по парковке. Очередь: <b>{babki}%</b>!{dep_note}", {
            "capital": new_capital,
            "babki_queue": babki
        }

    elif action == "bribe":
        if capital < COST_BRIBE_INSPECTOR:
            return False, f"❌ Нужно {COST_BRIBE_INSPECTOR:,} сыр. в капитале на золотой Гелик для Аладина!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_BRIBE_INSPECTOR - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🎖 <b>Адмирал-Генерал Аладин в восторге!</b>\n«Очень Аладин! Отныне эта башня — восьмое чудо Вадии!» Капризы Аладина сброшены в 0!{dep_note}", {
            "capital": new_capital,
            "inspection_anger": 0
        }

    elif action == "customs":
        if capital < COST_CUSTOMS_DEAL:
            return False, f"❌ Нужно {COST_CUSTOMS_DEAL:,} сыр. в капитале на «дипломатический пакет» для комиссии ООН!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_CUSTOMS_DEAL - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        heat = max(0, int(bank_data.get("border_heat", 15)) - random.randint(45, 70))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🕵️ <b>Инспекторы ООН уехали с сувенирами!</b>\nВ отчёте написали, что острая башня — это «высотный молокозавод». Санкции снижены до <b>{heat}%</b>!{dep_note}", {
            "capital": new_capital,
            "border_heat": heat
        }

    elif action == "feast":
        if capital < COST_FEAST:
            return False, f"❌ Нужно {COST_FEAST:,} сыр. в капитале на саммит ОПЭК на вертолётной площадке!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_FEAST - dep_fee)
        new_capital = max(0, capital - cost_after_fee)

        heat = max(0, int(bank_data.get("border_heat", 15)) - random.randint(25, 40))
        anger = max(0, int(bank_data.get("inspection_anger", 15)) - random.randint(25, 40))
        tip = random.randint(80_000, 220_000) if random.random() < 0.40 else 0
        new_capital += tip

        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        tip_note = f"\n🎁 <i>Министр нефти Вадии заценил пармезан и оставил +{tip:,} сыр. чаевых!</i>" if tip > 0 else ""
        return True, (
            f"🐪 <b>САММИТ ОПЭК НА 88-М ЭТАЖЕ ПРОШЁЛ ШИКАРНО!</b>\n"
            f"На вертолётной площадке жарили шашлык с выдержанным чеддером под салют Аладина.\n"
            f"🕵️ Санкции ООН: <b>{heat}%</b> | 🎖 Капризы Аладина: <b>{anger}%</b>"
            f"{tip_note}{dep_note}"
        ), {
            "capital": new_capital,
            "border_heat": heat,
            "inspection_anger": anger
        }

    elif action == "forex":
        now = int(time.time())
        last_forex = int(bank_data.get("last_forex_time", 0))
        if now - last_forex < FOREX_COOLDOWN:
            mins_left = max(1, (FOREX_COOLDOWN - (now - last_forex) + 59) // 60)
            return False, f"⏳ На бирже Вадии объявлен «Час Аладина»! Торги откроются через <b>{mins_left} мин.</b>", {}

        if capital < COST_FOREX_BET:
            return False, f"❌ Нужно {COST_FOREX_BET:,} сыр. в капитале для входа на нефтебиржу Вадии!", {}

        outcome = random.random()
        if outcome < 0.50:
            profit = random.randint(150_000, 480_000)
            barrels_gain = random.randint(150, 400)
            return True, (
                f"📈 <b>НЕФТЬ ВАДИИ УЛЕТЕЛА В КОСМОС!</b>\n"
                f"Аладин заявил в ООН, что качает только «экологичную сырную нефть» — котировки ВДР взорвались!\n"
                f"💰 Чистая прибыль: <b>+{profit:,}</b> сыр. (+{barrels_gain} 🛢)"
            ), {
                "capital": capital + profit,
                "oil_barrels": int(bank_data.get("oil_barrels", 1000)) + barrels_gain,
                "last_forex_time": now
            }
        elif outcome < 0.78:
            loss = min(capital, random.randint(40_000, 110_000))
            babki = max(0, int(bank_data.get("babki_queue", 20)) - 20)
            return True, (
                f"📉 <b>КОРРЕКЦИЯ НА СЛОВАХ ПРО КРУГЛЫЕ ШПИЛИ!</b>\n"
                f"Вы потеряли <b>-{loss:,}</b> сыр. на фьючерсах, но шейхи в ужасе выбежали из очереди проверять свои вышки!\n"
                f"👸 Очередь у входа снижена до <b>{babki}%</b>."
            ), {
                "capital": max(0, capital - loss),
                "babki_queue": babki,
                "last_forex_time": now
            }
        else:
            anger = max(0, int(bank_data.get("inspection_anger", 15)) - 20)
            heat = max(0, int(bank_data.get("border_heat", 15)) - 15)
            return True, (
                f"🏅 <b>НАЦБАНК ВАДИИ ВЫДАЛ ДИВИДЕНДЫ БИЛЕТАМИ НА ОЛИМПИАДУ!</b>\n"
                f"Депозит вернулся в ноль, но вы раздали золотые приглашения на «Игры Аладина» всем инспекторам!\n"
                f"🎖 Капризы Аладина: <b>{anger}%</b> | 🕵️ Санкции ООН: <b>{heat}%</b>"
            ), {
                "inspection_anger": anger,
                "border_heat": heat,
                "last_forex_time": now
            }

    elif action == "clean":
        if capital < COST_LUX_CLEANING:
            return False, f"❌ Нужно {COST_LUX_CLEANING:,} сыр. в капитале на полировку золотого шпиля!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_LUX_CLEANING - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        durability = min(100, int(bank_data.get("durability", 100)) + 15)
        rats = max(0, int(bank_data.get("rats_infestation", 10)) - 20)
        heat = max(0, int(bank_data.get("border_heat", 15)) - 15)
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, (
            f"✨ <b>Высотка сияет на всю пустыню Вадии!</b>\n"
            f"Золотой шпиль отполирован до зеркального блеска, мрамор блестит, верблюды ушли.\n"
            f"🏢 Фасад: <b>{durability}%</b> | 🐪 Верблюды: <b>{rats}%</b> | 🕵️ Санкции: <b>{heat}%</b>{dep_note}"
        ), {
            "capital": new_capital,
            "durability": durability,
            "rats_infestation": rats,
            "border_heat": heat
        }

    elif action == "smuggle":
        now = int(time.time())
        last_smuggle = int(bank_data.get("last_smuggle_time", 0))
        if now - last_smuggle < SMUGGLE_COOLDOWN:
            mins_left = max(1, (SMUGGLE_COOLDOWN - (now - last_smuggle) + 59) // 60)
            return False, f"⏳ Танкеры ещё загружаются в порту Вадии! Следующая отгрузка через <b>{mins_left} мин.</b>", {}

        if capital < 50_000:
            return False, "❌ Нужно минимум 50,000 сыр. в капитале на фрахт нефтяного танкера!", {}

        heat = int(bank_data.get("border_heat", 15))
        runs = int(bank_data.get("smuggle_runs", 0))
        barrels = int(bank_data.get("oil_barrels", 1000))
        fail_chance = min(0.75, 0.15 + (heat / 160.0))

        if random.random() >= fail_chance:
            profit = random.randint(250_000, 850_000)
            barrels_added = random.randint(250, 650)
            new_heat = min(100, heat + random.randint(10, 20))
            return True, (
                f"🛢 <b>ТАНКЕР НЕФТИ ОПЭК ПРОШЁЛ МИМО САНКЦИЙ!</b>\n"
                f"Вы сбыли {barrels_added} баррелей сырной нефти под видом «оливкового масла Вадии»!\n"
                f"💰 Чистая прибыль: <b>+{profit:,}</b> сыр. | 🛢 Всего нефти: <b>{barrels + barrels_added:,}</b> барр.\n"
                f"🕵️ Санкции ООН выросли до <b>{new_heat}%</b>."
            ), {
                "capital": capital + profit,
                "border_heat": new_heat,
                "last_smuggle_time": now,
                "smuggle_runs": runs + 1,
                "oil_barrels": barrels + barrels_added,
            }
        else:
            fine = min(capital, random.randint(80_000, 160_000))
            new_heat = min(100, heat + 18)
            new_anger = min(100, int(bank_data.get("inspection_anger", 15)) + 15)
            return True, (
                f"🚨 <b>ТАНКЕР ДОСМОТРЕЛ ПАТРУЛЬ ООН!</b>\n"
                f"В бочках с «гуманитарным сыром» нашли сырую нефть и инструкцию к центрифуге!\n"
                f"💸 Потери капитала: <b>-{fine:,}</b> сыр. | 🕵️ Санкции: <b>{new_heat}%</b>"
            ), {
                "capital": max(0, capital - fine),
                "border_heat": new_heat,
                "inspection_anger": new_anger,
                "last_smuggle_time": now
            }

    elif action == "aladeen":
        now = int(time.time())
        last_aladeen = int(bank_data.get("last_aladeen_time", 0))
        if now - last_aladeen < ALADEEN_COOLDOWN:
            mins_left = max(1, (ALADEEN_COOLDOWN - (now - last_aladeen) + 59) // 60)
            return False, f"⏳ Адмирал-Генерал в душе с золотой уткой! Следующий вердикт через <b>{mins_left} мин.</b>", {}

        roll = random.random()
        if roll < 0.48:
            grant = random.randint(350_000, 950_000)
            barrels_bonus = random.randint(200, 500)
            return True, (
                f"☢️ <b>ВЕРДИКТ АЛАДИНА: «ВАШ БАНК — АЛАДИН!»</b> 😀\n"
                f"<i>(Это... позитивный Аладин!)</i>\n"
                f"Генерал подарил грант из Нефтяного Фонда Вадии: <b>+{grant:,}</b> сыр. (+{barrels_bonus} 🛢) и обнулил капризы!"
            ), {
                "capital": capital + grant,
                "oil_barrels": int(bank_data.get("oil_barrels", 1000)) + barrels_bonus,
                "inspection_anger": 0,
                "last_aladeen_time": now,
            }
        elif roll < 0.78:
            bonus = random.randint(200_000, 500_000)
            babki = max(0, int(bank_data.get("babki_queue", 20)) - 30)
            return True, (
                f"🚀 <b>ВЕРДИКТ ПО ШПИЛЮ: «МАКСИМАЛЬНО ОСТРЫЙ!»</b>\n"
                f"Учёные подтвердили: форма высотки на 100% пугает врагов Вадии! Шейхи в восторге занесли <b>+{bonus:,}</b> сыр.!"
            ), {
                "capital": capital + bonus,
                "babki_queue": babki,
                "durability": 100,
                "last_aladeen_time": now,
            }
        else:
            fine = min(capital, random.randint(100_000, 260_000))
            heat = max(0, int(bank_data.get("border_heat", 15)) - 20)
            return True, (
                f"☢️ <b>ВЕРДИКТ АЛАДИНА: «ВАШ БАНК — АЛАДИН!»</b> 😟\n"
                f"<i>(Это... негативный Аладин...)</i>\n"
                f"Аладин обиделся на малое число своих портретов в лифте (-<b>{fine:,}</b> сыр. на золотой бюст), но разогнал комиссию ООН (-20% санкций)!"
            ), {
                "capital": max(0, capital - fine),
                "border_heat": heat,
                "last_aladeen_time": now,
            }

    elif action == "rent":
        if capital < COST_PAY_RENT:
            return False, f"❌ Нужно {COST_PAY_RENT:,} сыр. в капитале на оплату нефтяной концессии участка в Вадии!", {}
        now = int(time.time())
        rent_until_curr = bank_data.get("rent_paid_until", 0)
        if now < rent_until_curr and (rent_until_curr - now) > EARLY_RENT_PAY_SECONDS:
            hrs_left = (rent_until_curr - now) // 3600
            return False, f"⏳ Участок ещё оплачен (осталось {hrs_left} ч.). Продление доступно за {EARLY_RENT_PAY_SECONDS//3600} ч. до конца!", {}

        new_capital = capital - COST_PAY_RENT
        rent_until = max(now, rent_until_curr) + DAILY_RENT_SECONDS
        hrs_total = max(0, int((rent_until - now) // 3600))
        return True, f"📜 <b>Нефтяная концессия в Вадии продлена на 24 часа!</b>\nУчасток под высоткой оплачен ещё на {hrs_total} ч., гвардия салютует.", {
            "capital": new_capital,
            "rent_paid_until": rent_until
        }

    elif action == "power":
        chance = 0.85
        if random.random() < chance:
            return True, "⚡ <b>ЩЕЛК!</b>\nЗолотой рубильник включён! Вывеска «ВАДИЯ VIP-БАНК» снова слепит всю пустыню!", {
                "power_grid": True
            }
        else:
            shock = min(capital, 20_000)
            return True, f"⚡ <b>ШАРАХНУЛО ТОКОМ!</b>\nСгорел золотой стабилизатор (-{shock:,} сыр.), свет не зажёгся. Жмите ещё раз!", {
                "capital": max(0, capital - shock),
                "power_grid": False
            }

    return False, "Неизвестное действие.", {}
