"""Registered BEFORE legacy routers. No legacy handler/file is replaced."""
import logging
import time
from aiogram import Router, F
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from config import CREATOR_IDS
from v2 import settings, service, heist
from v2.model import RuleError, CAREERS, CRIMES, RESOURCES, level, event, market_price

router = Router(name="economy_v2")
log = logging.getLogger(__name__)


class Enabled(BaseFilter):
    async def __call__(self, message: Message):
        if not message.from_user or message.from_user.is_bot:
            return False
        return await settings.enabled(message.chat.id)


def args(text):
    return (text or "").split()[1:]


async def execute(chat, uid, operation):
    # Toggle and V2 mutations share a lock: no action can finish after an off
    # acknowledgement. Operation is a callable, never a pre-created coroutine.
    async with settings.switch_lock(chat):
        if not await settings.enabled(chat):
            raise RuleError("Новая экономика выключена в этом чате. Создатель: /v2 on")
        return await operation()


async def respond(message, operation):
    try:
        result = await execute(message.chat.id, message.from_user.id, operation)
    except RuleError as exc:
        return await message.answer(str(exc))
    return await message.answer(result)


@router.message(Command("v2"))
async def toggle(message: Message):
    if not message.from_user:
        return
    options = args(message.text)
    action = options[0].lower() if options else "status"
    if action not in ("on", "off", "status"):
        return await message.answer("/v2 on — включить; /v2 off — выключить; /v2 status — статус.")
    if action != "status" and message.from_user.id not in CREATOR_IDS:
        return await message.answer("Переключать версию может только создатель бота (CREATOR_ID).")
    async with settings.switch_lock(message.chat.id):
        if action != "status":
            await settings.set_enabled(message.chat.id, action == "on", message.from_user.id)
        on = await settings.enabled(message.chat.id)
    await message.answer(
        ("🧪 Казик 2.0 включён в этом чате. /eco — меню.\n/work, /crime и /steal теперь работают по новым правилам.\n"
         "⚠️ Балансы общие со старой версией: это не отдельная песочница. /v2 off вернёт старые обработчики, но не откатит операции.")
        if on else "Казик 2.0 выключен в этом чате. Работает прежняя версия. Данные прогресса 2.0 сохранены.")


def menu_keyboard(uid):
    rows = [
        [("💼 Работа", "work"), ("🎁 Награда", "daily")],
        [("🍄 Грибы", "mushroom"), ("🐟 Рыбалка", "fish"), ("⛏ Шахта", "ore")],
        [("🛡 Щит • 250", "shield"), ("🛏 Отдых", "rest")],
        [("📊 Обновить", "profile"), ("🏆 Забрать 500", "quest")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f"v2:menu:{uid}:{key}") for label, key in row
    ] for row in rows])


async def profile_text(chat, uid):
    data, s = await service.profile(chat, uid)
    career = s["career"]
    q = s["quests"]
    name, _, _ = event(chat, time.time())
    return (
        f"🍄 <b>КАЗИК 2.0 • Экономика</b>\n💰 {int(data.get('balance', 0))} сыр.\n"
        f"{CAREERS[career][0]} • ур. {level(s['xp'].get(career, 0))} • опыт {s['xp'].get(career, 0)}\n"
        f"⚡ {s['energy']}/100 • 🚨 {s['heat']}/100 • 🧰 {s['tools']}/5\n"
        f"🛡 Щит: {'активен' if s['shield_until'] > time.time() else 'нет'} • "
        f"🚔 Арест: {'да' if s['jail_until'] > time.time() else 'нет'}\n"
        f"🎁 Серия: {s['streak']}/7 • 📅 {name}\n\n"
        f"<b>Задания дня (UTC)</b>: работа {min(2, q.get('work', 0))}/2, "
        f"добыча {min(2, q.get('gather', 0))}/2, продажа {min(1, q.get('sell', 0))}/1\n"
        f"Награда: 500 сыр. {'✅ Получена' if s['quest_claimed'] else '— /quests claim'}\n\n"
        "/career — профессия • /tools — инструменты\n"
        "/crime — риск • /steal — кража ответом на сообщение\n"
        "/market — цены и ресурсы • /sell — продать\n"
        "/heist — кооперативный рейд • /bail — залог\n"
        "/ecohelp — все правила • Старые игры, банки и магазин остаются."
    )


@router.message(Command("eco"))
async def eco(message: Message):
    try:
        text = await execute(message.chat.id, message.from_user.id,
                             lambda: profile_text(message.chat.id, message.from_user.id))
    except RuleError as exc:
        return await message.answer(str(exc))
    await message.answer(text, reply_markup=menu_keyboard(message.from_user.id))


