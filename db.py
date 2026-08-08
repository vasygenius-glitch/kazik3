import os
import json
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore_async

db = None

class MockTransaction:
    def __init__(self):
        self._read_only = False
        self._id = b"mock"
        self._max_attempts = 5

    async def _begin(self, retry_id=None): pass
    async def _rollback(self): pass
    async def _commit(self): pass
    def _clean_up(self): pass

    def get(self, ref):
        return ref.get()

    def update(self, ref, data):
        if hasattr(ref, 'doc_node'):
            if '_data' in ref.doc_node:
                ref.doc_node['_data'].update(data)
            else:
                ref.doc_node['_data'] = data
            ref.db_instance.save()
        else:
            from utils import fire_and_forget
            fire_and_forget(ref.update(data))

    def set(self, ref, data, merge=False):
        if hasattr(ref, 'doc_node'):
            if merge and '_data' in ref.doc_node:
                ref.doc_node['_data'].update(data)
            else:
                ref.doc_node['_data'] = data
            ref.db_instance.save()
        else:
            from utils import fire_and_forget
            fire_and_forget(ref.set(data, merge=merge))

class MockDB:
    def __init__(self, filepath="data/local_db.json"):
        self.filepath = filepath
        self.data = {}
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                print(f"✅ Локальная база данных успешно загружена из {self.filepath}")
            except Exception as e:
                print(f"⚠️ Ошибка чтения {self.filepath}: {e}")

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка сохранения локальной БД: {e}")

    def collection(self, name):
        return MockCollection(self, self.data, name)

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
    def __init__(self, db_instance, parent_dict, name):
        self.db_instance = db_instance
        if name not in parent_dict:
            parent_dict[name] = {}
        self.data = parent_dict[name]

    def document(self, name):
        return MockDocument(self.db_instance, self.data, str(name))

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
            if '_data' in doc_data:
                yield MockDocStream(doc_id, doc_data['_data'])

class MockDocument:
    def __init__(self, db_instance, parent_dict, name):
        self.db_instance = db_instance
        if name not in parent_dict:
            parent_dict[name] = {}
        self.doc_node = parent_dict[name]

    def collection(self, name):
        if '_subcollections' not in self.doc_node:
            self.doc_node['_subcollections'] = {}
        return MockCollection(self.db_instance, self.doc_node['_subcollections'], name)

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
        self.db_instance.save()

    async def update(self, data):
        if '_data' in self.doc_node:
            self.doc_node['_data'].update(data)
        else:
            self.doc_node['_data'] = data
        self.db_instance.save()

    async def delete(self):
        if '_data' in self.doc_node:
            del self.doc_node['_data']
        self.db_instance.save()


def init_db(key_path):
    global db
    import json

    fb_config = os.environ.get("FIREBASE_JSON")
    cred = None

    if fb_config:
        try:
            cred_dict = json.loads(fb_config)
            cred = credentials.Certificate(cred_dict)
            print("✅ Загружен ключ Firebase из переменной окружения (Секрета).")
        except Exception as e:
            print(f"❌ Ошибка парсинга FIREBASE_JSON: {e}")
    elif os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        print(f"✅ Загружен ключ Firebase из файла: {key_path}")

    # При наличии ключа подключаем основной Firebase Firestore с реальными балансами
    if cred:
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            db = firestore_async.client()
            print("✅ Подключена основная база Firebase Firestore. Все балансы и инвентари доступны!")
            return db
        except Exception as e:
            print(f"⚠️ Переключение на локальную БД из-за ошибки Firebase: {e}")
            db = MockDB()
            return db

    print("[DB] Инициализирована локальная база данных (data/local_db.json).")
    db = MockDB()
    return db



def get_db():
    global db
    if db is None:
        init_db("firebase-key.json")
    return db

