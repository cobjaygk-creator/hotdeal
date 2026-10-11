import time

import pytest

import app.main as main_mod


@pytest.mark.asyncio
async def test_watchdog_warns_without_killing_web_server_when_stale(monkeypatch, caplog):
    monkeypatch.setattr(main_mod, "WATCHDOG_STALE_MINUTES", 5)
    monkeypatch.setitem(main_mod.state, "last_collect_ts", time.monotonic() - 6 * 60)

    def fake_exit(code):
        raise AssertionError("upstream outages must not kill the web server")

    monkeypatch.setattr(main_mod.os, "_exit", fake_exit)
    await main_mod._scheduled_watchdog()
    assert "collection degraded" in caplog.text


@pytest.mark.asyncio
async def test_watchdog_stays_quiet_when_fresh(monkeypatch):
    monkeypatch.setattr(main_mod, "WATCHDOG_STALE_MINUTES", 5)
    monkeypatch.setitem(main_mod.state, "last_collect_ts", time.monotonic())

    def fake_exit(code):  # pragma: no cover - must not run
        raise AssertionError("watchdog should not exit while fresh")

    monkeypatch.setattr(main_mod.os, "_exit", fake_exit)
    await main_mod._scheduled_watchdog()  # no raise = passed


@pytest.mark.asyncio
async def test_watchdog_noop_before_first_tick(monkeypatch):
    monkeypatch.delitem(main_mod.state, "last_collect_ts", raising=False)

    def fake_exit(code):  # pragma: no cover - must not run
        raise AssertionError("watchdog should not exit with no baseline yet")

    monkeypatch.setattr(main_mod.os, "_exit", fake_exit)
    await main_mod._scheduled_watchdog()
