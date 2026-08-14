from aiogram import Router, types, Bot, F
from aiogram.filters import Command, or_f

from db import get_db
from user_manager import get_user_data, update_user_balance
from config import CREATOR_ID, CREATOR_USERNAME, CREATOR_IDS
from escape import escape_html

router = Router()

def is_creator(message: types.Message):
    user_id = message.from_user.id
    if int(user_id) in CREATOR_IDS:
        return True
    return False

# ================= БАНКИРЫ И СОФТ-ВАЙП =================

@router.message(Command("setbanker"))
async def cmd_setbanker(message: types.Message):
    if not is_creator(message):
        return
    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение будущего Банкира.")

    chat_id = message.chat.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    from user_manager import update_user_field
    await get_user_data(chat_id, target_id, target_name)
    await update_user_field(chat_id, target_id, 'is_banker', True)
    
    await message.answer(f"💼 Пользователь <b>{target_name}</b> назначен официальным <b>Банкиром</b>!\nТеперь у него нет доступа к казино и работам, но он получает 50.000.000 в день и может кредитовать игроков.")
    from log_system import log_action
    log_action(f"💼 <b>Назначен банкир:</b> {message.from_user.full_name} ({message.from_user.id}) назначил {target_name} ({target_id}) банкиром в чате {chat_id}")

@router.message(Command("delbanker"))
async def cmd_delbanker(message: types.Message):
    if not is_creator(message):
        return
    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение Банкира.")

    chat_id = message.chat.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    from user_manager import update_user_field
    await get_user_data(chat_id, target_id, target_name)
    await update_user_field(chat_id, target_id, 'is_banker', False)
    
    await message.answer(f"❌ Пользователь <b>{target_name}</b> снят с должности Банкира и возвращен к обычной жизни.")
    from log_system import log_action
    log_action(f"❌ <b>Снят банкир:</b> {message.from_user.full_name} ({message.from_user.id}) снял {target_name} ({target_id}) с должности банкира в чате {chat_id}")

@router.message(Command("wipe_balances"))
async def cmd_wipe_balances(message: types.Message):
    if not is_creator(message):
        return await message.answer("❌ Отказано в доступе. Только Создатель.")

    args = message.text.split()
    if len(args) < 2 or args[1] != "CONFIRM":
        return await message.answer(
            "⚠️ <b>ВНИМАНИЕ! СОФТ-ВАЙП ЭКОНОМИКИ (ТОЛЬКО ДЕНЬГИ)!</b> ⚠️\n\n"
            "Это действие обнулит ТОЛЬКО балансы и вклады всех игроков до 500 сыроежек.\n"
            "💼 <b>Сохранятся:</b> Машины, бизнесы, питомцы, крипта, кланы, скиллы и долги.\n\n"
            "Если вы УВЕРЕНЫ, введите команду:\n"
            "<code>/wipe_balances CONFIRM</code>"
        )

    status_msg = await message.answer("🔄 <i>Начинаю сброс балансов...</i>")

    import time
    from user_manager import _user_cache
    db = get_db()
    _user_cache.clear() # Очищаем кэш

    from whitelist import get_whitelist
    whitelist_dict = await get_whitelist()
    users_wiped = 0

    for chat_id in whitelist_dict.keys():
        try:
            users_ref = db.collection('chats').document(str(chat_id)).collection('users')
            user_docs = await users_ref.get()
            
            batch = db.batch()
            count = 0
            for doc in user_docs:
                doc_id = getattr(doc, 'id', None)
                if doc_id:
                    # Обнуляем только деньги
                    batch.set(users_ref.document(doc_id), {
                        'balance': 500,
                        'bank_deposit': 0
                    }, merge=True)
                    users_wiped += 1
                    count += 1
                    if count >= 500:
                        await batch.commit()
                        batch = db.batch()
                        count = 0
            if count > 0:
                await batch.commit()
                
        except Exception as e:
            print(f"Ошибка при софт-вайпе чата {chat_id}: {e}")

    await status_msg.edit_text(f"✅ <b>БАЛАНСЫ УСПЕШНО СБРОШЕНЫ!</b>\n\n👤 Обнулено денег у игроков: <b>{users_wiped}</b>.\nИмущество и инвентари сохранены.")
    from log_system import log_action
    log_action(f"🚨🚨🚨 <b>Софт-вайп балансов:</b> {message.from_user.full_name} ({message.from_user.id}) сбросил балансы {users_wiped} игроков")

# ================= СТАРЫЕ КОМАНДЫ СОЗДАТЕЛЯ =================

@router.message(Command("addmoney", "give"))
async def cmd_addmoney(message: types.Message):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите сумму.")
        return

    try:
        amount = int(args[1])
        chat_id = message.chat.id
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)

        await get_user_data(chat_id, target_id, target_name)
        await update_user_balance(chat_id, target_id, amount)
        await message.answer(f"Выдано {amount} сыроежек пользователю {target_name}.")
        from log_system import log_action
        log_action(f"💰 <b>Выдача денег:</b> {message.from_user.full_name} ({message.from_user.id}) выдал <code>{amount:,}</code> сыроежек пользователю {target_name} ({target_id}) в чате {chat_id}")
    except ValueError:
        pass


async def _resolve_user_target(chat_id, target_str: str, message: types.Message = None):
    """Находит chat_id и target_id по реплаю, ID или @username."""
    if target_str:
        clean = target_str.strip().lstrip("@")
        if clean.isdigit():
            uid = int(clean)
            data = await get_user_data(chat_id, uid)
            return chat_id, uid, data.get("full_name", f"User {uid}"), data.get("username", "")

        # Поиск по username в текущем чате
        db = get_db()
        uname = clean.lower()
        try:
            docs = await db.collection("chats").document(str(chat_id)).collection("users").get()
            for doc in docs:
                d = doc.to_dict() or {}
                if str(d.get("username", "")).lower() == uname:
                    return chat_id, int(doc.id), d.get("full_name", uname), d.get("username", uname)
        except Exception:
            pass

        # Поиск по username по всем вайтлист-чатам
        try:
            from whitelist import get_whitelist
            wl = await get_whitelist()
            for cid in wl.keys():
                docs = await db.collection("chats").document(str(cid)).collection("users").get()
                for doc in docs:
                    d = doc.to_dict() or {}
                    if str(d.get("username", "")).lower() == uname:
                        return int(cid), int(doc.id), d.get("full_name", uname), d.get("username", uname)
        except Exception:
            pass

    if message and message.reply_to_message:
        u = message.reply_to_message.from_user
        return chat_id, u.id, u.full_name, u.username or ""

    return None, None, None, None


@router.message(Command("finduser", "найти_игрока", "найти_юзера"))
async def cmd_find_user(message: types.Message):
    if not is_creator(message):
        return

    args = message.text.split(maxsplit=1)
    target_str = args[1] if len(args) > 1 else ""
    t_chat_id, t_uid, t_name, t_uname = await _resolve_user_target(message.chat.id, target_str, message)
    if not t_uid:
        return await message.answer("❌ Пользователь не найден. Укажите @username, ID или ответьте на сообщение.")

    u_data = await get_user_data(t_chat_id, t_uid)
    inv = u_data.get("inventory") or {}
    from shop import ITEMS
    inv_str = "\n".join([f" • {ITEMS.get(k, {}).get('name', k)}: <b>{v} шт.</b>" for k, v in inv.items()]) or "<i>пусто</i>"

    text = (
        f"🔍 <b>Информация об игроке</b>\n"
        f"👤 Имя: <b>{escape_html(t_name)}</b> (@{t_uname})\n"
        f"🆔 ID: <code>{t_uid}</code> | Чат: <code>{t_chat_id}</code>\n"
        f"💰 Баланс: <b>{u_data.get('balance', 0):,}</b> сыр.\n"
        f"🏦 Банк: <b>{u_data.get('bank_deposit', 0):,}</b> сыр.\n"
        f"🎖 Престиж: <b>{u_data.get('prestige_level', 0)}</b>\n\n"
        f"🎒 <b>Инвентарь:</b>\n{inv_str}"
    )
    await message.answer(text)


