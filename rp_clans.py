import time
import secrets
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import get_db
from escape import escape_html
from user_manager import get_user_data, update_user_balance, update_user_field

router = Router()

# ================= БРАКИ =================
active_marriages = {}

@router.message(F.text.lower().in_(["брак", "/marry"]))
async def cmd_marry(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение человека, которому хотите предложить брак.")

    chat_id = message.chat.id
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id

    if user_id == target_id:
        return await message.answer("Нельзя вступить в брак с самим собой.")
    if message.reply_to_message.from_user.is_bot:
        return await message.answer("Нельзя вступить в брак с ботом.")

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'donovanosis' in active_diseases:
        return await message.answer("🦠 <b>Донованоз</b>: Строгий запрет на заключение браков. Вылечитесь сначала.")

    user_data = await get_user_data(chat_id, user_id)
    target_data = await get_user_data(chat_id, target_id)

    if user_data.get('partner'):
        return await message.answer("Вы уже в браке!")
    if target_data.get('partner'):
        return await message.answer("Этот человек уже в браке!")

    marriage_id = f"{chat_id}_{user_id}_{target_id}"
    active_marriages[marriage_id] = {'amount': 0} # Для подарков

    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data=f"marry_yes_{marriage_id}")
    builder.button(text="Нет", callback_data=f"marry_no_{marriage_id}")

    await message.answer(
        f"💍 <b>Предложение руки и сердца!</b>\n\n"
        f"Пользователь <b>{escape_html(message.from_user.full_name)}</b> предлагает <b>{escape_html(message.reply_to_message.from_user.full_name)}</b> стать партнерами.\n\n"
        f"<i>Зрители могут отправлять свадебные подарки, написав реплаем 'Подарок [сумма]' на это сообщение!</i>",
        reply_markup=builder.as_markup()
    )

@router.message(F.text.lower().startswith("подарок") | F.text.lower().startswith("/gift"))
async def cmd_gift(message: types.Message):
    if not message.reply_to_message or not message.reply_to_message.reply_markup:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 2:
        return

    try:
        amount = int(args[1])
        if amount <= 0: return
    except ValueError:
        return

    # Ищем marriage_id по кнопкам
    marriage_id = None
    for row in message.reply_to_message.reply_markup.inline_keyboard:
        for btn in row:
            if btn.callback_data and btn.callback_data.startswith("marry_yes_"):
                marriage_id = btn.callback_data.replace("marry_yes_", "")
                break

    if not marriage_id or marriage_id not in active_marriages:
        return

    user_data = await get_user_data(chat_id, user_id)
    if user_data.get('balance', 0) < amount:
        return await message.answer("У вас недостаточно сыроежек для такого подарка.")

    res = await update_user_balance(chat_id, user_id, -amount, min_balance=0)
    if res is None:
        return await message.answer("У вас недостаточно сыроежек для такого подарка.")
    active_marriages[marriage_id]['amount'] += amount
    await message.answer(f"🎁 <b>{escape_html(message.from_user.full_name)}</b> вложил <b>{amount}</b> сыроежек в свадебный бюджет!")

