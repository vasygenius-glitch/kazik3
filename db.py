import os
import json
import copy
import tempfile
from pathlib import Path
import logging
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
            # Never silently replace a corrupt database with an empty one.
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Local database root must be an object")
            self.data = data

    def save(self):
        """Atomic replacement; interrupted serialization preserves the old file.

        This development backend is single-process, not a Firestore substitute.
        Persistence errors propagate so the write-behind cache can retry.
        """
        target = Path(self.filepath).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=target.parent, prefix=target.name + '.',
                                             suffix='.tmp', delete=False) as f:
                temp_path = f.name
                json.dump(self.data, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

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
                self._data = copy.deepcopy(data or {})
            def to_dict(self): return copy.deepcopy(self._data)

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
    backend = os.environ.get("DB_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "firestore", "local"}:
        raise ValueError("DB_BACKEND must be auto, firestore or local")
    fb_config = os.environ.get("FIREBASE_JSON")
    has_credentials = bool(fb_config) or bool(key_path and os.path.exists(key_path))
    if backend == "local" or (backend == "auto" and not has_credentials):
        db = MockDB(os.environ.get("LOCAL_DB_PATH", "data/local_db.json"))
        logging.getLogger(__name__).warning(
            "Local development database selected; use Firestore for production transactions")
        return db
    if not has_credentials:
        raise RuntimeError("Firestore credentials are required for DB_BACKEND=firestore")
    # Fail closed: switching to unrelated balances on a Firebase error is unsafe.
    try:
        cred = credentials.Certificate(json.loads(fb_config) if fb_config else key_path)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        client = firestore_async.client()
    except Exception:
        raise RuntimeError("Firebase initialization failed; local fallback is disabled") from None
    db = client
    return db



def get_db():
    global db
    if db is None:
        from config import FIREBASE_KEY_PATH
        init_db(FIREBASE_KEY_PATH)
    return db