DICTORS_LIST = [
    ("dictor_common", "1. Обычный диктор"),
    ("dictor_simple", "2. Простой диктор"),
    ("dictor_basic", "3. Базовый диктор"),
    ("dictor_uncommon", "4. Необычный диктор"),
    ("dictor_rare", "5. Редкий диктор"),
    ("dictor_epic", "6. Эпический диктор"),
    ("dictor_legendary", "7. Легендарный диктор"),
    ("dictor_mythic", "8. Мифический диктор"),
    ("dictor_cosmic", "9. Космический диктор"),
    ("dictor_divine", "10. Божественный диктор"),
    ("dictor_shadow", "11. Теневой диктор"),
    ("dictor_abyss", "12. Диктор бездны"),
    ("dictor_elder", "13. Древний диктор"),
    ("dictor_chaos", "14. Диктор хаоса"),
    ("dictor_void", "15. Диктор пустоты"),
    ("dictor_infinity", "16. Бесконечный диктор"),
    ("dictor_secret", "17. Секретный диктор"),
    ("dictor_emperor", "18. Императорский диктор"),
    ("dictor_ghost", "19. Призрачный диктор"),
    ("dictor_immortal", "20. Бессмертный диктор"),
    ("dictor_celestial", "21. Небесный диктор"),
    ("dictor_astral", "22. Астральный диктор"),
    ("dictor_quantum", "23. Квантовый диктор"),
    ("dictor_singularity", "24. Сингулярный диктор"),
    ("dictor_supernova", "25. Сверхновый диктор"),
    ("dictor_nebula", "26. Туманный диктор"),
    ("dictor_hyperion", "27. Гиперионский диктор"),
    ("dictor_chronos", "28. Хронос-диктор"),
    ("dictor_aether", "29. Эфирный диктор"),
    ("dictor_primordial", "30. Первозданный диктор"),
    ("dictor_supreme", "31. Верховный диктор"),
    ("dictor_archon", "32. Архонтский диктор"),
    ("dictor_seraph", "33. Серафимский диктор"),
    ("dictor_leviathan", "34. Левиафанский диктор"),
    ("dictor_phoenix", "35. Феникс-диктор"),
    ("dictor_titan", "36. Титанический диктор"),
    ("dictor_valkyrie", "37. Валькирийский диктор"),
    ("dictor_overlord", "38. Владыка-диктор"),
    ("dictor_omega", "39. Омега-диктор"),
    ("dictor_alpha", "40. Альфа-диктор"),
    ("dictor_multiverse", "41. Мультивселенский диктор"),
    ("dictor_transcendent", "42. Трансцендентный диктор"),
    ("dictor_omnipotent", "43. Всемогущий диктор"),
    ("dictor_absolute", "44. Абсолютный диктор"),
    ("dictor_infinity_plus", "45. Сверхбесконечный диктор"),
    ("dictor_dark_matter", "46. Тёмноматериальный диктор"),
    ("dictor_dark_energy", "47. Тёмноэнергетический диктор"),
    ("dictor_antimatter", "48. Антиматериальный диктор"),
    ("dictor_hyperdimensional", "49. Гиперпространственный диктор"),
    ("dictor_zenith", "50. Зенитный диктор"),
    ("dictor_apex", "51. Апекс-диктор"),
    ("dictor_genesis", "52. Генезис-диктор"),
    ("dictor_apocalypse", "53. Апокалиптический диктор"),
    ("dictor_ragnarok", "54. Рагнарёк-диктор"),
    ("dictor_valhalla", "55. Вальхалла-диктор"),
    ("dictor_olympus", "56. Олимпский диктор"),
    ("dictor_asgard", "57. Асгардский диктор"),
    ("dictor_eldritch", "58. Иномировой диктор"),
    ("dictor_cthulhu", "59. Ктулхический диктор"),
    ("dictor_solaris", "60. Солярис-диктор"),
    ("dictor_lunar", "61. Лунный диктор"),
    ("dictor_eclipse", "62. Затменный диктор"),
    ("dictor_supernatural", "63. Сверхестественный диктор"),
    ("dictor_boundless", "64. Безграничный диктор"),
    ("dictor_eternity", "65. Вечность-диктор"),
    ("dictor_creation", "66. Созидательный диктор"),
    ("dictor_destruction", "67. Разрушительный диктор"),
    ("dictor_sovereign", "68. Суверенный диктор"),
    ("dictor_godlike", "69. Богоподобный диктор"),
    ("dictor_antigravity", "70. Антигравитационный диктор"),
]


def resolve_dictor_id(query: str) -> str:
    """Умное сопоставление строки с ID Диктора (по номеру 1..70 или имени)."""
    q = query.strip().lower()
    if q.isdigit():
        num = int(q)
        if 1 <= num <= len(DICTORS_LIST):
            return DICTORS_LIST[num - 1][0]

    # Прямое совпадение
    for item_id, title in DICTORS_LIST:
        if q == item_id or q == item_id.removeprefix("dictor_"):
            return item_id

    # Поиск по подстроке
    for item_id, title in DICTORS_LIST:
        if q in item_id or q in title.lower():
            return item_id

    return query


@router.message(Command("dictors", "дикторы", "список_дикторов"))
async def cmd_dictors_catalog(message: types.Message):
    """Интерактивный просмотр всех 70 Дикторов с номерами и ID."""
    args = message.text.split()
    page = int(args[1]) - 1 if len(args) > 1 and args[1].isdigit() else 0

    page_size = 10
    total_pages = (len(DICTORS_LIST) + page_size - 1) // page_size
    page = max(0, min(page, total_pages - 1))
    start_idx = page * page_size
    slice_items = DICTORS_LIST[start_idx:start_idx + page_size]

    lines = []
    for item_id, title in slice_items:
        lines.append(f"• <b>{title}</b> — <code>{item_id}</code>")

    text = (
        f"🐰 <b>КАТАЛОГ ДИКТОРОВ ТАЙНИЙ БАНИЙ</b> (Всего 70 рангов)\n"
        f"Страница: <b>{page + 1}/{total_pages}</b>\n\n"
        + "\n".join(lines) +
        f"\n\n💡 <i>Чтобы выдать:</i> <code>/givedictor @username &lt;номер_или_id&gt;</code>\n"
        f"<i>Пример:</i> <code>/givedictor @Dictor_mladshu 70</code>"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if total_pages > 1:
        prev_p = max(0, page - 1) + 1
        next_p = min(total_pages - 1, page + 1) + 1
        builder.button(text="◀️ Назад", callback_data=f"cr_dictors_p_{prev_p}")
        builder.button(text=f"Стр. {page + 1}/{total_pages}", callback_data="noop")
        builder.button(text="Вперед ▶️", callback_data=f"cr_dictors_p_{next_p}")
    builder.adjust(3)

    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("cr_dictors_p_"))
