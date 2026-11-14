import os
import time
import random
import logging
from typing import Dict, Any, Tuple, Optional
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html

logger = logging.getLogger(__name__)

# Пользователи с хардкорным банком (приграничный VIP-офис у Табулистана)
SHABBY_BANKER_IDS = {6896326008, 7081184095}

# Путь к изображению здания банка
SHABBY_BANK_IMG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", "shabby_bank.jpg"))
try:
    from shabby_bank_asset import ensure_shabby_bank_image
    ensure_shabby_bank_image(SHABBY_BANK_IMG_PATH)
except Exception as _e:
    logger.warning("Could not auto-extract shabby bank image: %s", _e)


def get_shabby_bank_input_file():
    """Возвращает InputFile для гарантированной отправки фото банка (FSInputFile или BufferedInputFile)."""
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
            logger.warning("Could not load FSInputFile for shabby bank: %s", e)

    try:
        from shabby_bank_asset import SHABBY_BANK_B64
        from aiogram.types import BufferedInputFile
        import base64
        return BufferedInputFile(base64.b64decode(SHABBY_BANK_B64), filename="shabby_bank.jpg")
    except Exception as e:
        logger.error("Could not build buffered shabby bank input file: %s", e)
        return None

# Стоимость обслуживания и приколов (сбалансировано под разбогатевший банк)
COST_EXTINGUISH = 45_000         # Охлаждение майнинг-фермы и проводки джакузи
COST_PATCH_ROOF = 55_000         # Реставрация лепнины и табулистанского мрамора
COST_POISON_RATS = 35_000        # Депортация енотов-нелегалов обратно за границу
COST_CALM_BABKI = 30_000         # Раф на кокосовом, валидол и VIP-талончики бабкам
COST_BRIBE_INSPECTOR = 90_000    # Конверт майору Сидоренко (теперь он на Гелике)
COST_CUSTOMS_DEAL = 80_000       # Решить вопросик с таможней Табулистана
COST_LUX_CLEANING = 40_000       # Люкс-клининг: вывезти остатки мусора и навести лоск
COST_FEAST = 50_000              # Дипломатический банкет «Сыр & Табуле» на границе
COST_FOREX_BET = 40_000          # Ставка на качели табулистанского тугрика (ТБЛ)
COST_PAY_RENT = 75_000           # Налог на приграничную землю (24 часа)

DAILY_RENT_SECONDS = 86_400      # 24 часа
EARLY_RENT_PAY_SECONDS = 7200    # Досрочное продление аренды (за 2 часа до окончания)
SMUGGLE_COOLDOWN = 1200          # Кулдаун на серый транш через границу (20 минут)
FOREX_COOLDOWN = 1500            # Кулдаун на биржу тугрика Табулистана (25 минут)

# Интервал между спонтанными событиями
INCIDENT_COOLDOWN = 900          # 15 минут

# Бегущая строка Нацбанка Табулистана (меняется раз в 30 минут)
TABULISTAN_TICKERS = [
    "1 сыр. = 14.88 ТБЛ 📈 (Нацбанк Табулистана докупил два принтера)",
    "1 сыр. = 9.40 ТБЛ 📉 (В столице Табулистана объявили День Бесплатного Табуле)",
    "1 сыр. = 22.10 ТБЛ 🚀 (Тугрик обеспечен горным эхом и честным словом)",
    "1 сыр. = 11.05 ТБЛ ⚖️ (Таможня перешла на сменный график «через одного»)",
    "1 сыр. = 17.77 ТБЛ 💎 (В Табулистане признали сыр стратегическим союзником петрушки)",
    "1 сыр. = 13.13 ТБЛ 🐐 (Индекс горного козла стабилен, шлагбаум смазан)",
]


