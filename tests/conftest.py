"""Isolate test collection from credentials and live services."""
import atexit
import os
import socket
import tempfile
from pathlib import Path
import dotenv

_temp = tempfile.TemporaryDirectory(prefix="kazik-tests-")
atexit.register(_temp.cleanup)
_root = Path(_temp.name)
os.environ.update({
    "DB_BACKEND": "local", "LOCAL_DB_PATH": str(_root / "database.json"),
    "BATTLE_PASS_PATH": str(_root / "battle_pass.json"),
    "FIREBASE_KEY_PATH": str(_root / "no-credentials.json"),
    "FIREBASE_JSON": "", "REDIS_URL": "", "DATABASE_URL": "", "MONGO_URI": "",
    "BOT_TOKEN": "123456789:" + "T" * 35, "ENABLE_ADMIN_EVAL": "false",
})
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
_original_dotenv = dotenv.load_dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


def _check_address(address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
        raise RuntimeError("Tests may not connect to external services")


def _connect(sock, address):
    _check_address(address)
    return _original_connect(sock, address)


def _connect_ex(sock, address):
    _check_address(address)
    return _original_connect_ex(sock, address)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex


def pytest_unconfigure(config):
    dotenv.load_dotenv = _original_dotenv
    socket.socket.connect = _original_connect
    socket.socket.connect_ex = _original_connect_ex
