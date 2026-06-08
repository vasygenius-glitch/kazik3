import asyncio
from config import FIREBASE_KEY_PATH
from db import init_db, get_db
from admin_dashboard import parse_clan_callback

async def main():
    try:
        init_db(FIREBASE_KEY_PATH)
    except Exception as e:
        print(f"Database init failed: {e}")
    
    cb_data = "db_clan_view_-1002321279920_DICKторы Тайний Баний"
    chat_id, clan_name, member_id = await parse_clan_callback(cb_data)
    print(f"Parsed info:\nchat_id: {chat_id}\nclan_name: '{clan_name}'\nmember_id: {member_id}")

if __name__ == "__main__":
    asyncio.run(main())