@router.message(Command("ecohelp"), Enabled())
async def help_v2(message: Message):
    await message.answer(
        "🧪 <b>Казик 2.0 — правила</b>\n"
        "💼 /work — смена раз в 30 мин, 8/12/16 энергии (курьер/механик/аналитик). Премия: ответить за 90 секунд.\n"
        "/career courier|mechanic|analyst — профессия. 25 опыта/смену, новый уровень каждые 100 опыта (макс. 20). Аналитик получает повышенную премию за задачу.\n"
        "/tools — купить уровень инструмента (макс. 5), цена 700 × новый уровень. Бонус зарплаты/ур.: курьер +20, механик +60, аналитик +35.\n"
        "🥷 /crime pickpocket|burglary|convoy — риск раз в час, 18 энергии; чем выше розыск, тем ниже шанс.\n"
        "/steal или «украсть» ответом на сообщение — 15 энергии, раз в час. Нужны 300 сыр.; добыча до 8% баланса цели, максимум 800.\n"
        "Цели: не боты/админы/создатели; не меньше 1000 сыр. Новички 2.0 защищены 24 часа, после попытки цель защищена 2 часа.\n"
        "Щит /shield: 250 сыр./24 часа; бункер тоже защищает. Твоя атака снимает твой щит и защиту новичка.\n"
        "Погоня жертвы: 2 минуты, возврат ограничен текущим балансом вора.\n"
        "🍄 /gather mushroom|fish|ore — ресурсы каждые 20 мин, общий откат, 8 энергии.\n"
        "/market — дневные цены; /sell mushroom all или /sell fish 3 — продажа.\n"
        "🎁 /daily — награда раз в день UTC, серия до 7 дней. /bonus остаётся прежним.\n"
        "/quests claim — 500 сыр. за 2 смены, 2 добычи и продажу за день UTC.\n"
        "🤝 /heist create|join|start|cancel — команда 2–5 человек, 20 энергии, откат 2 часа, без взноса.\n"
        "⚡ +5 энергии/10 мин, максимум 100. /rest: +20 энергии и −10 розыска раз в час.\n"
        "🚨 −1 розыска/7,5 мин; от 80 — арест на 15 мин. /bail — 400 + розыск × 5.\n"
        "В 2.0 свои выплаты: старые сезонные случайные награды, коллекторы и лобби не применяются к новым заработкам. "
        "Налог, переговоры, кот на работе, лиса/отмычка/маска при краже учитываются.\n"
        "⚠️ Общий игровой баланс, не песочница. Отключение 2.0 не отменяет операции."
    )


async def send_work(message, uid):
    text, nonce, choices = await execute(message.chat.id, uid, lambda: service.work(message.chat.id, uid))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(n), callback_data=f"v2:task:{uid}:{nonce}:{n}") for n in choices
    ]])
    await message.answer(text, reply_markup=kb)


@router.message(Command("work"), Enabled())
async def work(message: Message):
    try:
        await send_work(message, message.from_user.id)
    except RuleError as exc:
        await message.answer(str(exc))


@router.message(Command("career"), Enabled())
async def career(message: Message):
    options = args(message.text)
    await respond(message, lambda: service.career(message.chat.id, message.from_user.id, options[0] if options else ""))


@router.message(Command("crime"), Enabled())
async def crime(message: Message):
    options = args(message.text)
    if not options:
        text = "🥷 <b>Выбери преступление</b>\n"
        for key, (name, chance, low, high, heat, fine) in CRIMES.items():
            text += f"/crime {key} — {name}: база {int(chance * 100)}%, куш {low}–{high}, розыск +{heat}, штраф до {fine}.\n"
        return await message.answer(text + "Розыск снижает шанс; навык скрытности повышает его. Все варианты: общий откат 1 час.")
    await respond(message, lambda: service.crime(message.chat.id, message.from_user.id, options[0]))


@router.message(Command("gather"), Enabled())
async def gather(message: Message):
    options = args(message.text)
    await respond(message, lambda: service.gather(message.chat.id, message.from_user.id, options[0] if options else ""))


@router.message(Command("market"), Enabled())
async def market(message: Message):
    async def show():
        _, s = await service.profile(message.chat.id, message.from_user.id)
        text = "📦 <b>Рынок • цены на сегодня (UTC)</b>\n"
        for key, (name, _, _, _) in RESOURCES.items():
            text += f"{name}: {market_price(message.chat.id, key, time.time())} сыр./шт. • у тебя {s['resources'].get(key, 0)}\n"
        return text + "Цены до налога. /sell mushroom all или /sell fish 3"
    await respond(message, show)


@router.message(Command("sell"), Enabled())
async def sell(message: Message):
    options = args(message.text)
    await respond(message, lambda: service.sell(message.chat.id, message.from_user.id,
                  options[0] if options else "", options[1] if len(options) > 1 else "all"))


