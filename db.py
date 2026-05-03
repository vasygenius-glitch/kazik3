import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore_async
import os

db = None

def init_db(key_path):
    global db
    import json

    # Сначала проверяем переменную окружения FIREBASE_JSON (секрет из HF Spaces)
    fb_config = os.environ.get("FIREBASE_JSON")
    cred = None

    if fb_config:
        try:
            cred_dict = json.loads(fb_config)
            cred = credentials.Certificate(cred_dict)
            print("✅ Загружен ключ Firebase из переменной окружения (Секрета).")
        except Exception as e:
            print(f"❌ Ошибка парсинга FIREBASE_JSON: {e}")
    # Если переменной нет, пробуем прочитать из файла (для локального тестирования)
    elif os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        print(f"✅ Загружен ключ Firebase из файла: {key_path}")

    # Если мы так и не получили ключ (нет файла и нет секретов)
    if not cred:
        print("ВНИМАНИЕ: Ключ Firebase не найден ни в FIREBASE_JSON, ни в файле!")
        print("Бот будет работать в режиме мок-базы, или упадет при запросах.")
        class MockDB:
            def __init__(self):
                self.data = {}

            def collection(self, name):
                return MockCollection(self.data, name)

        class MockCollection:
            def __init__(self, parent_dict, name):
                if name not in parent_dict:
                    parent_dict[name] = {}
                self.data = parent_dict[name]

            def document(self, name):
                return MockDocument(self.data, str(name))

            async def get(self):
                class MockDocStream:
                    def __init__(self, data):
                        self._data = data
                    def to_dict(self): return self._data

                results = []
                for doc_id, doc_data in self.data.items():
                    if '_data' in doc_data:
                        results.append(MockDocStream(doc_data['_data']))
                return results

            async def stream(self):
                class MockDocStream:
                    def __init__(self, data):
                        self._data = data
                    def to_dict(self): return self._data

                for doc_id, doc_data in self.data.items():
                    # Return only docs that actually have data (not just subcollections)
                    if '_data' in doc_data:
                        yield MockDocStream(doc_data['_data'])

        class MockDocument:
            def __init__(self, parent_dict, name):
                if name not in parent_dict:
                    parent_dict[name] = {}
                self.doc_node = parent_dict[name]

            def collection(self, name):
                if '_subcollections' not in self.doc_node:
                    self.doc_node['_subcollections'] = {}
                return MockCollection(self.doc_node['_subcollections'], name)

            async def get(self):
                class MockDocRes:
                    def __init__(self, exists, data=None):
                        self.exists = exists
                        self._data = data or {}
                    def to_dict(self): return self._data

                if '_data' in self.doc_node:
                    return MockDocRes(True, self.doc_node['_data'])
                return MockDocRes(False)

            async def set(self, data, merge=False):
                if merge and '_data' in self.doc_node:
                    self.doc_node['_data'].update(data)
                else:
                    self.doc_node['_data'] = data

            async def update(self, data):
                if '_data' in self.doc_node:
                    self.doc_node['_data'].update(data)
        db = MockDB()
        return db

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore_async.client()
    return db


def get_db():
    return db
