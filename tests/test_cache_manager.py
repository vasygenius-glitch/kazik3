import time
import unittest
from utils_pkg.cache_manager import CacheManager

class TestCacheManager(unittest.TestCase):
    def setUp(self):
        self.cache = CacheManager(default_ttl=0.1)

    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")

    def test_expiration(self):
        self.cache.set("key2", "value2", ttl=0.1)
        self.assertEqual(self.cache.get("key2"), "value2")
        time.sleep(0.15)
        self.assertIsNone(self.cache.get("key2"))

    def test_delete(self):
        self.cache.set("key3", "value3")
        self.cache.delete("key3")
        self.assertIsNone(self.cache.get("key3"))

    def test_clear(self):
        self.cache.set("k", "v")
        self.cache.clear()
        self.assertIsNone(self.cache.get("k"))
