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
        class MockTransaction:
            def __init__(self):
                pass

            def get(self, ref):
                # Returns awaitable in mock
                return ref.get()

            def update(self, ref, data):
                from utils import fire_and_forget
                fire_and_forget(ref.update(data))

            def set(self, ref, data, merge=False):
                from utils import fire_and_forget
                fire_and_forget(ref.set(data, merge=merge))

        class MockDB:
            def __init__(self):
                self.data = {}

            def collection(self, name):
                return MockCollection(self.data, name)

            def batch(self):
                return MockBatch()

            def transaction(self):
                return MockTransaction()

        class MockBatch:
            def __init__(self):
                self.ops = []

            def set(self, doc_ref, data, merge=False):
                self.ops.append(('set', doc_ref, data, merge))

            def update(self, doc_ref, data):
                self.ops.append(('update', doc_ref, data))

            def delete(self, doc_ref):
                self.ops.append(('delete', doc_ref))

            async def commit(self):
                for op_data in self.ops:
                    op = op_data[0]
                    if op == 'set':
                        _, doc_ref, data, merge = op_data
                        await doc_ref.set(data, merge=merge)
                    elif op == 'update':
                        _, doc_ref, data = op_data
                        await doc_ref.update(data)
                    elif op == 'delete':
                        _, doc_ref = op_data
                        await doc_ref.delete()
                self.ops = []

        class MockCollection:
            def __init__(self, parent_dict, name):
                if name not in parent_dict:
                    parent_dict[name] = {}
                self.data = parent_dict[name]

            def document(self, name):
                return MockDocument(self.data, str(name))

            async def get(self):
                class MockDocStream:
                    def __init__(self, id, data):
                        self.id = id
                        self._data = data
                    def to_dict(self): return self._data

                results = []
                for doc_id, doc_data in self.data.items():
                    if '_data' in doc_data:
                        results.append(MockDocStream(doc_id, doc_data['_data']))
                return results

            async def stream(self):
                class MockDocStream:
                    def __init__(self, id, data):
                        self.id = id
                        self._data = data
                    def to_dict(self): return self._data

                for doc_id, doc_data in self.data.items():
                    # Return only docs that actually have data (not just subcollections)
                    if '_data' in doc_data:
                        yield MockDocStream(doc_id, doc_data['_data'])

        class MockDocument:
            def __init__(self, parent_dict, name):
                if name not in parent_dict:
                    parent_dict[name] = {}
                self.doc_node = parent_dict[name]

            def collection(self, name):
                if '_subcollections' not in self.doc_node:
                    self.doc_node['_subcollections'] = {}
                return MockCollection(self.doc_node['_subcollections'], name)

            async def get(self, **kwargs):
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

            async def delete(self):
                if '_data' in self.doc_node:
                    del self.doc_node['_data']
        db = MockDB()
        return db

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore_async.client()
    return db


def get_db():
    return db
