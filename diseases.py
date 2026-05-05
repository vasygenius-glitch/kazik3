import time
import random
from db import get_db
from aiogram import Router, types
from aiogram.filters import Command
from escape import escape_html

router = Router()

DISEASES = {
    "hiv": {"name": "ВИЧ", "desc": "Зарплата на работе падает до нуля. Сил работать нет."},
    "syphilis": {"name": "Сифилис", "desc": "Шанс успеха в преступлениях режется ровно в два раза."},
    "gonorrhea": {"name": "Гонорея", "desc": "Полный запрет на казино. Крупье брезгует пускать тебя за стол."},
    "chlamydia": {"name": "Хламидиоз", "desc": "Блокировка всех РП команд. Никаких обнимашек, поцелуев и укусов."},
    "herpes": {"name": "Герпес", "desc": "Глобальный налог на все переводы сыроежек возрастает до 30%."},
    "hpv": {"name": "ВПЧ", "desc": "Твой питомец отказывается давать бонусы и приносить доход."},
    "lice": {"name": "Лобковые вши", "desc": "За каждое твое сообщение в группе списывается 10 сыроежек на мази."},
    "trichomoniasis": {"name": "Трихомониаз", "desc": "Навык Удача в блэкджеке отключается. Перебор больше не прощается."},
    "hepatitis": {"name": "Гепатит", "desc": "Временный запрет на использование банка, кредитов и инкассации."},
    "candidiasis": {"name": "Кандидоз", "desc": "Ежедневный бонус выдает ровно половину от обычной суммы."}
}

from utils_pkg.cache_manager import global_cache

async def get_top_1_hooker(chat_id: int):
    """Возвращает ID топ-1 путаны чата."""
    cache_key = f"top_1_hooker_{chat_id}"
    cached_top = global_cache.get(cache_key)
    if cached_top is not None:
        return cached_top

    db = get_db()
    try:
        users_ref = db.collection('chats').document(str(chat_id)).collection('users')
        docs = await users_ref.get()
        top_hooker_id = 0
        max_count = 0
        for doc in docs:
            data = doc.to_dict()
            count = data.get('escort_count', 0)
            if count > max_count and not data.get('hide_in_top') and not data.get('is_banned'):
                max_count = count
                top_hooker_id = int(doc.id)

        global_cache.set(cache_key, top_hooker_id, ttl=300) # Кэшируем на 5 минут
        return top_hooker_id
    except Exception as e:
        return 0

async def is_top_1_hooker(chat_id: int, user_id: int) -> bool:
    top_id = await get_top_1_hooker(chat_id)
    return top_id == user_id

async def infect_user(chat_id: int, user_id: int) -> list:
    """Заражает пользователя случайным количеством болезней."""
    from user_manager import get_user_data, update_user_field

    data = await get_user_data(chat_id, user_id)
    current_diseases = data.get('diseases', {})

    num_to_infect = random.randint(1, len(DISEASES))
    new_infections = random.sample(list(DISEASES.keys()), num_to_infect)

    current_time = time.time()
    infected_list = []

    for d in new_infections:
        current_diseases[d] = current_time + 3600 # 1 час
        infected_list.append(DISEASES[d]['name'])

    await update_user_field(chat_id, user_id, 'diseases', current_diseases)
    return infected_list

async def get_active_diseases(chat_id: int, user_id: int) -> list:
    """Возвращает список ID активных болезней пользователя."""
    from user_manager import get_user_data, update_user_field

    # Оптимизация: получаем профиль. Если болезней нет, даже не проверяем иммунитет (экономим базу)
    data = await get_user_data(chat_id, user_id)
    diseases = data.get('diseases', {})
    if not diseases:
        return []

    if await is_top_1_hooker(chat_id, user_id):
        # Топ 1 путана имеет иммунитет, дебаффы не работают (возвращаем пустой список для логики)
        return []

    current_time = time.time()
    active = []
    to_delete = []

    for d, exp_time in diseases.items():
        if current_time < exp_time:
            active.append(d)
        else:
            to_delete.append(d)

    if to_delete:
        for d in to_delete:
            del diseases[d]
        await update_user_field(chat_id, user_id, 'diseases', diseases)

    return active

@router.message(Command("зппп"))
async def cmd_std(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    is_immune = await is_top_1_hooker(chat_id, user_id)

    from user_manager import get_user_data, update_user_field
    data = await get_user_data(chat_id, user_id)
    diseases = data.get('diseases', {})

    current_time = time.time()
    active_d_dict = {}
    to_delete = []

    for d, exp_time in diseases.items():
        if current_time < exp_time:
            active_d_dict[d] = exp_time
        else:
            to_delete.append(d)

    if to_delete:
        for d in to_delete:
            del diseases[d]
        await update_user_field(chat_id, user_id, 'diseases', diseases)

    if not active_d_dict and not is_immune:
        return await message.answer("✅ <b>Вы абсолютно здоровы!</b> Никаких ЗППП не обнаружено.")

    text = f"🩺 <b>Медицинская карта: {full_name}</b>\n\n"

    if is_immune:
        text += "👑 <b>Топ-1 Путана:</b> Ваш организм настолько привык к этой жизни, что выработал абсолютный иммунитет ко всем заболеваниям. Вы хронически больны всем, но симптомы вас больше не беспокоят.\n\n"
        for d_id, d_info in DISEASES.items():
            text += f"🦠 <b>{d_info['name']}</b> (Хроническое)\n"
    else:
        for d, exp_time in active_d_dict.items():
            rem_min = int((exp_time - current_time) // 60)
            d_info = DISEASES[d]
            text += f"🦠 <b>{d_info['name']}</b> (Осталось: {rem_min} мин.)\n<i>{d_info['desc']}</i>\n\n"

    await message.answer(text)
