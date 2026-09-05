"""Rate-limit behaviour for the outbound Telegram sender.

Regression cover for 2026-09-05: a 126-instance HoneypotSilent alert storm made
the gateway post sendMessage ~7x/sec for days. Telegram answered 429 with
retry_after up to 18h; the sender ignored it, re-posted every failure a second
time as a "formatting" retry, and built a fresh TLS connection per message —
burning ~14% of the host CPU while delivering nothing.
"""

import time

import pytest

from telegram_gateway import bot


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Records every POST so tests can count real network attempts."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    async def post(self, url, json=None, **kw):
        self.calls.append(json)
        payload = self._responses.pop(0) if self._responses else {"ok": True}
        return FakeResponse(payload)


TOO_MANY = {
    "ok": False,
    "error_code": 429,
    "description": "Too Many Requests: retry after 300",
    "parameters": {"retry_after": 300},
}
BAD_HTML = {
    "ok": False,
    "error_code": 400,
    "description": "Bad Request: can't parse entities",
}


@pytest.fixture(autouse=True)
def _clear_cooldown():
    bot.reset_send_state()
    yield
    bot.reset_send_state()


async def test_429_does_not_trigger_the_plaintext_retry(monkeypatch):
    """A rate-limit is not a formatting problem — retrying doubled the load."""
    client = FakeClient(TOO_MANY)
    monkeypatch.setattr(bot, "_get_client", lambda: client)

    await bot.send_telegram_message(1, "hello")

    assert len(client.calls) == 1


async def test_429_opens_a_cooldown_that_suppresses_later_sends(monkeypatch):
    """After a 429 the sender must stop dialling Telegram until retry_after."""
    client = FakeClient(TOO_MANY)
    monkeypatch.setattr(bot, "_get_client", lambda: client)

    await bot.send_telegram_message(1, "first")
    assert len(client.calls) == 1

    await bot.send_telegram_message(1, "second")
    await bot.send_telegram_message(1, "third")
    assert len(client.calls) == 1, "cooldown must short-circuit before any HTTP call"


async def test_cooldown_expires(monkeypatch):
    client = FakeClient(
        {"ok": False, "error_code": 429, "description": "slow down",
         "parameters": {"retry_after": 0}},
    )
    monkeypatch.setattr(bot, "_get_client", lambda: client)

    await bot.send_telegram_message(1, "first")
    time.sleep(0.01)
    await bot.send_telegram_message(1, "second")
    assert len(client.calls) == 2, "a zero-length cooldown must not block forever"


async def test_400_still_falls_back_to_plaintext(monkeypatch):
    """The formatting fallback is still valuable — just not for 429s."""
    client = FakeClient(BAD_HTML, {"ok": True})
    monkeypatch.setattr(bot, "_get_client", lambda: client)

    await bot.send_telegram_message(1, "<b>hi</b>", parse_mode="HTML")

    assert len(client.calls) == 2
    assert "parse_mode" not in client.calls[1]


async def test_client_is_reused_across_sends():
    """A fresh AsyncClient per message meant a TLS handshake per message."""
    bot.reset_send_state()
    first = bot._get_client()
    second = bot._get_client()
    assert first is second