async def cb_dictors_page(callback: types.CallbackQuery):
    p_str = callback.data.removeprefix("cr_dictors_p_")
    page = int(p_str) - 1 if p_str.isdigit() else 0

    page_size = 10
    total_pages = (len(DICTORS_LIST) + page_size - 1) // page_size
    page = max(0, min(page, total_pages - 1))
    start_idx = page * page_size
    slice_items = DICTORS_LIST[start_idx:start_idx + page_size]

    lines = []
    for item_id, title in slice_items:
        lines.append(f"• <b>{title}</b> — <code>{item_id}</code>")

    text = (
        f"🐰 <b>КАТАЛОГ ДИКТОРОВ ТАЙНИЙ БАНИЙ</b> (Всего 70 рангов)\n"
        f"Страница: <b>{page + 1}/{total_pages}</b>\n\n"
        + "\n".join(lines) +
        f"\n\n💡 <i>Чтобы выдать:</i> <code>/givedictor @username &lt;номер_или_id&gt;</code>\n"
        f"<i>Пример:</i> <code>/givedictor @Dictor_mladshu 70</code>"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if total_pages > 1:
        prev_p = max(0, page - 1) + 1
        next_p = min(total_pages - 1, page + 1) + 1
        builder.button(text="◀️ Назад", callback_data=f"cr_dictors_p_{prev_p}")
        builder.button(text=f"Стр. {page + 1}/{total_pages}", callback_data="noop")
        builder.button(text="Вперед ▶️", callback_data=f"cr_dictors_p_{next_p}")
    builder.adjust(3)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.message(Command("giveitem", "givedictor", "выдать_предмет", "выдать_диктора"))
async def cmd_give_item(message: types.Message):
    if not is_creator(message):
        return

    # Форматы:
    # 1. Реплай: /giveitem <item_id> [count]
    # 2. По юзеру: /giveitem @username <item_id> [count]
    args = message.text.split()
    if len(args) < 2:
        return await message.answer(
            "<b>Использование команды выдачи:</b>\n\n"
            "• По нику/ID: <code>/givedictor @username &lt;номер_1..70_или_id&gt; [кол-во]</code>\n"
            "• Выдать ВСЕХ 70 дикторов сразу: <code>/givedictor @username all</code>\n"
            "• В ответ на сообщение: <code>/givedictor &lt;номер_или_id&gt; [кол-во]</code>\n\n"
            "<i>Примеры:</i>\n"
            " • <code>/givedictor @Dictor_mladshu 70</code> (выдаст Антигравити-диктора)\n"
            " • <code>/givedictor @Dictor_mladshu all</code> (выдаст по 1 шт каждого из 70 дикторов)\n"
            " • <code>/givedictor @Dictor_mladshu 1 5</code> (выдаст 5 шт Обычных дикторов)"
        )

    from user_manager import add_item_to_inventory, invalidate_user_cache
    from shop import ITEMS

    target_str = ""
    raw_item = ""
    count = 1

    # Умный разбор аргументов:
    # 1. Если args[1] начинается с @ или len(args) >= 3 и args[1] не число:
    if len(args) > 1 and args[1].startswith("@"):
        target_str = args[1]
        raw_item = args[2].lower() if len(args) > 2 else "70"
        count = int(args[3]) if len(args) > 3 and args[3].isdigit() else 1
    elif message.reply_to_message:
        target_str = ""
        raw_item = args[1].lower() if len(args) > 1 else "70"
        count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 1
    elif len(args) >= 3:
        target_str = args[1]
        raw_item = args[2].lower()
        count = int(args[3]) if len(args) > 3 and args[3].isdigit() else 1
    else:
        # Без реплая и без явного @user: если это номер/ID предмета, выдаём самому Создателю
        target_str = str(message.from_user.id)
        raw_item = args[1].lower() if len(args) > 1 else "70"
        count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 1

    if not raw_item:
        raw_item = "70"

    t_chat_id, t_uid, t_name, t_uname = await _resolve_user_target(message.chat.id, target_str, message)
    if not t_uid:
        return await message.answer("❌ Пользователь не найден. Проверьте правильность @username или ID.")

    # Выдача ВСЕХ дикторов
    if raw_item in ("all", "все", "всё"):
        given_count = 0
        for d_id, _ in DICTORS_LIST:
            if await add_item_to_inventory(t_chat_id, t_uid, d_id, count=count):
                given_count += 1
        invalidate_user_cache(t_chat_id, t_uid)
        from log_system import log_action
        log_action(f"👑 <b>Выдача ВСЕХ дикторов:</b> {message.from_user.full_name} выдал полный комплект из 70 дикторов x{count} для {t_name} ({t_uid})")
        return await message.answer(
            f"👑 <b>ПОЛНЫЙ КОМПЛЕКТ ДИКТОРОВ ВЫДАН!</b>\n\n"
            f"👤 Получатель: <b>{escape_html(t_name)}</b> (@{t_uname})\n"
            f"🐰 Выдано: <b>все 70 рангов Дикторов</b> по <b>{count} шт.</b>!"
        )

    item_id = resolve_dictor_id(raw_item)
    success = await add_item_to_inventory(t_chat_id, t_uid, item_id, count=count)
    if success:
        invalidate_user_cache(t_chat_id, t_uid)
        item_name = ITEMS.get(item_id, {}).get("name", item_id)
        await message.answer(
            f"✅ <b>Предмет успешно выдан!</b>\n"
            f"👤 Получатель: <b>{escape_html(t_name)}</b> (@{t_uname})\n"
            f"🎁 Выдано: <b>{item_name}</b> (<code>{item_id}</code>) x{count} шт."
        )
        from log_system import log_action
        log_action(f"🎁 <b>Выдача предмета Создателем:</b> {message.from_user.full_name} выдал {item_name} x{count} для {t_name} ({t_uid})")
    else:
        await message.answer(f"❌ Ошибка: предмет <code>{item_id}</code> не найден в каталоге.")


@router.message(Command("givetopdictor", "топдиктор", "выдать_топ_диктора", "лучший_диктор", "антигравити", "antigravity", "topdictor"))
async def cmd_give_top_dictor(message: types.Message):
    """Мгновенная выдача самого крутого Диктора (#70 Антигравитационный диктор)."""
    if not is_creator(message):
        return

    from user_manager import add_item_to_inventory, invalidate_user_cache
    from shop import ITEMS

    args = message.text.split()
    count = 1
    target_str = ""

    if message.reply_to_message:
        if len(args) > 1 and args[1].isdigit():
            count = int(args[1])
    else:
        if len(args) > 1:
            target_str = args[1]
            if len(args) > 2 and args[2].isdigit():
                count = int(args[2])
        else:
            # Если без аргументов и без реплая — выдаём самому Создателю!
            target_str = str(message.from_user.id)

    t_chat_id, t_uid, t_name, t_uname = await _resolve_user_target(message.chat.id, target_str, message)
    if not t_uid:
        return await message.answer("❌ Пользователь не найден. Укажите @username, ID или ответьте на сообщение игрока.")

    top_dictor_id = "dictor_antigravity"
    success = await add_item_to_inventory(t_chat_id, t_uid, top_dictor_id, count=count)
    if success:
        invalidate_user_cache(t_chat_id, t_uid)
        top_name = ITEMS.get(top_dictor_id, {}).get("name", "🌌 Антигравитационный диктор")
        from log_system import log_action
        log_action(f"👑 <b>Выдача САМОГО КРУТОГО ДИКТОРА:</b> {message.from_user.full_name} выдал {top_name} x{count} для {t_name} ({t_uid})")
        await message.answer(
            f"👑 <b>САМЫЙ КРУТОЙ ДИКТОР ВО ВСЕЛЕННОЙ ВЫДАН!</b>\n\n"
            f"👤 Получатель: <b>{escape_html(t_name)}</b> (@{t_uname})\n"
            f"🆔 ID: <code>{t_uid}</code>\n\n"
            f"🐰 Диктор: <b>{top_name}</b> (<code>{top_dictor_id}</code>)\n"
            f"🌟 Ранг: <b>#70 / 70 (Максимальный Тир)</b>\n"
            f"🔢 Количество: <b>{count} шт.</b>\n"
            f"🛡 <i>Полная 100% защита от всех сбросов, вайпов и престижей!</i>"
        )
    else:
        await message.answer("❌ Ошибка при выдаче диктора.")


@router.message(Command("givetop5dictors", "топ5дикторов", "топ5"))
async def cmd_give_top5_dictors(message: types.Message):
    """Выдача комплекта из ТОП-5 сильнейших Дикторов (ранги 66-70)."""
    if not is_creator(message):
        return

    from user_manager import add_item_to_inventory, invalidate_user_cache
    from shop import ITEMS

    args = message.text.split()
    count = 1
    target_str = ""

    if message.reply_to_message:
        if len(args) > 1 and args[1].isdigit():
            count = int(args[1])
    else:
        if len(args) > 1:
            target_str = args[1]
            if len(args) > 2 and args[2].isdigit():
                count = int(args[2])
        else:
            target_str = str(message.from_user.id)

    t_chat_id, t_uid, t_name, t_uname = await _resolve_user_target(message.chat.id, target_str, message)
    if not t_uid:
        return await message.answer("❌ Пользователь не найден. Укажите @username, ID или ответьте на сообщение игрока.")

    top5_ids = [
        "dictor_creation",       # 66
        "dictor_destruction",    # 67
        "dictor_sovereign",      # 68
        "dictor_godlike",        # 69
        "dictor_antigravity",    # 70
    ]

    for d_id in top5_ids:
        await add_item_to_inventory(t_chat_id, t_uid, d_id, count=count)
    invalidate_user_cache(t_chat_id, t_uid)

    from log_system import log_action
    log_action(f"👑 <b>Выдача ТОП-5 ДИКТОРОВ:</b> {message.from_user.full_name} выдал ТОП-5 дикторов x{count} для {t_name} ({t_uid})")

    lines = [f" • {ITEMS.get(d_id, {}).get('name', d_id)} x{count}" for d_id in top5_ids]
    await message.answer(
        f"🌌 <b>ТОП-5 БОЖЕСТВЕННЫХ ДИКТОРОВ ВЫДАНЫ!</b>\n\n"
        f"👤 Получатель: <b>{escape_html(t_name)}</b> (@{t_uname})\n"
        f"🆔 ID: <code>{t_uid}</code>\n\n"
        f"<b>Выданные ранги (66-70):</b>\n" + "\n".join(lines) +
        f"\n\n🛡 <i>Полная 100% защита от всех сбросов, вайпов и престижей!</i>"
    )


@router.message(Command("setprestige", "установить_престиж", "престиж_сет"))
async def cmd_set_prestige(message: types.Message):
    if not is_creator(message):
        return

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("<b>Использование:</b> <code>/setprestige @username &lt;0-6&gt;</code>")

    if message.reply_to_message:
        target_str = ""
        lvl_str = args[1]
    else:
        target_str = args[1]
        lvl_str = args[2] if len(args) > 2 else "0"

    if not lvl_str.isdigit() or not (0 <= int(lvl_str) <= 6):
        return await message.answer("❌ Укажите ранг престижа от 0 до 6.")

    tier = int(lvl_str)
    t_chat_id, t_uid, t_name, t_uname = await _resolve_user_target(message.chat.id, target_str, message)
    if not t_uid:
        return await message.answer("❌ Пользователь не найден.")

    from user_manager import update_user_field, invalidate_user_cache
    from prestige import PRESTIGE_TIERS
    await update_user_field(t_chat_id, t_uid, "prestige_level", tier)
    invalidate_user_cache(t_chat_id, t_uid)

    p_info = PRESTIGE_TIERS.get(tier, {"name": "Обыватель", "badge": "▫️", "roman": "0"})
    await message.answer(
        f"🎖 <b>Престиж установлен!</b>\n"
        f"👤 Игрок: <b>{escape_html(t_name)}</b> (@{t_uname})\n"
        f"🌟 Новый ранг: <b>[{tier}/6] {p_info['badge']} {p_info['name']}</b>"
    )


@router.message(Command("delitem", "забрать_предмет"))
async def cmd_del_item(message: types.Message):
    if not is_creator(message):
        return

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: <code>/delitem @username &lt;item_id&gt; [кол-во]</code>")

    from user_manager import remove_item_from_inventory, invalidate_user_cache
    from shop import ITEMS

    if message.reply_to_message:
        target_str = ""
        item_id = args[1].lower()
        count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 1
    else:
        target_str = args[1]
        item_id = args[2].lower() if len(args) > 2 else ""
        count = int(args[3]) if len(args) > 3 and args[3].isdigit() else 1

    t_chat_id, t_uid, t_name, t_uname = await _resolve_user_target(message.chat.id, target_str, message)
    if not t_uid:
        return await message.answer("❌ Пользователь не найден.")

    success = await remove_item_from_inventory(t_chat_id, t_uid, item_id, count=count)
    if success:
        invalidate_user_cache(t_chat_id, t_uid)
        item_name = ITEMS.get(item_id, {}).get("name", item_id)
        await message.answer(f"✅ Изъято {count}x {item_name} у {escape_html(t_name)}.")
    else:
        await message.answer("❌ У пользователя нет указанного предмета или количества.")


@router.message(Command("setmoney"))
async def cmd_setmoney(message: types.Message):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите сумму.")
        return

    try:
        amount = int(args[1])
        chat_id = message.chat.id
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)

        from user_manager import update_user_field
        await get_user_data(chat_id, target_id, target_name)
        await update_user_field(chat_id, target_id, 'balance', amount)
        await message.answer(f"Баланс пользователя {target_name} установлен в {amount} сыроежек.")
        from log_system import log_action
        log_action(f"💵 <b>Установка баланса:</b> {message.from_user.full_name} ({message.from_user.id}) установил баланс {target_name} ({target_id}) в <code>{amount:,}</code> сыроежек в чате {chat_id}")
    except ValueError:
        pass