@router.callback_query(F.data.startswith("marry_"))
async def callback_marry(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    marriage_id = callback.data.replace(f"marry_{action}_", "")
    parts = marriage_id.split("_")
    chat_id = int(parts[0])
    proposer_id = int(parts[1])
    target_id = int(parts[2])

    if callback.from_user.id != target_id:
        return await callback.answer("Это предложение не для вас!", show_alert=True)

    if marriage_id not in active_marriages:
        return await callback.answer("Предложение больше не действительно.", show_alert=True)

    gift_amount = active_marriages.pop(marriage_id, {}).get('amount', 0)

    if action == "no":
        await callback.message.edit_text("💔 Предложение отклонено. Свадьба отменяется.")
        return

    # Согласие
    proposer_name = "Ваш партнер" # В идеале получить из кэша
    target_name = escape_html(callback.from_user.full_name)

    await update_user_field(chat_id, proposer_id, 'partner', target_id)
    await update_user_field(chat_id, target_id, 'partner', proposer_id)

    text = f"🎉 <b>СВАДЬБА!</b> 🎉\n\nПоздравляем новую пару! 💍"
    if gift_amount > 0:
        half = gift_amount // 2
        await update_user_balance(chat_id, proposer_id, half)
        await update_user_balance(chat_id, target_id, gift_amount - half)
        text += f"\n\nСвадебный банк составил <b>{gift_amount}</b> сыроежек. Деньги разделены поровну между молодоженами!"

    await callback.message.edit_text(text)

@router.message(F.text.lower().in_(["развод", "/divorce"]))
async def cmd_divorce(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    partner_id = data.get('partner')
    if not partner_id:
        return await message.answer("Вы не в браке.")

    await update_user_field(chat_id, user_id, 'partner', None)
    await update_user_field(chat_id, partner_id, 'partner', None)

    await message.answer("💔 Вы успешно расторгли брак.")

# ================= РП КОМАНДЫ И КАРМА =================

RP_COMMANDS = {
    "обнять": "🤗 {user} нежно обнял(а) {target}",
    "поцеловать": "💋 {user} поцеловал(а) {target}",
    "ударить": "👊 {user} сильно ударил(а) {target}",
    "кусь": "🧛‍♂️ {user} сделал(а) кусь {target}",
    "погладить": "✋ {user} погладил(а) {target} по голове",
    "укусить": "🧛‍♂️ {user} укусил(а) {target}"
}

async def get_seasonal_rp_commands():
    from seasons import get_season_config
    cfg = await get_season_config()
    if cfg.get("active") and cfg.get("id") == "backrooms":
        return {
            "поделиться водой": "🍶 {user} поделился миндальной водой с {target}",
            "вместе бежать": "🏃‍♂️ {user} и {target} вместе убегают от Сущности!",
            "напугать": "👻 {user} выскочил(а) из-за угла и напугал(а) {target}!"
        }
    return {}

karma_triggers_global = ['+', 'спасибо', 'спс', 'rep', 'реп', 'уважение']

@router.message(F.reply_to_message & F.text & (F.text.lower().in_(RP_COMMANDS.keys()) | F.text.lower().in_(karma_triggers_global)))
async def rp_and_karma(message: types.Message):
    text = message.text.lower()
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    # Объединяем базовые и сезонные РП команды
    seasonal_rp = await get_seasonal_rp_commands()
    ALL_RP = {**RP_COMMANDS, **seasonal_rp}

    # РП Команды
    if text in ALL_RP:
        from diseases import get_active_diseases
        from user_manager import remove_item_from_inventory

        # Проверяем, есть ли презерватив при РП
        has_condom = await remove_item_from_inventory(message.chat.id, message.from_user.id, "condom")

        active_diseases = await get_active_diseases(message.chat.id, message.from_user.id)
        if 'chlamydia' in active_diseases and not has_condom:
            return await message.answer("🦠 <b>Хламидиоз</b>: Партнер шарахается от тебя. Никаких обнимашек, поцелуев и укусов, пока не вылечишься!")

        if message.from_user.id == message.reply_to_message.from_user.id:
            return await message.answer("Вы не можете применить это к себе.")
        if message.reply_to_message.from_user.is_bot:
            return await message.answer("Боты не чувствуют эмоций 🤖.")

        action_text = ALL_RP[text].format(user=f"<b>{user_name}</b>", target=f"<b>{target_name}</b>")
        if has_condom:
            action_text += "\n🎈 <i>Был использован презерватив для безопасности контакта.</i>"
        
        from seasons import get_glitch_text
        action_text = await get_glitch_text(action_text)

        return await message.answer(action_text)

    # Карма / Репутация
    if text in karma_triggers_global:
        if message.from_user.id == message.reply_to_message.from_user.id:
            return await message.answer("Нельзя повысить репутацию самому себе.")
        if message.reply_to_message.from_user.is_bot:
            return

        chat_id = message.chat.id
        target_id = message.reply_to_message.from_user.id

        target_data = await get_user_data(chat_id, target_id, target_name)
        new_rep = target_data.get('reputation', 0) + 1
        await update_user_field(chat_id, target_id, 'reputation', new_rep)

        await message.answer(f"📈 Уважение пользователя <b>{target_name}</b> повышено! (Репутация: {new_rep})")

# ================= ДУЭЛИ =================
import time
import asyncio
from aiogram.utils.keyboard import InlineKeyboardBuilder

active_duels = {}

@router.message(F.text & (F.text.lower().startswith("вызвать на дуэль") | F.text.lower().startswith("дуэль") | F.text.lower().startswith("/duel")))
async def cmd_duel(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение ковбоя, которому хотите бросить вызов.")

    chat_id = message.chat.id
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id

    if user_id == target_id or message.reply_to_message.from_user.is_bot:
        return await message.answer("В этом салуне с такими не стреляются.")

    args = message.text.split()
    bet_str = args[-1]

    try:
        bet = int(bet_str)
        if bet <= 0: return
    except ValueError:
        return await message.answer("Укажите ставку для дуэли: <code>Вызвать на дуэль 1000</code>")

    user_data = await get_user_data(chat_id, user_id)
    if user_data.get('balance', 0) < bet:
        return await message.answer("В ваших карманах пусто для такой ставки.")

    import uuid
    duel_id = uuid.uuid4().hex[:10]

    proposer_name = escape_html(message.from_user.full_name)
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    active_duels[duel_id] = {
        'state': 'pending',
        'bet': bet,
        'proposer_id': user_id,
        'target_id': target_id,
        'proposer_name': proposer_name,
        'target_name': target_name,
        'timestamp': time.time()
    }

    async def expire_duel(d_id):
        await asyncio.sleep(300)
        if d_id in active_duels and active_duels[d_id]['state'] == 'pending':
            del active_duels[d_id]

    asyncio.create_task(expire_duel(duel_id))

    builder = InlineKeyboardBuilder()
    builder.button(text="Принять вызов 🔫", callback_data=f"duelinv_yes_{duel_id}")
    builder.button(text="Струсить 🏃", callback_data=f"duelinv_no_{duel_id}")

    text = (
        f"🌵 <b>Солнце в зените, пыль под сапогами...</b>\n\n"
        f"Ковбой <b>{proposer_name}</b> бросает вызов <b>{target_name}</b>.\n"
        f"Ставка в этом жестоком споре: <b>{bet}</b> сыроежек.\n\n"
        f"<i>Рука на кобуре. Время покажет, кто из вас быстрее.</i>"
    )

    await message.answer(text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("duelinv_"))
async def callback_duel_invitation(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    action = parts[1]
    duel_id = parts[2]

    if duel_id not in active_duels:
        return await callback.answer("Эта история уже стала местной легендой и больше не актуальна.", show_alert=True)

    duel_info = active_duels[duel_id]
    if duel_info['state'] != 'pending':
        return await callback.answer("Дуэль уже идет полным ходом или завершена.", show_alert=True)

    target_id = duel_info['target_id']
    chat_id = callback.message.chat.id

    if callback.from_user.id != target_id:
        return await callback.answer("Этот вызов брошен не вам, постойте в сторонке.", show_alert=True)

    if action == "no":
        del active_duels[duel_id]
        return await callback.message.edit_text(f"🏃 <b>{duel_info['target_name']}</b> бросил шляпу в пыль и сбежал от дуэли под свист толпы.")

    bet = duel_info['bet']
    proposer_id = duel_info['proposer_id']

    res_prop = await update_user_balance(chat_id, proposer_id, -bet, min_balance=0)
    if res_prop is None:
        del active_duels[duel_id]
        return await callback.message.edit_text("❌ У зачинщика дуэли недостаточно средств. Дуэль отменяется.")

    res_targ = await update_user_balance(chat_id, target_id, -bet, min_balance=0)
    if res_targ is None:
        # Возвращаем ставку proposer
        await update_user_balance(chat_id, proposer_id, bet)
        del active_duels[duel_id]
        return await callback.message.edit_text("❌ У защитника дуэли недостаточно средств. Дуэль отменяется.")

    duel_info['state'] = 'active'
    duel_info['p1'] = {'id': proposer_id, 'name': duel_info['proposer_name'], 'acc': 10, 'cover': False}
    duel_info['p2'] = {'id': target_id, 'name': duel_info['target_name'], 'acc': 10, 'cover': False}
    duel_info['turn'] = proposer_id

    await render_tactical_duel(callback.bot, chat_id, duel_id, message_to_edit=callback.message)


def get_duel_keyboard(duel_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Прищуриться", callback_data=f"tduel_{duel_id}_aim")
    builder.button(text="💥 Спустить курок", callback_data=f"tduel_{duel_id}_shoot")
    builder.button(text="💨 Бросить пыль в глаза", callback_data=f"tduel_{duel_id}_distract")
    builder.button(text="🛡 За бочку", callback_data=f"tduel_{duel_id}_cover")
    builder.adjust(2, 2)
    return builder.as_markup()

async def render_tactical_duel(bot, chat_id: int, duel_id: str, message_to_edit=None, action_text=""):
    if duel_id not in active_duels:
        return

    duel = active_duels[duel_id]
    p1 = duel['p1']
    p2 = duel['p2']

    turn_name = p1['name'] if duel['turn'] == p1['id'] else p2['name']

    p1_cover = "🛡 Прячется за бочкой" if p1['cover'] else ""
    p2_cover = "🛡 Прячется за бочкой" if p2['cover'] else ""

    text = (
        f"🌵 <b>КРОВАВАЯ ДУЭЛЬ</b> 🌵\n\n"
        f"💰 <b>Куш:</b> {duel['bet'] * 2}\n\n"
        f"🤠 <b>{p1['name']}</b>\n"
        f"Меткость: {p1['acc']}% {p1_cover}\n\n"
        f"🤠 <b>{p2['name']}</b>\n"
        f"Меткость: {p2['acc']}% {p2_cover}\n\n"
    )

    if action_text:
        text += f"📜 <i>{action_text}</i>\n\n"

    text += f"⏳ Свинец полетит по команде: <b>{turn_name}</b>"

    keyboard = get_duel_keyboard(duel_id)

    if message_to_edit:
        await message_to_edit.edit_text(text, reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("tduel_"))
async def callback_tactical_duel(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    duel_id = parts[1]
    action = parts[2]

    if duel_id not in active_duels:
        return await callback.answer("Дуэль завершена или не найдена.", show_alert=True)

    duel = active_duels[duel_id]
    if duel['state'] != 'active':
        return await callback.answer("Один уже мертв. Дуэль окончена.", show_alert=True)

    if duel['turn'] != callback.from_user.id:
        return await callback.answer("Спрячь револьвер. Не твой ход!", show_alert=True)

    is_p1 = (callback.from_user.id == duel['p1']['id'])
    me = duel['p1'] if is_p1 else duel['p2']
    enemy = duel['p2'] if is_p1 else duel['p1']

    chat_id = callback.message.chat.id
    action_text = ""

    me['cover'] = False

    if action == "aim":
        me['acc'] = min(100, me['acc'] + 35)
        action_text = f"{me['name']} прищуривает глаз, выцеливая жертву. Шанс попасть: {me['acc']}%."

    elif action == "cover":
        me['cover'] = True
        action_text = f"{me['name']} перекатывается за старую деревянную бочку! В него не попасть."

    elif action == "distract":
        enemy['acc'] = 10
        action_text = f"{me['name']} пинает сапогом песок в глаза противнику! {enemy['name']} ослеплен (меткость 10%)."

    elif action == "shoot":
        import secrets
        rand = secrets.SystemRandom()
        roll = rand.randint(1, 100)

        from config import CREATOR_ID
        is_me_creator = CREATOR_ID and int(me['id']) == int(CREATOR_ID)
        is_enemy_creator = CREATOR_ID and int(enemy['id']) == int(CREATOR_ID)

        from diseases import get_active_diseases
        me_diseases = await get_active_diseases(chat_id, me['id'])
        if 'mycoplasmosis' in me_diseases:
            me['acc'] = 0

        if is_me_creator:
            roll = 0 # Guaranteed hit
            enemy['cover'] = False # Ignore cover
        elif is_enemy_creator:
            roll = 101 # Guaranteed miss

        if enemy['cover']:
            action_text = f"💥 Грохот выстрела! Но пуля {me['name']} лишь пробила бочку, за которой спрятался враг. Промах! (меткость снова 10%)."
            me['acc'] = 10
        elif roll <= me['acc']:
            from economy_utils import get_global_tax
            tax_percent = await get_global_tax()
            pool = duel['bet'] * 2
            tax_amount = int(pool * (tax_percent / 100.0))
            win_amount = pool - tax_amount

            await update_user_balance(chat_id, me['id'], win_amount)

            text = (
                f"💥 <b>СМЕРТЕЛЬНЫЙ ВЫСТРЕЛ!</b> 💥\n\n"
                f"🎯 <b>{me['name']}</b> нажимает на курок (шанс был {me['acc']}%). В яблочко!\n"
                f"☠️ <b>{enemy['name']}</b> хватается за грудь и падает в дорожную пыль замертво.\n\n"
                f"🏆 Победитель <b>{me['name']}</b> забирает <b>{win_amount}</b> сыроежек!"
            )

            if tax_amount > 0:
                text += f"\n<i>(Гробовщик забирает свои {tax_amount} монет)</i>"

            duel['state'] = 'finished'
            del active_duels[duel_id]
            return await callback.message.edit_text(text)
        else:
            action_text = f"💥 {me['name']} спускает курок (шанс {me['acc']}%)... Щелчок, осечка, мимо! (меткость снова 10%)."
            me['acc'] = 10

    duel['turn'] = enemy['id']

    await render_tactical_duel(callback.bot, chat_id, duel_id, message_to_edit=callback.message, action_text=action_text)

# ================= КЛАНЫ =================
async def get_clan_ref(chat_id: int, clan_name: str):
    db = get_db()
    return db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)

active_clan_invites = {}
active_clan_raids = {}

@router.message(Command("clan"))
async def cmd_clan(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    args = message.text.split(maxsplit=2)
    data = await get_user_data(chat_id, user_id, full_name)
    clan_name = data.get('clan')

    if len(args) < 2:
        action = "info"
    else:
        action = args[1].lower()

    if action == "help":
        return await message.answer(
            "🛡 <b>Управление кланом:</b>\n"
            "<code>/clan create [Название]</code> — создать клан (50к сыроежек)\n"
            "<code>/clan invite [reply]</code> — пригласить в клан\n"
            "<code>/clan kick [reply]</code> — выгнать из клана (лидер/заместитель)\n"
            "<code>/clan leave</code> — выйти из клана\n"
            "<code>/clan promote [reply]</code> — назначить Заместителем (лидер)\n"
            "<code>/clan demote [reply]</code> — разжаловать Заместителя (лидер)\n"
            "<code>/clan transfer [reply]</code> — передать лидерство (лидер)\n"
            "<code>/clan disband</code> — распустить клан (лидер)\n"
            "<code>/clan deposit [сумма]</code> — положить в казну\n"
            "<code>/clan withdraw [сумма]</code> — снять из казны (лидер)\n"
            "<code>/clan raid [клан]</code> — совершить набег на другой клан\n"
            "<code>/clan list</code> — список всех кланов чата\n"
            "<code>/clan info</code> — детальная информация о клане"
        )

    elif action in ["info", "status"]:
        if clan_name:
            clan_ref = await get_clan_ref(chat_id, clan_name)
            doc = await clan_ref.get()
            if not doc.exists:
                await update_user_field(chat_id, user_id, 'clan', None)
                return await message.answer("Ваш клан больше не существует.")
            
            clan_data = doc.to_dict()
            leader_data = await get_user_data(chat_id, clan_data['leader_id'])
            leader_name = leader_data.get('full_name', 'Неизвестно')
            
            member_names = []
            for m_id in clan_data.get('members', []):
                m_data = await get_user_data(chat_id, m_id)
                role = ""
                if m_id == clan_data['leader_id']:
                    role = "👑 Лидер"
                elif m_id in clan_data.get('deputy_ids', []):
                    role = "⭐ Заместитель"
                else:
                    role = "👤 Участник"
                member_names.append(f"- <b>{escape_html(m_data.get('full_name', 'Игрок'))}</b> ({role})")
                
            members_str = "\n".join(member_names)
            
            text = (
                f"🛡 <b>Клан: {escape_html(clan_name)}</b>\n\n"
                f"👑 <b>Лидер:</b> {escape_html(leader_name)}\n"
                f"💰 <b>Казна:</b> {clan_data.get('treasury', 0)} сыроежек\n"
                f"👥 <b>Состав ({len(clan_data.get('members', []))}):</b>\n"
                f"{members_str}\n\n"
                f"💡 <i>Используйте <code>/clan help</code>, чтобы посмотреть доступные команды управления кланом.</i>"
            )
            return await message.answer(text)
        else:
            action = "list"

    if action == "list":
        db = get_db()
        clans_ref = db.collection('chats').document(str(chat_id)).collection('clans')
        
        clans_list = []
        async for doc in clans_ref.stream():
            clans_list.append((doc.id, doc.to_dict()))
            
        if not clans_list:
            return await message.answer(
                "🛡 В этом чате пока нет ни одного клана!\n\n"
                "Вы можете создать свой клан, написав:\n"
                "<code>/clan create [Название]</code> — создать (50к сыроежек)"
            )
            
        clans_str = []
        for c_name, c_data in clans_list:
            leader_data = await get_user_data(chat_id, c_data.get('leader_id'))
            leader_name = leader_data.get('full_name', 'Неизвестно')
            clans_str.append(f"- <b>{escape_html(c_name)}</b> (Лидер: <i>{escape_html(leader_name)}</i>, Участников: {len(c_data.get('members', []))}, Казна: {c_data.get('treasury', 0)})")
            
        text = (
            f"🛡 <b>Список кланов чата:</b>\n\n"
            + "\n".join(clans_str) +
            f"\n\n💡 <i>Используйте <code>/clan create [Название]</code>, чтобы создать свой клан (50к сыроежек).</i>"
        )
        return await message.answer(text)

    elif action == "create":
        if clan_name:
            return await message.answer("Вы уже состоите в клане.")
        if len(args) < 3:
            return await message.answer("Укажите название: <code>/clan create Название</code>")

        new_clan_name = args[2]
        clan_ref = await get_clan_ref(chat_id, new_clan_name)
        doc = await clan_ref.get()
        if doc.exists:
            return await message.answer("Клан с таким названием уже существует.")

        res = await update_user_balance(chat_id, user_id, -50000, min_balance=0)
        if res is None:
            return await message.answer("Для создания клана нужно 50.000 сыроежек.")
        await clan_ref.set({
            'leader_id': user_id,
            'deputy_ids': [],
            'treasury': 0,
            'members': [user_id]
        })
        await update_user_field(chat_id, user_id, 'clan', new_clan_name)
        await message.answer(f"🛡 Клан <b>{escape_html(new_clan_name)}</b> успешно создан!")

    elif action == "invite":
        if not clan_name: return await message.answer("Вы не состоите в клане.")
        if not message.reply_to_message: return await message.answer("Сделайте реплай на человека.")

        target_id = message.reply_to_message.from_user.id
        if target_id == user_id or message.reply_to_message.from_user.is_bot: return

        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()

        if user_id != clan_data['leader_id'] and user_id not in clan_data.get('deputy_ids', []):
            return await message.answer("Приглашать могут только Лидер и Заместители.")

        target_data = await get_user_data(chat_id, target_id)
        if target_data.get('clan'): return await message.answer("Пользователь уже в клане.")

        invite_id = f"{chat_id}_{clan_name}_{target_id}_{int(time.time())}"
        active_clan_invites[invite_id] = {'target': target_id, 'clan_name': clan_name}

        builder = InlineKeyboardBuilder()
        builder.button(text="Вступить 🛡", callback_data=f"claninv_yes_{invite_id}")
        builder.button(text="Отказаться ❌", callback_data=f"claninv_no_{invite_id}")

        await message.answer(
            f"🛡 <b>Приглашение в клан!</b>\n\n"
            f"Пользователь <b>{escape_html(message.from_user.full_name)}</b> приглашает <b>{escape_html(message.reply_to_message.from_user.full_name)}</b> вступить в ряды клана <b>{escape_html(clan_name)}</b>.\n\n"
            f"Согласны?",
            reply_markup=builder.as_markup()
        )

    elif action == "kick":
        if not clan_name: return
        if not message.reply_to_message: return
        target_id = message.reply_to_message.from_user.id

        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()

        if user_id != clan_data['leader_id'] and user_id not in clan_data.get('deputy_ids', []):
            return await message.answer("Выгонять участников могут только Лидер и Заместители.")

        if target_id == clan_data['leader_id']:
            return await message.answer("Нельзя кикнуть лидера.")

        if user_id in clan_data.get('deputy_ids', []) and target_id in clan_data.get('deputy_ids', []):
            return await message.answer("Заместитель не может кикнуть другого Заместителя.")

        members = clan_data.get('members', [])
        if target_id in members:
            members.remove(target_id)
            deputy_ids = clan_data.get('deputy_ids', [])
            if target_id in deputy_ids:
                deputy_ids.remove(target_id)
            await clan_ref.update({
                'members': members,
                'deputy_ids': deputy_ids
            })
            await update_user_field(chat_id, target_id, 'clan', None)
            await message.answer("Пользователь изгнан из клана.")

    elif action == "leave":
        if not clan_name: return
        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()

        if user_id == clan_data['leader_id']:
            return await message.answer("Лидер не может просто так покинуть клан. Передайте лидерство (<code>/clan transfer [reply]</code>) или распустите клан (<code>/clan disband</code>).")

        members = clan_data.get('members', [])
        if user_id in members:
            members.remove(user_id)
            deputy_ids = clan_data.get('deputy_ids', [])
            if user_id in deputy_ids:
                deputy_ids.remove(user_id)
            await clan_ref.update({
                'members': members,
                'deputy_ids': deputy_ids
            })
            await update_user_field(chat_id, user_id, 'clan', None)
            await message.answer("Вы покинули клан.")

    elif action == "promote":
        if not clan_name:
            return await message.answer("Вы не состоите в клане.")
        if not message.reply_to_message:
            return await message.answer("Сделайте реплай на человека, которого хотите повысить.")
            
        target_id = message.reply_to_message.from_user.id
        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()
        
        if user_id != clan_data['leader_id']:
            return await message.answer("Повышать участников до Заместителей может только Лидер.")
            
        if target_id not in clan_data.get('members', []):
            return await message.answer("Этот игрок не состоит в вашем клане.")
            
        if target_id == user_id:
            return await message.answer("Вы не можете повысить самого себя.")
            
        deputy_ids = clan_data.get('deputy_ids', [])
        if target_id in deputy_ids:
            return await message.answer("Этот игрок уже является Заместителем.")
            
        deputy_ids.append(target_id)
        await clan_ref.update({'deputy_ids': deputy_ids})
        target_name = escape_html(message.reply_to_message.from_user.full_name)
        await message.answer(f"⭐ Игрок <b>{target_name}</b> успешно назначен Заместителем клана!")

    elif action == "demote":
        if not clan_name:
            return await message.answer("Вы не состоите в клане.")
        if not message.reply_to_message:
            return await message.answer("Сделайте реплай на человека, которого хотите разжаловать.")
            
        target_id = message.reply_to_message.from_user.id
        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()
        
        if user_id != clan_data['leader_id']:
            return await message.answer("Разжаловать заместителей может только Лидер.")
            
        deputy_ids = clan_data.get('deputy_ids', [])
        if target_id not in deputy_ids:
            return await message.answer("Этот игрок не является Заместителем.")
            
        deputy_ids.remove(target_id)
        await clan_ref.update({'deputy_ids': deputy_ids})
        target_name = escape_html(message.reply_to_message.from_user.full_name)
        await message.answer(f"👤 Игрок <b>{target_name}</b> разжалован до обычного Участника.")

    elif action == "disband":
        if not clan_name:
            return await message.answer("Вы не состоите в клане.")
            
        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()
        
        if user_id != clan_data['leader_id']:
            return await message.answer("Распустить клан может только Лидер.")
            
        for m_id in clan_data.get('members', []):
            await update_user_field(chat_id, m_id, 'clan', None)
            
        await clan_ref.delete()
        await message.answer(f"💥 Клан <b>{escape_html(clan_name)}</b> был распущен Лидером!")

    elif action == "transfer":
        if not clan_name:
            return await message.answer("Вы не состоите в клане.")
        if not message.reply_to_message:
            return await message.answer("Сделайте реплай на человека, которому хотите передать лидерство.")
            
        target_id = message.reply_to_message.from_user.id
        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()
        
        if user_id != clan_data['leader_id']:
            return await message.answer("Передать лидерство может только Лидер.")
            
        if target_id not in clan_data.get('members', []):
            return await message.answer("Этот игрок не состоит в вашем клане.")
            
        if target_id == user_id:
            return await message.answer("Вы уже являетесь Лидером.")
            
        deputy_ids = clan_data.get('deputy_ids', [])
        if target_id in deputy_ids:
            deputy_ids.remove(target_id)
            
        await clan_ref.update({
            'leader_id': target_id,
            'deputy_ids': deputy_ids
        })
        target_name = escape_html(message.reply_to_message.from_user.full_name)
        await message.answer(f"👑 Лидерство клана <b>{escape_html(clan_name)}</b> успешно передано ковбою <b>{target_name}</b>!")

    elif action == "deposit":
        if not clan_name: return
        if len(args) < 3: return await message.answer("Укажите сумму или 'all'.")

        balance = data.get('balance', 0)
        amount_str = args[2].lower()
        if amount_str in ["all", "всё", "все"]:
            amount = balance
        else:
            try: amount = int(amount_str)
            except ValueError: return await message.answer("Сумма должна быть числом или 'all'.")

        if amount <= 0: return

        res = await update_user_balance(chat_id, user_id, -amount, min_balance=0)
        if res is None:
            return await message.answer("Недостаточно средств.")

        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        new_treasury = doc.to_dict().get('treasury', 0) + amount
        await clan_ref.update({'treasury': new_treasury})
        await message.answer(f"💰 Вы пожертвовали <b>{amount}</b> в казну клана. Баланс казны: {new_treasury}.")

    elif action == "withdraw":
        if not clan_name: return
        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()

        if user_id != clan_data['leader_id']: return await message.answer("Снимать может только Лидер.")

        if len(args) < 3: return await message.answer("Укажите сумму или 'all'.")

        treasury = clan_data.get('treasury', 0)

        amount_str = args[2].lower()
        if amount_str in ["all", "всё", "все"]:
            amount = treasury
        else:
            try: amount = int(amount_str)
            except ValueError: return await message.answer("Сумма должна быть числом или 'all'.")

        if amount <= 0: return
        if treasury < amount: return await message.answer(f"В казне недостаточно средств (Доступно: {treasury}).")

        from economy_utils import get_global_tax, calculate_progressive_tax
        base_tax = await get_global_tax()
        neg_lvl = data.get('skills', {}).get('negotiation', 0)
        tax_percent = calculate_progressive_tax(data.get('balance', 0), base_tax, neg_lvl)

        from diseases import get_active_diseases
        active_diseases = await get_active_diseases(chat_id, user_id)
        if 'cytomegalovirus' in active_diseases:
            tax_percent = min(90, tax_percent * 2)

        tax_amount = int(amount * (tax_percent / 100.0))
        net_amount = amount - tax_amount

        await update_user_balance(chat_id, user_id, net_amount)
        await clan_ref.update({'treasury': treasury - amount})
        await message.answer(f"💸 Вы сняли <b>{amount}</b> из казны. Удержан налог {tax_amount}. На руки получено: {net_amount}.")

    elif action in ["raid", "attack"]:
        if not clan_name:
            return await message.answer("Вы не состоите в клане.")
            
        clan_ref = await get_clan_ref(chat_id, clan_name)
        doc = await clan_ref.get()
        clan_data = doc.to_dict()
        
        if user_id != clan_data['leader_id'] and user_id not in clan_data.get('deputy_ids', []):
            return await message.answer("Организовывать набеги могут только Лидер и Заместители.")
            
        if len(args) < 3:
            return await message.answer("Укажите клан для нападения: <code>/clan raid [Название]</code>")
            
        target_clan_name = " ".join(args[2:])
        if target_clan_name.lower() == clan_name.lower():
            return await message.answer("Нельзя напасть на свой же клан.")
            
        target_clan_ref = await get_clan_ref(chat_id, target_clan_name)
        t_doc = await target_clan_ref.get()
        
        if not t_doc.exists:
            return await message.answer("Вражеский клан не найден.")
            
        target_clan_data = t_doc.to_dict()
        
        my_treasury = clan_data.get('treasury', 0)
        t_treasury = target_clan_data.get('treasury', 0)
        
        if my_treasury < 1000:
            return await message.answer("В вашей казне должно быть минимум 1000 сыроежек для организации набега.")
        if t_treasury < 1000:
            return await message.answer("У вражеского клана слишком бедная казна (меньше 1000), набег не имеет смысла.")
            
        raid_key = f"{chat_id}_{clan_name}"
        current_time = time.time()
        if raid_key in active_clan_raids and current_time - active_clan_raids[raid_key] < 3600:
            rem = 3600 - int(current_time - active_clan_raids[raid_key])
            return await message.answer(f"Ваши бойцы устали. Следующий набег возможен через {rem//60} мин.")
            
        active_clan_raids[raid_key] = current_time
        
        import random
        my_members = len(clan_data.get('members', []))
        t_members = len(target_clan_data.get('members', []))
        
        base_chance = 50
        bonus = (my_members - t_members) * 5
        chance = max(10, min(90, base_chance + bonus))
        
        from config import CREATOR_ID
        is_attacker_creator_clan = CREATOR_ID and int(clan_data.get('leader_id', 0)) == int(CREATOR_ID)
        is_defender_creator_clan = CREATOR_ID and int(target_clan_data.get('leader_id', 0)) == int(CREATOR_ID)
        
        roll = random.randint(1, 100)
        success = False
        if is_attacker_creator_clan:
            success = True
        elif is_defender_creator_clan:
            success = False
        else:
            success = (roll <= chance)

        if success:
            steal_pct = random.randint(10, 25) / 100.0
            stolen = int(t_treasury * steal_pct)
            
            await target_clan_ref.update({'treasury': t_treasury - stolen})
            await clan_ref.update({'treasury': my_treasury + stolen})
            
            await message.answer(
                f"⚔️ <b>УСПЕШНЫЙ НАБЕГ!</b>\n\n"
                f"Ваш клан <b>{escape_html(clan_name)}</b> внезапно атаковал клан <b>{escape_html(target_clan_name)}</b>.\n"
                f"Защитники были застигнуты врасплох!\n\n"
                f"Вы разграбили вражескую казну и украли <b>{stolen}</b> сыроежек! 💰"
            )
        else:
            lose_pct = random.randint(10, 25) / 100.0
            lost = int(my_treasury * lose_pct)
            
            await clan_ref.update({'treasury': my_treasury - lost})
            
            if is_defender_creator_clan:
                await message.answer(
                    f"🛡 <b>ПРОВАЛ НАБЕГА!</b>\n\n"
                    f"Вы попытались напасть на клан Создателя <b>{escape_html(target_clan_name)}</b>, но получили по лицу от админской мощи! 💥\n"
                    f"В панике ваши бойцы бросили <b>{lost}</b> сыроежек. 📉"
                )
            else:
                await message.answer(
                    f"🛡 <b>ПРОВАЛ НАБЕГА!</b>\n\n"
                    f"Клан <b>{escape_html(target_clan_name)}</b> дал жесткий отпор вашему нападению.\n"
                    f"В панике ваши бойцы потеряли часть своей казны: <b>{lost}</b> сыроежек. 📉"
                )

# --- ОБРАБОТЧИК КНОПОК ДЛЯ КЛАНА ---
@router.callback_query(F.data.startswith("claninv_"))
async def callback_claninv(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    invite_id = callback.data.replace(f"claninv_{action}_", "")

    if invite_id not in active_clan_invites:
        return await callback.answer("Приглашение больше не действительно.", show_alert=True)

    invite_info = active_clan_invites.pop(invite_id)
    target_id = invite_info['target']
    clan_name = invite_info['clan_name']
    chat_id = callback.message.chat.id

    if callback.from_user.id != target_id:
        active_clan_invites[invite_id] = invite_info # Возвращаем в словарь, т.к. нажал не тот
        return await callback.answer("Это приглашение не для вас!", show_alert=True)

    if action == "no":
        return await callback.message.edit_text("❌ Приглашение в клан отклонено.")

    # Логика согласия
    target_data = await get_user_data(chat_id, target_id)
    if target_data.get('clan'):
        return await callback.message.edit_text("❌ Пользователь уже состоит в другом клане.")

    clan_ref = await get_clan_ref(chat_id, clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await callback.message.edit_text("❌ Этот клан больше не существует.")

    clan_data = doc.to_dict()
    members = clan_data.get('members', [])
    members.append(target_id)
    
    await clan_ref.update({'members': members})
    await update_user_field(chat_id, target_id, 'clan', clan_name)
    await callback.message.edit_text(f"✅ <b>{escape_html(callback.from_user.full_name)}</b> успешно вступил(а) в клан <b>{escape_html(clan_name)}</b>!")