"""Regression: a copied Markdown URL must not break /start and /v2."""
from unittest.mock import AsyncMock

import pytest

from v2 import links
from v2.security import parse_chat_token

BASE = 'https://example.hf.space'


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ('V2_WEBAPP_URL', 'PUBLIC_URL', 'SPACE_HOST'):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize('raw', [BASE, BASE+'/', BASE+'/app', BASE+'/app/',
    f'[{BASE}]({BASE})', f'[{BASE}]({BASE})/app/',
    f'[Открыть]({BASE}/app/)', f'<{BASE}/app/>', BASE+'/app/?c=old#fragment'])
def test_copied_urls(monkeypatch, raw):
    monkeypatch.setenv('V2_WEBAPP_URL', raw)
    assert links.webapp_url() == BASE+'/app/'
    button = links.webapp_markup(-100123).inline_keyboard[0][0]
    from urllib.parse import urlsplit, parse_qs
    assert parse_chat_token(parse_qs(urlsplit(button.web_app.url).query)['c'][0]) == -100123


@pytest.mark.parametrize('raw', ['http://example.com', 'https://', 'javascript:alert(1)',
    'https://example.com:abc', 'https://user:pass@example.com',
    'https://example.com:80', 'https://exam ple.com', 'https://[broken',
    'not a URL', 'https://example.com/invalid[path]'])
def test_invalid_url_is_safe(monkeypatch, raw):
    monkeypatch.setenv('V2_WEBAPP_URL', raw)
    assert links.webapp_url() == ''
    assert links.webapp_markup(-100123) is None


def test_space_host_fallback(monkeypatch):
    monkeypatch.setenv('V2_WEBAPP_URL', 'broken')
    monkeypatch.setenv('SPACE_HOST', 'example.hf.space')
    assert links.webapp_url() == BASE+'/app/'


@pytest.mark.asyncio
async def test_start_has_group_bound_button(monkeypatch):
    from types import SimpleNamespace
    from economy import cmd_start
    import economy
    import user_manager
    from v2 import settings
    monkeypatch.setenv('SPACE_HOST', 'example.hf.space')
    monkeypatch.setattr(economy, 'get_user_data', AsyncMock(return_value={}))
    monkeypatch.setattr(user_manager, 'load_user_primary_chat', AsyncMock(return_value=-100123))
    monkeypatch.setattr(settings, 'enabled', AsyncMock(return_value=True))
    message = SimpleNamespace(chat=SimpleNamespace(id=42, type='private'),
        from_user=SimpleNamespace(id=42, full_name='<Гриб>'), answer=AsyncMock())
    await cmd_start(message)
    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert '&lt;Гриб&gt;' in args[0]
    assert kwargs['reply_markup'].inline_keyboard[0][0].web_app.url.startswith(BASE+'/app/?c=')
