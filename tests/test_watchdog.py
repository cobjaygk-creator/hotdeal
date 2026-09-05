import time

import pytest

import app.main as main_mod


@pytest.mark.asyncio
async def test_watchdog_exits_when_stale(monkeypatch):
    monkeypatch.setattr(main_mod, "WATCHDOG_STALE_MINUTES", 5)
    main_mod.state["last_collect_ts"] = time.monotonic() - 6 * 60

    called = {}

    def fake_exit(code):
        called["code"] = code
        raise SystemExit(code)

    monkeypatch.setattr(main_mod.os, "_exit", fake_exit)
    with pytest.raises(SystemExit):
        await main_mod._scheduled_watchdog()
    assert called["code"] == 1


@pytest.mark.asyncio
async def test_watchdog_stays_quiet_when_fresh(monkeypatch):
    monkeypatch.setattr(main_mod, "WATCHDOG_STALE_MINUTES", 5)
    main_mod.state["last_collect_ts"] = time.monotonic()

    def fake_exit(code):  # pragma: no cover - must not run
        raise AssertionError("watchdog should not exit while fresh")

    monkeypatch.setattr(main_mod.os, "_exit", fake_exit)
    await main_mod._scheduled_watchdog()  # no raise = passed


@pytest.mark.asyncio
async def test_watchdog_noop_before_first_tick(monkeypatch):
    main_mod.state.pop("last_collect_ts", None)

    def fake_exit(code):  # pragma: no cover - must not run
        raise AssertionError("watchdog should not exit with no baseline yet")

    monkeypatch.setattr(main_mod.os, "_exit", fake_exit)
    await main_mod._scheduled_watchdog()