def _get_tabulistan_ticker(now: int) -> str:
    idx = (now // 1800) % len(TABULISTAN_TICKERS)
    return TABULISTAN_TICKERS[idx]


def is_shabby_bank(bank_data: Optional[Dict[str, Any]], banker_id: Optional[int] = None) -> bool:
    """Проверяет, является ли банк приграничным банком у Табулистана."""
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
    """Возвращает базовые параметры нового здания на границе с Табулистаном."""
    now = int(time.time())
    return {
        "is_shabby": True,
        "shabby_hardcore": True,
        "durability": 70,             # Состояние евроремонта и фасада (0-100%)
        "fire_risk": 25,              # Перегруз майнинг-фермы и джакузи (0-100%)
        "rats_infestation": 20,       # Набеги енотов-нелегалов с границы (0-100%)
        "babki_queue": 35,            # Очередь VIP-бабок за кэшбэком (0-100%)
        "inspection_anger": 25,       # Аппетиты майора Сидоренко и СЭС (0-100%)
        "border_heat": 30,            # Палево на таможне Табулистана (0-100%)
        "power_grid": True,           # Подстанция (True - 380V, False - выбило автомат)
        "rent_paid_until": now + DAILY_RENT_SECONDS,
        "last_incident_time": now,
        "last_smuggle_time": 0,
        "last_forex_time": 0,
        "smuggle_runs": 0,
        "total_disasters_survived": 0
    }


def _render_bar(value: int, max_value: int = 100, length: int = 5) -> str:
    """Генерирует текстовую полосу прогресса."""
    val = max(0, min(value, max_value))
    filled = int(round((val / max_value) * length))
    return "▓" * filled + "░" * (length - filled)


def check_and_apply_shabby_decay(bank_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Пассивная суета на границе с Табулистаном и спонтанные события.
    Возвращает обновленные данные банка и текст события, если оно произошло.
    """
    now = int(time.time())
    last_check = bank_data.get("last_incident_time", now)
    elapsed = now - last_check

    updates = {}
    incident_text = None

    durability = int(bank_data.get("durability", 70))
    fire_risk = int(bank_data.get("fire_risk", 25))
    rats = int(bank_data.get("rats_infestation", 20))
    babki = int(bank_data.get("babki_queue", 35))
    anger = int(bank_data.get("inspection_anger", 25))
    border_heat = int(bank_data.get("border_heat", 30))
    capital = int(bank_data.get("capital", 0))

    if elapsed >= INCIDENT_COOLDOWN:
        updates["last_incident_time"] = now

        # Мусора меньше, евроремонт держится бодрее, но граница не спит
        durability = max(0, durability - random.randint(2, 5))
        fire_risk = min(100, fire_risk + random.randint(3, 7))
        rats = min(100, rats + random.randint(2, 6))
        babki = min(100, babki + random.randint(4, 10))
        anger = min(100, anger + random.randint(2, 6))
        border_heat = min(100, border_heat + random.randint(2, 5))

        # Проверка налога на приграничную землю
        rent_until = bank_data.get("rent_paid_until", 0)
        rent_warning = ""
        if now > rent_until:
            rent_penalty = 75_000
            capital = max(0, capital - rent_penalty)
            durability = max(0, durability - 5)
            rent_warning = (
                f"\n⚠️ <b>ЗЕМЕЛЬНЫЙ КОМИТЕТ ТАБУЛИСТАНА:</b> Просрочен налог на приграничный участок! "
                f"Пограничники опечатали шлагбаум и списали <b>{rent_penalty:,}</b> сыр. штрафа!"
            )

        roll = random.random()
        survived = int(bank_data.get("total_disasters_survived", 0))

        if border_heat >= 70 and roll < 0.22:
            # ОБЛАВА ТАМОЖНИ ТАБУЛИСТАНА
            confiscated = min(capital, random.randint(60_000, 160_000))
            capital = max(0, capital - confiscated)
            border_heat = 25
            survived += 1
            incident_text = (
                "🛂 <b>ШМОН ТАМОЖНИ ТАБУЛИСТАНА!</b>\n"
                "Пограничники со служебными овчарками накрыли черный ход, через который тащили элитный пармезан!\n"
                f"💸 Конфисковано на «оформление протокола»: <b>{confiscated:,}</b> сыр.!"
            )
        elif fire_risk >= 65 and roll < 0.40:
            # ПЕРЕГРУЗ МАЙНИНГ-ФЕРМЫ В VIP-ПОДВАЛЕ
            burned = min(capital, random.randint(45_000, 130_000))
            capital = max(0, capital - burned)
            durability = max(0, durability - random.randint(4, 9))
            fire_risk = min(100, fire_risk + 12)
            anger = min(100, anger + 10)
            survived += 1
            incident_text = (
                "🔥 <b>ЗАДЫМЛЕНИЕ В VIP-ПОДВАЛЕ!</b>\n"
                "<i>«Тише, тише, слышишь крик? Это асики в джакузи замкнули...»</i>\n"
                "⚡ Перегрелась скрытая майнинг-ферма сыркоинов, оплавился итальянский натяжной потолок!\n"
                f"💸 Ущерб оборудованию: <b>{burned:,}</b> сыр.!\n"
                f"🏛 Состояние ремонта упало до <b>{durability}%</b>!"
            )
        elif rats >= 60 and roll < 0.56:
            # ЕНОТЫ-НЕЛЕГАЛЫ С ГРАНИЦЫ
            stolen = min(capital, random.randint(25_000, 75_000))
            capital = max(0, capital - stolen)
            survived += 1
            incident_text = (
                "🦝 <b>РЕЙД ЕНОТОВ-КАРМАННИКОВ ИЗ ТАБУЛИСТАНА!</b>\n"
                "Крыс вывели, но через дыру в пограничном заборе пролезла банда наглых енотов и обнесла VIP-ложу!\n"
                f"💸 Утащили в кусты: <b>{stolen:,}</b> сыр.!"
            )
        elif anger >= 75 and roll < 0.70:
            # ВИЗИТ МАЙОРА СИДОРЕНКО НА ГЕЛИКЕ
            fine = min(capital, random.randint(70_000, 150_000))
            capital = max(0, capital - fine)
            anger = 30
            survived += 1
            incident_text = (
                "🚓 <b>ВНЕПЛАНОВЫЙ ВИЗИТ МАЙОРА СИДОРЕНКО!</b>\n"
                "Майор подкатил к крыльцу на свежем Гелике: «Особняк вижу, мрамор вижу, а долю пожнадзора не вижу!»\n"
                f"💸 Пришлось отстегнуть <b>{fine:,}</b> сыр. на «благоустройство части»!"
            )
        elif durability <= 20 and roll < 0.78:
            # ПРОТЕЧКА ДЖАКУЗИ С КРЫШИ
            repair_hit = min(capital, random.randint(40_000, 95_000))
            capital = max(0, capital - repair_hit)
            durability = max(0, durability - 8)
            incident_text = (
                "🛁 <b>ПОТОП ИЗ ДЖАКУЗИ НА ТЕРРАСЕ!</b>\n"
                "Перелилось джакузи в пентхаусе — вода рухнула прямо на мраморную стойку ресепшена!\n"
                f"💸 Залиты купюросчетные машинки, ущерб: <b>{repair_hit:,}</b> сыр.!"
            )
        elif roll < 0.84:
            # ЛОР ТАБУЛИСТАНА: ГОРНЫЕ КОЗЛЫ НА КРЫШЕ
            durability = max(0, durability - random.randint(4, 8))
            incident_text = (
                "🐐 <b>ПАРКУР ГОРНЫХ КОЗЛОВ ТАБУЛИСТАНА!</b>\n"
                "Стадо диких козлов спустилось с перевала, залезло на козырек банка и сжевало кабель от спутниковой тарелки!\n"
                f"🏛 Состояние фасада просело до <b>{durability}%</b>."
            )
        elif roll < 0.90:
            # ЛОР ТАБУЛИСТАНА: ПОДГОН ОТ СЫРНО-ТАБУЛЕШНОГО МАГНАТА
            gift = random.randint(60_000, 160_000)
            capital += gift
            border_heat = min(100, border_heat + 6)
            incident_text = (
                "🥗 <b>ЧАЕВЫЕ ОТ ТАБУЛИСТАНСКОГО МАГНАТА!</b>\n"
                "У кортежа на КПП спустило колесо — хозяин сети «Табуле-Плаза» зашел в ваш VIP-туалет, оценил золотой ершик и занес котлету!\n"
                f"💰 В кассу поступило: <b>+{gift:,}</b> сыр.!"
            )
        elif roll < 0.94:
            # ЛОР ТАБУЛИСТАНА: ХАЙП У ТИКТОКЕРОВ НА ФОНЕ КПП
            hype_cash = random.randint(45_000, 110_000)
            capital += hype_cash
            babki = min(100, babki + 8)
            incident_text = (
                "📱 <b>ЗАЛЕТНЫЙ БЛОГЕР СНЯЛ РИЛС У ВАШЕГО БАНКА!</b>\n"
                "Ролик «Как открыть вклад в особняке на границе с Табулистаном» набрал миллион просмотров!\n"
                f"💰 Новые клиенты принесли <b>+{hype_cash:,}</b> сыр. комиссии (правда, бабки тоже прибежали)."
            )
        elif roll < 0.97:
            # ЛОР ТАБУЛИСТАНА: ДЕНЬ ТИШИНЫ ПО УКАЗУ МИНКУЛЬТА
            babki = max(0, babki - 25)
            anger = max(0, anger - 10)
            incident_text = (
                "🤫 <b>УКАЗ МИНКУЛЬТА ТАБУЛИСТАНА О «ЧАСЕ ТИШИНЫ»!</b>\n"
                "В радиусе километра от границы запрещено громко возмущаться — даже бабки в очереди перешли на шепот!\n"
                f"👵 Напряжение очереди упало до <b>{babki}%</b>."
            )
        elif random.random() < 0.25:
            # ВЫБИЛО ПОДСТАНЦИЮ ОТ НЕОНОВОЙ ВЫВЕСКИ
            updates["power_grid"] = False
            incident_text = (
                "⚡ <b>ПЕРЕГРУЗ НЕОНОВОЙ ВЫВЕСКИ!</b>\n"
                "Огромная неоновая надпись «ДОИСТОРИЧЕСКИЙ VIP-БАНК» вырубила трансформатор на границе!\n"
                "🔌 Стеклянные двери заклинило, терминалы погасли! Надо дернуть автомат в щитовой."
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
            "total_disasters_survived": survived,
        })

    return updates, incident_text


async def collect_depositor_maintenance(chat_id: int, banker_id: int, max_total_fee: int = 25_000) -> int:
    """
    Символический сервисный сбор с вкладчиков за VIP-обслуживание (до 0.2%, не более 3,000 сыр. с человека).
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
    """Форматирует главную панель разбогатевшего банка на границе с Табулистаном."""
    capital = bank_data.get("capital", 0)
    rate = bank_data.get("deposit_rate", 13.0)
    name = bank_data.get("name", "Доисторический VIP-банк")

    durability = int(bank_data.get("durability", 70))
    fire_risk = int(bank_data.get("fire_risk", 25))
    rats = int(bank_data.get("rats_infestation", 20))
    babki = int(bank_data.get("babki_queue", 35))
    anger = int(bank_data.get("inspection_anger", 25))
    border_heat = int(bank_data.get("border_heat", 30))
    power = bank_data.get("power_grid", True)
    survived = bank_data.get("total_disasters_survived", 0)
    smuggle_runs = bank_data.get("smuggle_runs", 0)

    now = int(time.time())
    ticker = _get_tabulistan_ticker(now)

    rent_until = bank_data.get("rent_paid_until", 0)
    if now >= rent_until:
        rent_status = "🔴 ПРОСРОЧЕНО (Шлагбаум перекрыт!)"
    else:
        diff = rent_until - now
        hrs = diff // 3600
        mins = (diff % 3600) // 60
        if diff <= EARLY_RENT_PAY_SECONDS:
            time_display = f"{hrs}ч {mins}м" if hrs > 0 else f"{mins}м"
            rent_status = f"🟡 Скоро истечет! ({time_display})"
        else:
            rent_status = f"🟢 Оплачено ({hrs} ч.)"

    power_status = "🟢 380V VIP (В норме)" if power else "🔴 ОБЕСТОЧЕН (Выбило автомат!)"

    # Критические статусы (логика блокировок сохранена для совместимости)
    warnings = []
    if durability <= 15:
        warnings.append("🚨 <b>АВАРИЯ:</b> Фасад осыпается! Вклады на стопе!")
    if fire_risk >= 75:
        warnings.append("🔥 <b>ПЕРЕГРЕВ:</b> Ферма в подвале дымит!")
    if babki >= 85:
        warnings.append("👵 <b>БУНТ БАБОК:</b> Перекрыли вход за раф! Вклады на стопе!")
    if anger >= 80:
        warnings.append("🚓 <b>ПРОВЕРКА:</b> Сидоренко паркует Гелик у крыльца!")
    if border_heat >= 80:
        warnings.append("🛂 <b>ТАМОЖНЯ:</b> Патрули стянуты к черному ходу!")
    if not power:
        warnings.append("⚡ <b>НЕТ СВЕТА:</b> Неон потух, замки обесточены!")
    if now < rent_until and (rent_until - now) <= 3600:
        mins_left = max(1, int((rent_until - now) // 60))
        warnings.append(f"📜 <b>ПРИГРАНИЧНЫЙ НАЛОГ:</b> Осталось {mins_left} мин.! Продлите аренду участка заранее.")

    if len(warnings) > 3:
        status_block = "\n".join(warnings[:3]) + f"\n⚠️ <i>...и ещё {len(warnings)-3} угроз!</i>\n"
    elif warnings:
        status_block = "\n".join(warnings) + "\n"
    else:
        status_block = ""

    inc_block = f"\n💥 <b>СВОДКА:</b>\n{incident_text}\n" if incident_text else ""

    co_bankers_names = bank_data.get("co_banker_names", [])
    if co_bankers_names:
        owners_line = f"🏛 <b>Боссы:</b> {escape_html(bank_data.get('banker_name', '🦖'))} & 🤝 <b>{escape_html(', '.join(co_bankers_names))}</b>\n"
    else:
        owners_line = f"🏛 <b>Босс:</b> {escape_html(bank_data.get('banker_name', '🦖'))}\n"

    slogan_line = "<i>«Официальный партнёр Минсыра Табулистана: мусор вывезли, мрамор положили»</i>\n"

    text = (
        f"🏛 <b>{escape_html(name)}</b> <i>[КПП Табулистан • Плаза]</i>\n"
        f"{owners_line}"
        f"{slogan_line}"
        f"📡 <code>{ticker}</code>\n\n"
        f"💰 <b>Капитал банка:</b> {capital:,} сыр.\n"
        f"📈 <b>Ставка:</b> <b>{rate}%</b> в день <i>(элитный % для своих 👉👈)</i>\n\n"
        f"🏢 <b>СОСТОЯНИЕ ОСОБНЯКА И ГРАНИЦЫ:</b>\n"
        f"🏛 Фасад: [{_render_bar(durability)}] <b>{durability}%</b>\n"
        f"🔥 Ферма: [{_render_bar(fire_risk)}] <b>{fire_risk}%</b>\n"
        f"🦝 Еноты: [{_render_bar(rats)}] <b>{rats}%</b>\n"
        f"👵 Бабки: [{_render_bar(babki)}] <b>{babki}%</b>\n"
        f"🚓 Сидоренко: [{_render_bar(anger)}] <b>{anger}%</b>\n"
        f"🛂 Палево на КПП: [{_render_bar(border_heat)}] <b>{border_heat}%</b>\n"
        f"⚡ Подстанция: {power_status}\n"
        f"📜 Земля: {rent_status}\n"
        f"📦 Траншей: <b>{smuggle_runs}</b> | 🏆 Пережито ЧП: <b>{survived}</b>\n\n"
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
    """Формирует клавиатуру управления приграничным банком."""
    builder = InlineKeyboardBuilder()

    power = bank_data.get("power_grid", True)
    babki = int(bank_data.get("babki_queue", 35))
    fire = int(bank_data.get("fire_risk", 25))
    durability = int(bank_data.get("durability", 70))
    rats = int(bank_data.get("rats_infestation", 20))
    anger = int(bank_data.get("inspection_anger", 25))
    border_heat = int(bank_data.get("border_heat", 30))

    # Срочные аварийные кнопки первыми
    if not power:
        builder.button(text="⚡ Врубить автомат", callback_data=f"bshabby_power_{banker_id}")
    if fire >= 50:
        builder.button(text=f"🧯 Охладить ферму ({COST_EXTINGUISH//1000}k)", callback_data=f"bshabby_extinguish_{banker_id}")
    if babki >= 55:
        builder.button(text=f"☕ Раф бабкам ({COST_CALM_BABKI//1000}k)", callback_data=f"bshabby_calm_{banker_id}")
    if durability <= 65:
        builder.button(text=f"🏛 Подмазать мрамор ({COST_PATCH_ROOF//1000}k)", callback_data=f"bshabby_patch_{banker_id}")
    if rats >= 45:
        builder.button(text=f"🦝 Прогнать енотов ({COST_POISON_RATS//1000}k)", callback_data=f"bshabby_poison_{banker_id}")
    if anger >= 45:
        builder.button(text=f"💼 Доля Сидоренко ({COST_BRIBE_INSPECTOR//1000}k)", callback_data=f"bshabby_bribe_{banker_id}")
    if border_heat >= 45:
        builder.button(text=f"🛂 Занести таможне ({COST_CUSTOMS_DEAL//1000}k)", callback_data=f"bshabby_customs_{banker_id}")

    # Приграничная земля
    now = int(time.time())
    rent_until = bank_data.get("rent_paid_until", 0)
    if now >= rent_until:
        builder.button(text=f"📜 Оплатить участок ({COST_PAY_RENT//1000}k)", callback_data=f"bshabby_rent_{banker_id}")
    elif (rent_until - now) <= EARLY_RENT_PAY_SECONDS:
        builder.button(text=f"📜 Продлить участок ({COST_PAY_RENT//1000}k)", callback_data=f"bshabby_rent_{banker_id}")

    # Постоянные прикольчики приграничного особняка и Табулистана
    builder.button(text="📦 Серый транш (Табулистан)", callback_data=f"bshabby_smuggle_{banker_id}")
    builder.button(text=f"💱 Биржа тугрика ({COST_FOREX_BET//1000}k)", callback_data=f"bshabby_forex_{banker_id}")
    builder.button(text=f"🥗 Саммит Сыр-Табуле ({COST_FEAST//1000}k)", callback_data=f"bshabby_feast_{banker_id}")
    builder.button(text=f"✨ Люкс-клининг ({COST_LUX_CLEANING//1000}k)", callback_data=f"bshabby_clean_{banker_id}")

    # Стандартные банковские вкладки + Гайд
    builder.button(text="🔄 Обновить", callback_data=f"bstat_main_{banker_id}")
    builder.button(text="📖 Гайд босса", callback_data=f"bshabby_guide_{banker_id}")
    builder.button(text="👥 Вкладчики", callback_data=f"bstat_deps_{banker_id}")
    builder.button(text="🤝 Должники", callback_data=f"bstat_loans_{banker_id}")
    builder.button(text="⚙️ Настройки", callback_data=f"bstat_settings_{banker_id}")
    builder.button(text="⬆️ Улучшения", callback_data=f"bstat_upgrades_{banker_id}")
    builder.button(text="💼 Схемы", callback_data=f"bstat_schemes_{banker_id}")

    builder.adjust(2)
    return builder.as_markup()


def get_shabby_guide_text() -> str:
    """Возвращает гайд по управлению приграничным банком у Табулистана."""
    return (
        "📖 <b>ГАЙД БОССА: «ОСОБНЯК У ГРАНИЦЫ С ТАБУЛИСТАНОМ»</b>\n\n"
        "🏛 <b>Что изменилось после переезда:</b>\n"
        "Вы вылезли из нищеты, вывезли почти весь мусор и купили здание прямо у КПП Табулистана! "
        "Ставка <b>13.0% в день</b> по-прежнему разрывает рынок, здание ветшает медленнее, но появились новые приграничные движухи.\n\n"
        "📦 <b>Серый транш (Табулистан):</b>\n"
        "Раз в 20 минут можно прогнать фуру с элитным сыром через черный ход на границе. "
        "При успехе получаете <b>+120k–350k сыр.</b> прямо в капитал! Чем ниже <i>палево на таможне</i>, тем меньше шанс спалиться.\n\n"
        "💱 <b>Биржа тугрика (ТБЛ):</b>\n"
        "Раз в 25 минут можно поспекулировать на курсе табулистанского тугрика: поймать иксы на пампе или получить сдачу VIP-купонами для проверяющих.\n\n"
        "🥗 <b>Саммит «Сыр и Табуле»:</b>\n"
        "Главный дипломатический козырь Табулистана: накрываете поляну у шлагбаума — разом успокаиваете и таможню, и майора Сидоренко.\n\n"
        "✨ <b>Люкс-клининг:</b>\n"
        "Вызывает бригаду на Гелике — вывозит остатки мусора, натирает мрамор, отпугивает енотов и снижает палево на границе.\n\n"
        "🏢 <b>Показатели особняка:</b>\n"
        "🏛 <b>Евроремонт и фасад:</b> Ниже <b>15%</b> — посыплется лепнина и прием вкладов встанет.\n"
        "🔥 <b>Нагрузка майнинга:</b> Асики и джакузи в подвале. Выше <b>65%</b> — риск пожара.\n"
        "🦝 <b>Еноты с границы:</b> Вместо крыс из Табулистана лезут еноты-карманники и обчищают VIP-ложу.\n"
        "👵 <b>Очередь VIP-бабок:</b> Требуют раф на кокосовом и золотые карты. При <b>85%+</b> перекрывают вход!\n\n"
        "👥 <b>VIP-сервисный сбор:</b> При каждом благоустройстве с вкладчиков удерживается до 0.2% на содержание особняка!"
    )


def get_shabby_guide_kb(banker_id: int):
    """Клавиатура возврата из гайда."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в особняк", callback_data=f"bstat_main_{banker_id}")
    return builder.as_markup()


async def execute_shabby_repair(
    chat_id: int,
    banker_id: int,
    action: str,
    bank_data: Dict[str, Any]
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Выполняет действия и прикольчики банкира в приграничном особняке.
    Возвращает (успех, сообщение, словарь_обновлений).
    """
    capital = int(bank_data.get("capital", 0))

    if action == "extinguish":
        if capital < COST_EXTINGUISH:
            return False, f"❌ Нужно {COST_EXTINGUISH:,} сыр. в капитале на фреон и медные шины для подвала!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_EXTINGUISH - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        fire = max(5, int(bank_data.get("fire_risk", 25)) - random.randint(35, 55))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🧯 <b>Майнинг-ферма и джакузи охлаждены!</b>\nПоставили промышленный чиллер. Нагрузка упала до <b>{fire}%</b>!{dep_note}", {
            "capital": new_capital,
            "fire_risk": fire
        }

    elif action == "patch":
        if capital < COST_PATCH_ROOF:
            return False, f"❌ Нужно {COST_PATCH_ROOF:,} сыр. в капитале на табулистанский мрамор и герметик!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_PATCH_ROOF - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        durability = min(100, int(bank_data.get("durability", 70)) + random.randint(25, 40))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🏛 <b>Евроремонт обновлен!</b>\nЛепнину подкрасили позолотой, трещины затерли. Состояние фасада: <b>{durability}%</b>!{dep_note}", {
            "capital": new_capital,
            "durability": durability
        }

    elif action == "poison":
        if capital < COST_POISON_RATS:
            return False, f"❌ Нужно {COST_POISON_RATS:,} сыр. в капитале на ультразвук и откупные енотам!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_POISON_RATS - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        rats = max(5, int(bank_data.get("rats_infestation", 20)) - random.randint(35, 60))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🦝 <b>Еноты выдворены обратно в Табулистан!</b>\nДыру в заборе заварили арматурой. Набеги енотов снижены до <b>{rats}%</b>!{dep_note}", {
            "capital": new_capital,
            "rats_infestation": rats
        }

    elif action == "calm":
        if capital < COST_CALM_BABKI:
            return False, f"❌ Нужно {COST_CALM_BABKI:,} сыр. в капитале на раф на кокосовом и валидол!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_CALM_BABKI - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        babki = max(5, int(bank_data.get("babki_queue", 35)) - random.randint(35, 55))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"☕ <b>VIP-бабки задобрены рафом и круассанами!</b>\nОчередь мирно обсуждает курс табулистанского тугрика. Напряжение: <b>{babki}%</b>!{dep_note}", {
            "capital": new_capital,
            "babki_queue": babki
        }

    elif action == "bribe":
        if capital < COST_BRIBE_INSPECTOR:
            return False, f"❌ Нужно {COST_BRIBE_INSPECTOR:,} сыр. в капитале на конверт в бардачок майору Сидоренко!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_BRIBE_INSPECTOR - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"💼 <b>Майор Сидоренко доволен!</b>\n«Отличный особняк, по документам тут вообще библиотека». Аппетит проверки сброшен в 0!{dep_note}", {
            "capital": new_capital,
            "inspection_anger": 0
        }

    elif action == "customs":
        if capital < COST_CUSTOMS_DEAL:
            return False, f"❌ Нужно {COST_CUSTOMS_DEAL:,} сыр. в капитале на банкет для начальника заставы!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_CUSTOMS_DEAL - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        heat = max(0, int(bank_data.get("border_heat", 30)) - random.randint(45, 70))
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, f"🛂 <b>Вопросик на границе порешали!</b>\nПограничники Табулистана теперь смотрят строго в другую сторону. Палево снижено до <b>{heat}%</b>!{dep_note}", {
            "capital": new_capital,
            "border_heat": heat
        }

    elif action == "feast":
        if capital < COST_FEAST:
            return False, f"❌ Нужно {COST_FEAST:,} сыр. в капитале на пармезан, булгур и свежую петрушку!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_FEAST - dep_fee)
        new_capital = max(0, capital - cost_after_fee)

        heat = max(0, int(bank_data.get("border_heat", 30)) - random.randint(25, 40))
        anger = max(0, int(bank_data.get("inspection_anger", 25)) - random.randint(25, 40))
        tip = random.randint(25_000, 70_000) if random.random() < 0.35 else 0
        new_capital += tip

        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        tip_note = f"\n🎁 <i>Замминистра Табулистана оценил табуле с сыром и закинул чаевые: +{tip:,} сыр.!</i>" if tip > 0 else ""
        return True, (
            f"🥗 <b>САММИТ «СЫР И ТАБУЛЕ» ПРОШЕЛ НА УРА!</b>\n"
            f"За общим столом у шлагбаума братались пограничники Табулистана и майор Сидоренко.\n"
            f"🛂 Палево на таможне: <b>{heat}%</b> | 🚓 Аппетит Сидоренко: <b>{anger}%</b>"
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
            return False, f"⏳ Торги в столице Табулистана на обеде! Биржа тугрика откроется через <b>{mins_left} мин.</b>", {}

        if capital < COST_FOREX_BET:
            return False, f"❌ Нужно {COST_FOREX_BET:,} сыр. в капитале для входа на биржу Табулистана!", {}

        outcome = random.random()
        if outcome < 0.48:
            # ПАМП ТУГРИКА
            profit = random.randint(90_000, 220_000)
            return True, (
                f"📈 <b>ТУГРИК ТАБУЛИСТАНА УЛЕТЕЛ В КОСМОС!</b>\n"
                f"Минфин Табулистана объявил, что в каждой купюре ТБЛ зашито семечко элитного булгура — курс рванул вверх!\n"
                f"💰 Вы вовремя скинули котлету: <b>+{profit:,}</b> сыр. чистыми в капитал!"
            ), {
                "capital": capital + profit,
                "last_forex_time": now
            }
        elif outcome < 0.78:
            # ОБВАЛ ИЗ-ЗА НЕУРОЖАЯ ПЕТРУШКИ
            loss = min(capital, random.randint(25_000, 55_000))
            babki = max(0, int(bank_data.get("babki_queue", 35)) - 25)
            return True, (
                f"📉 <b>ТУГРИК РУХНУЛ НА НОВОСТЯХ О НЕУРОЖАЕ ПЕТРУШКИ!</b>\n"
                f"Вы потеряли <b>-{loss:,}</b> сыр. на курсе, но зато все бабки из очереди побежали скупать зелень на рынке!\n"
                f"👵 Очередь VIP-бабок снижена до <b>{babki}%</b>."
            ), {
                "capital": max(0, capital - loss),
                "babki_queue": babki,
                "last_forex_time": now
            }
        else:
            # ОТДАЛИ СДАЧУ VIP-КУПОНАМИ В АКВАПАРК ТАБУЛИСТАНА
            anger = max(0, int(bank_data.get("inspection_anger", 25)) - 20)
            heat = max(0, int(bank_data.get("border_heat", 30)) - 15)
            return True, (
                f"🎟 <b>НАЦБАНК ТАБУЛИСТАНА ВЕРНУЛ ДЕПОЗИТ VIP-КУПОНАМИ!</b>\n"
                f"Деньги вернулись в ноль, но вам отсыпали абонементы в аквапарк «Табулистан-Лэнд» — вы сразу раздали их проверяющим!\n"
                f"🚓 Аппетит Сидоренко: <b>{anger}%</b> | 🛂 Палево: <b>{heat}%</b>"
            ), {
                "inspection_anger": anger,
                "border_heat": heat,
                "last_forex_time": now
            }

    elif action == "clean":
        if capital < COST_LUX_CLEANING:
            return False, f"❌ Нужно {COST_LUX_CLEANING:,} сыр. в капитале на вызов люкс-клининга!", {}
        dep_fee = await collect_depositor_maintenance(chat_id, banker_id)
        cost_after_fee = max(0, COST_LUX_CLEANING - dep_fee)
        new_capital = max(0, capital - cost_after_fee)
        durability = min(100, int(bank_data.get("durability", 70)) + 15)
        rats = max(0, int(bank_data.get("rats_infestation", 20)) - 20)
        heat = max(0, int(bank_data.get("border_heat", 30)) - 15)
        dep_note = f"\n👥 <i>Сервисный сбор с вкладчиков: +{dep_fee:,} сыр.</i>" if dep_fee > 0 else ""
        return True, (
            f"✨ <b>Люкс-клининг отработал на 10/10!</b>\n"
            f"Вывезли последние мешки мусора, натерли мрамор до блеска, пахнет дорогим парфюмом.\n"
            f"🏛 Ремонт: <b>{durability}%</b> | 🦝 Еноты: <b>{rats}%</b> | 🛂 Палево: <b>{heat}%</b>{dep_note}"
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
            return False, f"⏳ Фура еще на загрузке в Табулистане! Следующий серый транш через <b>{mins_left} мин.</b>", {}

        if capital < 50_000:
            return False, "❌ Нужно минимум 50,000 сыр. в капитале на закупку партии через границу!", {}

        heat = int(bank_data.get("border_heat", 30))
        runs = int(bank_data.get("smuggle_runs", 0))
        fail_chance = min(0.75, 0.18 + (heat / 150.0))

        if random.random() >= fail_chance:
            profit = random.randint(120_000, 350_000)
            new_heat = min(100, heat + random.randint(12, 22))
            return True, (
                f"📦 <b>СЕРЫЙ ТРАНШ ПРОШЕЛ УСПЕШНО!</b>\n"
                f"Фура с элитным табулистанским сыром и специями проскочила через черный ход мимо поста!\n"
                f"💰 Чистый навар в капитал: <b>+{profit:,}</b> сыр.!\n"
                f"🛂 Палево на границе выросло до <b>{new_heat}%</b>."
            ), {
                "capital": capital + profit,
                "border_heat": new_heat,
                "last_smuggle_time": now,
                "smuggle_runs": runs + 1
            }
        else:
            fine = min(capital, random.randint(70_000, 140_000))
            new_heat = min(100, heat + 20)
            new_anger = min(100, int(bank_data.get("inspection_anger", 25)) + 15)
            return True, (
                f"🚨 <b>ГРУЗ ТОРМОЗНУЛИ НА НЕЙТРАЛКЕ!</b>\n"
                f"Таможня Табулистана вскрыла двойное дно в чемоданах — пришлось срочно откупаться!\n"
                f"💸 Потери капитала: <b>-{fine:,}</b> сыр. | 🛂 Палево: <b>{new_heat}%</b>"
            ), {
                "capital": max(0, capital - fine),
                "border_heat": new_heat,
                "inspection_anger": new_anger,
                "last_smuggle_time": now
            }

    elif action == "rent":
        if capital < COST_PAY_RENT:
            return False, f"❌ Нужно {COST_PAY_RENT:,} сыр. в капитале на оплату налога за приграничный участок!", {}
        now = int(time.time())
        rent_until_curr = bank_data.get("rent_paid_until", 0)
        if now < rent_until_curr and (rent_until_curr - now) > EARLY_RENT_PAY_SECONDS:
            hrs_left = (rent_until_curr - now) // 3600
            return False, f"⏳ Участок ещё оплачен (осталось {hrs_left} ч.). Продление доступно за {EARLY_RENT_PAY_SECONDS//3600} ч. до конца!", {}

        new_capital = capital - COST_PAY_RENT
        rent_until = max(now, rent_until_curr) + DAILY_RENT_SECONDS
        hrs_total = max(0, int((rent_until - now) // 3600))
        return True, f"📜 <b>Налог на приграничную землю продлен на 24 часа!</b>\nШлагбаум открыт ещё на {hrs_total} ч., погранцы машут рукой.", {
            "capital": new_capital,
            "rent_paid_until": rent_until
        }

    elif action == "power":
        chance = 0.80
        if random.random() < chance:
            return True, "⚡ <b>ЩЕЛК!</b>\nВы в дизайнерских резиновых перчатках врубили автомат! Неон снова сияет на весь Табулистан!", {
                "power_grid": True
            }
        else:
            shock = min(capital, 20_000)
            return True, f"⚡ <b>ШАРАХНУЛО ТОКОМ!</b>\nВыбило фазу, сгорел дорогой стабилизатор (-{shock:,} сыр.), но свет не зажегся. Жмите ещё раз!", {
                "capital": max(0, capital - shock),
                "power_grid": False
            }

    return False, "Неизвестное действие.", {}