@router.message(Command("ban"))
async def cmd_ban(message: types.Message):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return

    chat_id = message.chat.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)
    from user_manager import update_user_field, invalidate_user_cache
    await get_user_data(chat_id, target_id, target_name)
    await update_user_field(chat_id, target_id, 'is_banned', True)
    invalidate_user_cache(chat_id, target_id)
    await message.answer(f"Пользователь забанен в боте.")
    from log_system import log_action
    log_action(f"🔨 <b>Бан в боте:</b> {message.from_user.full_name} ({message.from_user.id}) забанил {target_name} ({target_id}) в чате {chat_id}")

@router.message(Command("unban"))
async def cmd_unban(message: types.Message):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return

    chat_id = message.chat.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)
    from user_manager import update_user_field, invalidate_user_cache
    await get_user_data(chat_id, target_id, target_name)
    await update_user_field(chat_id, target_id, 'is_banned', False)
    invalidate_user_cache(chat_id, target_id)
    await message.answer(f"Пользователь разбанен в боте.")
    from log_system import log_action
    log_action(f"🔓 <b>Разбан в боте:</b> {message.from_user.full_name} ({message.from_user.id}) разбанил {target_name} ({target_id}) в чате {chat_id}")

@router.message(Command("hide"))
async def cmd_hide(message: types.Message):
    if not is_creator(message):
        return

    chat_id = message.chat.id
    from user_manager import update_user_field

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        await update_user_field(chat_id, target_id, 'hide_in_top', True)
        await message.answer("Пользователь скрыт из топа.")
    else:
        user_id = message.from_user.id
        await update_user_field(chat_id, user_id, 'hide_in_top', True)
        await message.answer("Вы скрыты из топа.")

