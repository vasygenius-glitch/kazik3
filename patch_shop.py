with open('shop.py', 'r') as f:
    content = f.read()

old_code = """    await callback.answer(f"Куплено: {item['name']}!", show_alert=True)
    await show_category(callback)"""

new_code = """    await callback.answer(f"Куплено: {item['name']}!", show_alert=True)

    # Refresh data and render category
    data = await get_user_data(chat_id, user_id)
    base_tax = await get_global_tax()
    category = item.get('cat', 'other')
    cats_names = {"biz": "Бизнесы", "cars": "Машины", "other": "Разное"}
    text = f"📂 <b>Категория: {cats_names.get(category)}</b>\n\nВыбери товар для покупки (цены указаны с учетом твоего налога):"
    await callback.message.edit_text(text, reply_markup=get_category_kb(category, data.get('balance', 0), base_tax, data.get('skills', {}).get('negotiation', 0)))"""

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('shop.py', 'w') as f:
        f.write(content)
    print("Patched successfully!")
else:
    print("Code block not found!")