@router.message(Command("daily"), Enabled())
async def daily(message: Message):
    await respond(message, lambda: service.daily(message.chat.id, message.from_user.id))


@router.message(Command("quests"), Enabled())
async def quests(message: Message):
    if args(message.text) != ["claim"]:
        return await eco(message)
    await respond(message, lambda: service.quest_claim(message.chat.id, message.from_user.id))


@router.message(Command("shield", "tools", "bail"), Enabled())
async def buy(message: Message):
    key = message.text.split()[0].split("@")[0][1:]
    await respond(message, lambda: service.purchase(message.chat.id, message.from_user.id, key))


@router.message(Command("rest"), Enabled())
async def rest(message: Message):
    await respond(message, lambda: service.rest(message.chat.id, message.from_user.id))


@router.message(Command("heist"), Enabled())
async def raid(message: Message):
    options = args(message.text)
    await respond(message, lambda: heist.run(message.chat.id, message.from_user.id, options[0] if options else ""))


@router.message(Command("steal"), Enabled())
@router.message(F.text.lower().regexp(r"^украсть(?:\s|$)"), Enabled())
async def steal(message: Message):
    reply = message.reply_to_message
    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("Кражи доступны только в группе.")
    if not reply or not reply.from_user or reply.sender_chat or reply.from_user.is_bot:
        return await message.answer("Ответь командой /steal на сообщение игрока (не бота и не анонимного администратора).")
    target = reply.from_user.id
    if target in CREATOR_IDS:
        return await message.answer("Создатель защищён от краж.")
    # Fail closed: an API error must not bypass administrator immunity.
    try:
        member = await message.bot.get_chat_member(message.chat.id, target)
    except Exception:
        log.warning("Cannot verify V2 theft target administrator status", exc_info=True)
        return await message.answer("Не удалось проверить защиту участника. Кража не выполнена, попробуй позже.")
    if member.status in ("administrator", "creator"):
        return await message.answer("Администрация защищена от краж.")
    try:
        text, nonce = await execute(message.chat.id, message.from_user.id,
                                    lambda: service.steal(message.chat.id, message.from_user.id, target))
    except RuleError as exc:
        return await message.answer(str(exc))
    kb = None
    if nonce:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚓 Жертва: начать погоню", callback_data=f"v2:chase:{target}:{nonce}")
        ]])
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("v2:"))
async def callbacks(callback: CallbackQuery):
    # Every button binds the actor; parsed IDs are never trusted as authorization.
    if not callback.message or not isinstance(callback.message, Message):
        return await callback.answer("Сообщение недоступно.", show_alert=True)
    parts = (callback.data or "").split(":")
    try:
        if len(parts) < 4 or int(parts[2]) != callback.from_user.id:
            raise RuleError("Эта кнопка предназначена другому игроку.")
        action, uid, chat = parts[1], callback.from_user.id, callback.message.chat.id
        if action == "task" and len(parts) == 5:
            result = await execute(chat, uid, lambda: service.solve_task(chat, uid, parts[3], int(parts[4])))
        elif action == "chase" and len(parts) == 4:
            result = await execute(chat, uid, lambda: service.chase(chat, uid, parts[3]))
        elif action == "menu" and len(parts) == 4:
            key = parts[3]
            if key == "work":
                # Acknowledge before sending a separate work message; the menu remains usable.
                await callback.answer()
                try:
                    await send_work(callback.message, uid)
                except RuleError as exc:
                    await callback.message.answer(str(exc))
                return
            operations = {
                "daily": lambda: service.daily(chat, uid),
                "rest": lambda: service.rest(chat, uid),
                "shield": lambda: service.purchase(chat, uid, "shield"),
                "quest": lambda: service.quest_claim(chat, uid),
                "profile": lambda: profile_text(chat, uid),
            }
            if key in RESOURCES:
                operation = lambda: service.gather(chat, uid, key)
            else:
                operation = operations.get(key)
            if operation is None:
                raise RuleError("Неизвестная кнопка.")
            result = await execute(chat, uid, operation)
        else:
            raise RuleError("Кнопка устарела.")
    except (ValueError, IndexError):
        return await callback.answer("Некорректная кнопка.", show_alert=True)
    except RuleError as exc:
        return await callback.answer(str(exc)[:200], show_alert=True)
    await callback.answer()
    if action in ("task", "chase"):
        # Payment already happened. A failed edit must not trigger another payment.
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
    if action == "menu" and parts[3] == "profile":
        try:
            await callback.message.edit_text(result, reply_markup=menu_keyboard(uid))
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    else:
        await callback.message.answer(result)