@router.message(Command("show"))
async def cmd_show(message: types.Message):
    if not is_creator(message):
        return

    chat_id = message.chat.id
    from user_manager import update_user_field

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        await update_user_field(chat_id, target_id, 'hide_in_top', False)
        await message.answer("Пользователь теперь отображается в топе.")
    else:
        user_id = message.from_user.id
        await update_user_field(chat_id, user_id, 'hide_in_top', False)
        await message.answer("Вы теперь отображаетесь в топе.")

@router.message(Command("setvip"))
async def cmd_setvip(message: types.Message):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return

    chat_id = message.chat.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    from user_manager import update_user_field
    await get_user_data(chat_id, target_id, target_name)
    await update_user_field(chat_id, target_id, 'is_vip', True)
    await message.answer(f"Пользователь {target_name} получил статус 👑 VIP!")

@router.message(Command("delvip"))
async def cmd_delvip(message: types.Message):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return

    chat_id = message.chat.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    from user_manager import update_user_field
    await get_user_data(chat_id, target_id, target_name)
    await update_user_field(chat_id, target_id, 'is_vip', False)
    await message.answer(f"Пользователь {target_name} лишен статуса VIP.")


@router.message(Command("setrole"))
async def cmd_setrole(message: types.Message):
    if not is_creator(message):
        return

    chat_id = message.chat.id
    target_id = None
    target_name = ""
    role_name = ""

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)
        
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            return await message.answer("Укажите название роли. Пример: <code>/setrole Люцифер</code>")
        role_name = args[1].strip()
    else:
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            return await message.answer("Использование:\nОтветом на сообщение: <code>/setrole [роль]</code>\nИли: <code>/setrole [ID/username] [роль]</code>")
        
        target_input = args[1]
        role_name = args[2].strip()
        
        from user_manager import get_user_by_username_or_id
        target_user = await get_user_by_username_or_id(chat_id, target_input)
        if not target_user:
            return await message.answer("❌ Пользователь не найден в базе этого чата.")
        target_id = target_user['user_id']
        target_name = escape_html(target_user.get('full_name', f"Юзер {target_id}"))

    if not target_id:
        return

    role_lower = role_name.lower()
    if "создатель" in role_lower or "creator" in role_lower:
        if target_id not in CREATOR_IDS:
            return await message.answer("❌ Роль 'Создатель' может быть установлена только для разработчиков бота.")

    from user_manager import update_user_field, invalidate_user_cache
    await update_user_field(chat_id, target_id, 'custom_role', role_name)
    invalidate_user_cache(chat_id, target_id)
    
    await message.answer(f"✅ Пользователю <b>{target_name}</b> выдана особая роль: <b>{escape_html(role_name)}</b>!")
    from log_system import log_action
    log_action(f"🎭 <b>Выдача роли:</b> {message.from_user.full_name} ({message.from_user.id}) выдал роль \"{role_name}\" пользователю {target_name} ({target_id}) в чате {chat_id}")


@router.message(Command("delrole"))
async def cmd_delrole(message: types.Message):
    if not is_creator(message):
        return

    chat_id = message.chat.id
    target_id = None
    target_name = ""

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)
    else:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            return await message.answer("Использование:\nОтветом на сообщение: <code>/delrole</code>\nИли: <code>/delrole [ID/username]</code>")
        
        target_input = args[1]
        from user_manager import get_user_by_username_or_id
        target_user = await get_user_by_username_or_id(chat_id, target_input)
        if not target_user:
            return await message.answer("❌ Пользователь не найден в базе этого чата.")
        target_id = target_user['user_id']
        target_name = escape_html(target_user.get('full_name', f"Юзер {target_id}"))

    if not target_id:
        return

    from user_manager import update_user_field, invalidate_user_cache
    await update_user_field(chat_id, target_id, 'custom_role', None)
    invalidate_user_cache(chat_id, target_id)
    
    await message.answer(f"❌ С пользователя <b>{target_name}</b> снята особая роль.")
    from log_system import log_action
    log_action(f"🎭 <b>Снятие роли:</b> {message.from_user.full_name} ({message.from_user.id}) снял роль с пользователя {target_name} ({target_id}) в чате {chat_id}")


@router.message(Command("check_id"))
async def cmd_check_id(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        f"👤 Твой ID: <code>{user_id}</code>\n"
        f"⚙️ В конфиге (CREATOR_ID): <code>{CREATOR_ID}</code>\n\n"
        f"<i>Если ID не совпадают, команды Создателя работать не будут!</i>"
    )

from whitelist import add_to_whitelist, remove_from_whitelist, get_whitelist
from spy import toggle_spy

@router.message(Command("say"))
async def cmd_say(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: <code>/say [id_группы] [сообщение]</code>")
        return

    try:
        chat_id = int(parts[1])
        text_to_say = parts[2]

        await bot.send_message(chat_id=chat_id, text=text_to_say, parse_mode=None)
        await message.answer(f"✅ Сообщение отправлено в группу <code>{chat_id}</code>")
    except ValueError:
        await message.answer("ID группы должен быть числом.")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")

@router.message(Command("rdel"))
async def cmd_rdel(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Использование: <code>/rdel [id_группы] [id_сообщения]</code>")
        return

    try:
        chat_id = int(parts[1])
        msg_id = int(parts[2])

        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        await message.answer(f"✅ Сообщение {msg_id} удалено из группы {chat_id}.")
    except ValueError:
        await message.answer("ID группы и сообщения должны быть числами.")
    except Exception as e:
        await message.answer(f"❌ Ошибка удаления: {e}\n(Возможно у меня нет прав админа в той группе или сообщение слишком старое)")

@router.message(Command("rban"))
async def cmd_rban(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Использование: <code>/rban [id_группы] [id_пользователя]</code>")
        return

    try:
        chat_id = int(parts[1])
        user_id = int(parts[2])

        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await message.answer(f"✅ Пользователь {user_id} забанен в группе {chat_id}.")
    except ValueError:
        await message.answer("ID должны быть числами.")
    except Exception as e:
        await message.answer(f"❌ Ошибка бана: {e}\n(Нет прав админа или пользователя нет в чате)")

@router.message(Command("runban"))
async def cmd_runban(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Использование: <code>/runban [id_группы] [id_пользователя]</code>")
        return

    try:
        chat_id = int(parts[1])
        user_id = int(parts[2])

        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
        await message.answer(f"✅ Пользователь {user_id} разбанен в группе {chat_id}.")
    except ValueError:
        await message.answer("ID должны быть числами.")
    except Exception as e:
        await message.answer(f"❌ Ошибка разбана: {e}")

@router.message(Command("getlink"))
async def cmd_getlink(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: <code>/getlink [id_группы]</code>")
        return

    try:
        chat_id = int(parts[1])
        link = await bot.export_chat_invite_link(chat_id=chat_id)
        await message.answer(f"🔗 Ссылка на группу <code>{chat_id}</code>:\n{link}")
    except ValueError:
        await message.answer("ID группы должен быть числом.")
    except Exception as e:
        await message.answer(f"❌ Ошибка получения ссылки: {e}\n(Нужны права админа)")

@router.message(Command("spy"))
async def cmd_spy(message: types.Message):
    if not is_creator(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите ID группы. Пример: <code>/spy -100123456789</code>\nИли напишите <code>/spyall</code> для шпионажа за ВСЕМИ группами.")
        return

    try:
        chat_id = int(args[1])
        is_enabled = await toggle_spy(chat_id)
        if is_enabled:
            await message.answer(f"👁 Режим шпионажа для группы <code>{chat_id}</code> ВКЛЮЧЕН.\nТеперь вы будете получать все их сообщения.")
        else:
            await message.answer(f"🙈 Режим шпионажа для группы <code>{chat_id}</code> ВЫКЛЮЧЕН.")
    except ValueError:
        await message.answer("ID группы должен быть числом.")

@router.message(Command("spyall"))
async def cmd_spyall(message: types.Message):
    if not is_creator(message):
        return

    from spy import toggle_spy_all
    is_enabled = await toggle_spy_all()
    if is_enabled:
        await message.answer("👁👁 <b>ГЛОБАЛЬНЫЙ ШПИОНАЖ ВКЛЮЧЕН!</b>\nТеперь вы получаете все сообщения ИЗ ВСЕХ ГРУПП, где состоит бот.")
    else:
        await message.answer("🙈 <b>Глобальный шпионаж ВЫКЛЮЧЕН.</b>")


@router.message(Command("allow"))
async def cmd_allow(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Укажите ID группы. Пример: <code>/allow -100123456789 Название</code>")
        return

    try:
        chat_id = int(args[1])
        title = args[2] if len(args) > 2 else "Unknown Group"

        try:
            chat = await bot.get_chat(chat_id)
            title = chat.title or title
        except Exception:
            pass

        success = await add_to_whitelist(chat_id, title)
        if success:
            await message.answer(f"✅ Группа <b>{title}</b> (<code>{chat_id}</code>) добавлена в белый список.")
        else:
            await message.answer(f"Группа <code>{chat_id}</code> уже в белом списке.")
    except ValueError:
        await message.answer("ID группы должен быть числом.")

@router.message(Command("disallow"))
async def cmd_disallow(message: types.Message):
    if not is_creator(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите ID группы. Пример: <code>/disallow -100123456789</code>")
        return

    try:
        chat_id = int(args[1])
        success = await remove_from_whitelist(chat_id)
        if success:
            await message.answer(f"❌ Группа <code>{chat_id}</code> удалена из белого списка.")
        else:
            await message.answer(f"Группы <code>{chat_id}</code> нет в белом списке.")
    except ValueError:
        await message.answer("ID группы должен быть числом.")

from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER, ADMINISTRATOR
from aiogram.filters.chat_member_updated import KICKED, LEFT

@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=(LEFT | KICKED) >> (MEMBER | ADMINISTRATOR)))
async def bot_added_to_chat(event: types.ChatMemberUpdated, bot: Bot):
    chat_id = event.chat.id
    chat_title = event.chat.title or "Unknown"

    whitelist = await get_whitelist()

    if chat_id not in whitelist:
        from config import CREATOR_ID
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="Хаю хай гайсы, я бот диктор тайний баний, /help узнать все мои команды"
            )
        except Exception as e:
            print(f"Ошибка при приветствии в новой группе: {e}")

        if CREATOR_ID and int(CREATOR_ID) != 0:
            try:
                await bot.send_message(
                    chat_id=CREATOR_ID,
                    text=(
                        f"⚠️ <b>Меня добавили в новую группу!</b>\n\n"
                        f"Название: <b>{chat_title}</b>\n"
                        f"ID группы: <code>{chat_id}</code>\n"
                        f"Кто добавил: <b>{event.from_user.full_name}</b> (<code>{event.from_user.id}</code>)\n\n"
                        f"Добавить в белый список: <code>/allow {chat_id}</code>\n"
                        f"Наблюдать за чатом: <code>/spy {chat_id}</code>\n"
                        f"Написать туда: <code>/say {chat_id} текст</code>"
                    )
                )
            except Exception as e:
                print(f"Ошибка при отправке уведомления создателю: {e}")

@router.message(Command("whitelist"))
async def cmd_whitelist(message: types.Message):
    if not is_creator(message):
        return

    whitelist = await get_whitelist()
    if not whitelist:
        await message.answer("Белый список пуст.")
        return

    text = "📝 <b>Разрешенные группы:</b>\n\n"
    for chat_id, title in whitelist.items():
        text += f"• <b>{title}</b>\n<code>{chat_id}</code>\n\n"

    await message.answer(text)

from chances import set_game_chance, get_game_chance

@router.message(Command("setchance"))
async def cmd_setchance(message: types.Message):
    if not is_creator(message):
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "Использование: <code>/setchance [игра] [процент]</code>\n"
            "Доступные игры: <code>slots</code>, <code>cups</code>, <code>roulette</code>, <code>blackjack</code>, <code>baccarat</code>, <code>craps</code>, <code>poker</code>, <code>crash</code>\n"
            "Процент: 0-100 (установите -1 для честного рандома).\n"
            "Пример: <code>/setchance slots 50</code>"
        )
        return

    game_name = args[1].lower()
    valid_games = ['slots', 'cups', 'roulette', 'blackjack', 'baccarat', 'craps', 'poker', 'crash']

    if game_name not in valid_games:
        await message.answer(f"Неизвестная игра. Доступные: {', '.join(valid_games)}")
        return

    try:
        percentage = int(args[2])
        if percentage < -1 or percentage > 100:
            await message.answer("Процент должен быть от -1 до 100.")
            return

        await set_game_chance(game_name, percentage)
        if percentage == -1:
            await message.answer(f"Для игры <b>{game_name}</b> установлен честный рандом.")
        else:
            await message.answer(f"Для игры <b>{game_name}</b> установлен принудительный шанс победы: <b>{percentage}%</b>")
    except ValueError:
        await message.answer("Процент должен быть числом.")

@router.message(Command("info"))
async def cmd_info(message: types.Message):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return

    chat_id = message.chat.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    data = await get_user_data(chat_id, target_id, target_name)

    balance = data.get('balance', 0)
    is_vip = data.get('is_vip', False)
    is_banned = data.get('is_banned', False)
    inventory = data.get('inventory', {})

    inv_text = ", ".join([f"{k}: {v}" for k, v in inventory.items()]) if inventory else "Пусто"
    vip_text = "Да 👑" if is_vip else "Нет"
    ban_text = "Да 🚫" if is_banned else "Нет"

    text = (
        f"📊 <b>Информация о пользователе {target_name}</b>\n\n"
        f"ID: <code>{target_id}</code>\n"
        f"Баланс: {balance} сыроежек\n"
        f"VIP статус: {vip_text}\n"
        f"Бан: {ban_text}\n"
        f"Инвентарь: {inv_text}"
    )

    await message.answer(text)

@router.message(Command("nalog"))
async def cmd_nalog(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите процент налога: <code>/nalog 15</code>")
        return

    try:
        tax = int(args[1])
        if tax < 0 or tax > 100:
            await message.answer("Налог должен быть от 0 до 100.")
            return

        from economy_utils import set_global_tax
        await set_global_tax(tax)

        from whitelist import get_whitelist
        whitelist = await get_whitelist()

        import secrets
        phrases_up =[
            f"⚠️ <b>ВНИМАНИЕ: ЭКОНОМИЧЕСКИЙ КРИЗИС!</b>\nНалоги повышены до <b>{tax}%</b>! Запасайтесь сыроежками!",
            f"🏛 <b>УКАЗ ГУБЕРНАТОРА:</b>\nКазна пустеет. Налоги увеличены до <b>{tax}%</b>.",
            f"💼 <b>НОВОСТИ ЭКОНОМИКИ:</b>\nНалоговая ставка выросла! Теперь при переводах удерживается <b>{tax}%</b>."
        ]
        phrases_down =[
            f"🎉 <b>ПРАЗДНИК В СТРАНЕ!</b>\nНалоги снижены до <b>{tax}%</b>! Время переводить сыроежки!",
            f"🏛 <b>УКАЗ ГУБЕРНАТОРА:</b>\nЭкономика процветает. Налоги уменьшены до <b>{tax}%</b>.",
            f"💼 <b>НОВОСТИ ЭКОНОМИКИ:</b>\nНалоговое бремя ослабло! Теперь при переводах удерживается всего <b>{tax}%</b>."
        ]

        text = secrets.choice(phrases_up) if tax >= 15 else secrets.choice(phrases_down)

        success_count = 0
        for chat_id in whitelist.keys():
            try:
                await bot.send_message(chat_id, text)
                success_count += 1
            except Exception:
                pass

        await message.answer(f"✅ Налог установлен на {tax}%. Уведомлено {success_count} групп.")
    except ValueError:
        await message.answer("Процент должен быть числом.")

@router.message(Command("wipe_economy"))
async def cmd_wipe_economy(message: types.Message):
    if not is_creator(message):
        return await message.answer("❌ Отказано в доступе. У вас нет прав Создателя для запуска вайпа!")

    args = message.text.split()
    if len(args) < 2 or args[1] != "CONFIRM":
        return await message.answer(
            "⚠️ <b>ВНИМАНИЕ! ГЛОБАЛЬНЫЙ ВАЙП ЭКОНОМИКИ!</b> ⚠️\n\n"
            "Это действие:\n"
            "1. Сбросит баланс всех игроков до 500.\n"
            "2. Обнулит банковские счета.\n"
            "3. Удалит все бизнесы и машины из инвентарей.\n"
            "4. Сбросит все навыки и удалит питомцев.\n"
            "5. Простит все долги игроков.\n"
            "6. Обнулит казну всех кланов.\n"
            "7. Полностью перезапустит крипто-рынок.\n\n"
            "<i>(Админки, репутация, браки и варны сохранятся)</i>\n\n"
            "Если вы абсолютно УВЕРЕНЫ, введите команду:\n"
            "<code>/wipe_economy CONFIRM</code>"
        )

    status_msg = await message.answer("🔄 <i>Начинаю глобальный сброс экономики... Это займет некоторое время.</i>")

    import time
    import random
    from user_manager import _user_cache
    
    db = get_db()
    
    # 1. Очищаем оперативную память (кэш), чтобы старые балансы не вернулись
    _user_cache.clear()

    from whitelist import get_whitelist
    whitelist_dict = await get_whitelist()
    users_wiped = 0
    clans_wiped = 0

    for chat_id in whitelist_dict.keys():
        try:
            # 2. Вайп пользователей (обнуление полей экономики)
            users_ref = db.collection('chats').document(str(chat_id)).collection('users')
            user_docs = await users_ref.get()
            
            from user_manager import preserve_protected_inventory
            batch = db.batch()
            count = 0
            for doc in user_docs:
                doc_id = getattr(doc, 'id', None)
                if doc_id:
                    u_data = doc.to_dict() if hasattr(doc, 'to_dict') else {}
                    kept_inv = preserve_protected_inventory(u_data.get('inventory') or {})
                    batch.set(users_ref.document(doc_id), {
                        'balance': 500,
                        'bank_deposit': 0,
                        'inventory': kept_inv,
                        'debts': {},
                        'skills': {},
                        'pet': None
                    }, merge=True)
                    users_wiped += 1
                    count += 1
                    if count >= 500:
                        await batch.commit()
                        batch = db.batch()
                        count = 0

            # 3. Вайп кланов (обнуление казны)
            clans_ref = db.collection('chats').document(str(chat_id)).collection('clans')
            clan_docs = await clans_ref.get()
            
            for cdoc in clan_docs:
                cdoc_id = getattr(cdoc, 'id', None)
                if cdoc_id:
                    batch.set(clans_ref.document(cdoc_id), {
                        'treasury': 0
                    }, merge=True)
                    clans_wiped += 1
                    count += 1
                    if count >= 500:
                        await batch.commit()
                        batch = db.batch()
                        count = 0

            if count > 0:
                await batch.commit()
                
        except Exception as e:
            print(f"Ошибка при вайпе чата {chat_id}: {e}")

    # 4. Полный вайп криптовалюты
    current_time = int(time.time())
    default_coins = {
        "chsyr": {"name": "Китайская Сыроежка", "ticker": "CH_SYR", "prices":[random.randint(100, 500)], "creator": 0},
        "espsyr": {"name": "Испанская Сыроежка", "ticker": "ESP_SYR", "prices":[random.randint(100, 500)], "creator": 0}
    }
    await db.collection('bot_settings').document('crypto_coins').set({
        'coins': default_coins,
        'last_update': current_time
    })

    try:
        await status_msg.edit_text(
            f"✅ <b>ЭКОНОМИКА УСПЕШНО СБРОШЕНА!</b>\n\n"
            f"👤 Обнулено игроков: <b>{users_wiped}</b>\n"
            f"🛡 Обнулено кланов: <b>{clans_wiped}</b>\n"
            f"📈 Крипторынок пересоздан с нуля.\n\n"
            f"<i>Все начали жизнь с чистого листа (баланс 500 сыроежек).</i>"
        )
    except Exception as e:
        await status_msg.reply(f"Вайп завершен! Ошибка статуса: {e}")
from lock_system import toggle_lock

@router.message(Command("lockbot"))
async def cmd_lockbot(message: types.Message):
    if not is_creator(message):
        return await message.answer("❌ Нет доступа.")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: <code>/lockbot [ID группы]</code>")

    try:
        chat_id = int(args[1])
        is_enabled = await toggle_lock(chat_id)

        if is_enabled:
            await message.answer(f"🔒 <b>Группа {chat_id} заблокирована.</b> Бот потребует права администратора для работы.")
        else:
            await message.answer(f"🔓 <b>Группа {chat_id} разблокирована.</b> Бот работает в штатном режиме.")
    except ValueError:
        await message.answer("ID группы должен быть числом.")

@router.message(Command("checkadmin"))
async def cmd_checkadmin(message: types.Message, bot: Bot):
    if not is_creator(message):
        return await message.answer("❌ Нет доступа.")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: <code>/checkadmin [ID группы]</code>")

    try:
        chat_id = int(args[1])
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        if bot_member.status in ['administrator', 'creator']:
            await message.answer(f"✅ Бот <b>является</b> администратором в группе {chat_id}.")
        else:
            await message.answer(f"❌ Бот <b>не является</b> администратором в группе {chat_id}. Текущий статус: {bot_member.status}")
    except Exception as e:
        await message.answer(f"❌ Ошибка проверки: {e}")


@router.message(Command("wipe_mid"))
async def cmd_wipe_mid(message: types.Message):
    if not is_creator(message):
        return await message.answer("❌ Отказано в доступе. У вас нет прав Создателя для запуска вайпа!")

    args = message.text.split()
    if len(args) < 2 or args[1] != "CONFIRM":
        return await message.answer(
            "⚠️ <b>ВНИМАНИЕ! СРЕДНИЙ ВАЙП ЭКОНОМИКИ (/wipe_mid)!</b> ⚠️\n\n"
            "Это действие:\n"
            "1. Сбросит баланс наличных всех игроков до 500.\n"
            "2. <b>Полностью очистит инвентари</b> (бизнесы, машины, VIP, предметы удалятся).\n"
            "3. Полностью перезапустит крипто-рынок (биржу).\n\n"
            "<b>При этом СОХРАНЯТСЯ:</b>\n"
            "- Банковские счета и вклады.\n"
            "- Долги игроков.\n"
            "- Навыки и питомцы.\n"
            "- Кланы и их казна.\n"
            "- Браки, репутация и варны.\n\n"
            "Если вы абсолютно УВЕРЕНЫ, введите команду:\n"
            "<code>/wipe_mid CONFIRM</code>"
        )

    status_msg = await message.answer(
        "🔄 <b>Вайп запущен в фоновом режиме!</b>\n\n"
        "<i>Пожалуйста, подождите, бот перебирает базу данных... Это может занять несколько минут. Я сообщу, когда закончу.</i>"
    )

    import asyncio

    async def run_wipe():
        try:
            import time
            import random
            from user_manager import _user_cache
            from db import get_db

            db = get_db()
            _user_cache.clear()

            from whitelist import get_whitelist
            whitelist_dict = await get_whitelist()
            users_wiped = 0

            # 2. Вайп пользователей (обнуление налички и инвентаря)
            for chat_id in whitelist_dict.keys():
                try:
                    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
                    user_docs = await users_ref.get()

                    from user_manager import preserve_protected_inventory
                    batch = db.batch()
                    count = 0
                    for doc in user_docs:
                        doc_id = getattr(doc, 'id', None)
                        if doc_id:
                            u_data = doc.to_dict() if hasattr(doc, 'to_dict') else {}
                            kept_inv = preserve_protected_inventory(u_data.get('inventory') or {})
                            batch.set(users_ref.document(doc_id), {
                                'balance': 500,
                                'inventory': kept_inv,
                                'is_vip': False
                            }, merge=True)
                            users_wiped += 1
                            count += 1
                            if count >= 450:
                                await batch.commit()
                                batch = db.batch()
                                count = 0

                    if count > 0:
                        await batch.commit()

                except Exception as e:
                    print(f"Ошибка при вайпе чата {chat_id}: {e}")

            # 3. Полный вайп криптовалюты
            current_time = int(time.time())
            default_coins = {
                "chsyr": {"name": "Китайская Сыроежка", "ticker": "CH_SYR", "prices":[random.randint(100, 500)], "creator": 0},
                "espsyr": {"name": "Испанская Сыроежка", "ticker": "ESP_SYR", "prices":[random.randint(100, 500)], "creator": 0}
            }
            await db.collection('bot_settings').document('crypto_coins').set({
                'coins': default_coins,
                'last_update': current_time
            })

            try:
                await status_msg.edit_text(
                    f"✅ <b>СРЕДНИЙ ВАЙП УСПЕШНО ЗАВЕРШЕН!</b>\n\n"
                    f"👤 Очищено налички и инвентарей у игроков: <b>{users_wiped}</b>\n"
                    f"📈 Крипторынок пересоздан с нуля.\n\n"
                    f"<i>Вклады, долги, кланы и навыки не пострадали.</i>"
                )
            except Exception:
                await status_msg.reply(
                    f"✅ <b>СРЕДНИЙ ВАЙП УСПЕШНО ЗАВЕРШЕН!</b>\n\n"
                    f"👤 Очищено: {users_wiped} игроков."
                )
        except Exception as fatal_e:
            import traceback
            tb = traceback.format_exc()
            try:
                await status_msg.reply(f"❌ <b>Критическая ошибка во время вайпа!</b>\n\n<code>{fatal_e}</code>\n{tb[:500]}")
            except Exception:
                pass

    # Launch task in background
    asyncio.create_task(run_wipe())

@router.message(or_f(Command("execute"), F.text.lower() == "казнить"))
async def cmd_execute(message: types.Message, bot: Bot):
    if not is_creator(message):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение грешника, которого нужно <b>казнить</b>.")

    target_user = message.reply_to_message.from_user
    target_id = target_user.id
    target_name = escape_html(target_user.full_name)
    
    # Ссылка на эпичную картинку (сгенерирована специально для вас)
    from aiogram.types import FSInputFile
    import os
    
    # Путь теперь относительный, чтобы работало в Docker/на сервере
    image_path = "assets/execution.png"
    
    caption = (
        f"⚖️ <b>ВЫСШАЯ МЕРА НАКАЗАНИЯ!</b>\n\n"
        f"Пользователь <b>{target_name}</b> (<code>{target_id}</code>) был признан виновным в предательстве и приговорен к <b>казни</b>!\n\n"
        f"⚔️ <i>Приговор приведен в исполнение немедленно по воле Создателя.</i>\n"
        f"💀 Да смилуются боги над его душой!"
    )

    try:
        if os.path.exists(image_path):
            photo = FSInputFile(image_path)
            await message.answer_photo(photo=photo, caption=caption)
        else:
            await message.answer_photo(
                photo="https://i.imgur.com/8Qp4S3q.png",
                caption=caption
            )
    except Exception as e:
        print(f"Ошибка отправки фото казни: {e}")
        await message.answer(caption)


# ============================================================
# РЕЗЕРВНОЕ КОПИРОВАНИЕ И ВОССТАНОВЛЕНИЕ
# ============================================================

@router.message(Command("db_backup"))
async def cmd_db_backup(message: types.Message):
    if not is_creator(message):
        return

    # Удаляем сообщение с командой для конфиденциальности
    try:
        await message.delete()
    except Exception:
        pass

    from backup_system import backup_database
    success, result = await backup_database()
    
    response_text = ""
    if success:
        response_text = f"✅ Резервная копия базы данных успешно создана: <code>{result}</code>"
    else:
        response_text = f"❌ Не удалось создать резервную копию: {result}"

    try:
        await message.bot.send_message(chat_id=message.from_user.id, text=response_text, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки приватного сообщения создателю: {e}")

@router.message(Command("db_backups"))
async def cmd_db_backups(message: types.Message):
    if not is_creator(message):
        return

    try:
        await message.delete()
    except Exception:
        pass

    db = get_db()
    try:
        docs = await db.collection('backups').order_by('timestamp', direction='DESCENDING').limit(30).get()
        if not docs:
            response_text = "📭 Список резервных копий пуст."
        else:
            lines = ["📅 <b>Доступные резервные копии (за последние 7 дней):</b>\n"]
            for doc in docs:
                d = doc.to_dict()
                lines.append(f"• <code>{doc.id}</code> — {d.get('datetime')} UTC")
            response_text = "\n".join(lines)
            
        await message.bot.send_message(chat_id=message.from_user.id, text=response_text, parse_mode="HTML")
    except Exception as e:
        try:
            await message.bot.send_message(chat_id=message.from_user.id, text=f"❌ Ошибка получения списка копий: {e}", parse_mode="HTML")
        except Exception:
            pass

@router.message(Command("db_restore"))
async def cmd_db_restore(message: types.Message):
    if not is_creator(message):
        return

    try:
        await message.delete()
    except Exception:
        pass

    args = message.text.split()
    if len(args) < 2:
        try:
            await message.bot.send_message(chat_id=message.from_user.id, text="⚠️ Использование: <code>/db_restore backup_[timestamp]</code>", parse_mode="HTML")
        except Exception:
            pass
        return

    backup_id = args[1].strip()
    
    try:
        status_msg = await message.bot.send_message(
            chat_id=message.from_user.id,
            text=f"🔄 <i>Начинаю восстановление базы данных из {backup_id}...</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка отправки приватного сообщения восстановления: {e}")
        status_msg = None

    from backup_system import restore_database
    success, error = await restore_database(backup_id)
    
    if status_msg:
        try:
            if success:
                await status_msg.edit_text(f"✅ База данных успешно восстановлена из резервной копии <code>{backup_id}</code>!", parse_mode="HTML")
            else:
                await status_msg.edit_text(f"❌ Ошибка восстановления: {error}", parse_mode="HTML")
        except Exception:
            pass
    else:
        print(f"Результат восстановления {backup_id}: success={success}, error={error}")
