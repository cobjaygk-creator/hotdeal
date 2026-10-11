import asyncio

import pytest

import app.collection_guard as guard
import app.main as main
from app.db import connect
from app.pipeline import collect_and_process


class Source:
    def __init__(self, name, fetch):
        self.name = name
        self.fetch_latest = fetch


@pytest.mark.asyncio
async def test_timeout_cancels_source_then_collects_next_and_cools_down(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "SOURCE_FETCH_TIMEOUT_SECONDS", .02)
    calls = []
    cancelled = asyncio.Event()

    async def stalled(_):
        calls.append("stalled")
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def healthy(_):
        calls.append("healthy")
        return []

    sources = [Source("stalled", stalled), Source("healthy", healthy)]
    failures = {}
    results = await guard.fetch_sources(sources, object(), failures)
    assert cancelled.is_set()
    assert calls == ["stalled", "healthy"]
    conn = await connect(tmp_path / "guard.db")
    try:
        summary = await collect_and_process(conn, results, object())
        assert "total budget" in summary["sources"]["stalled"]["error"]
        assert summary["sources"]["healthy"]["fetched"] == 0
    finally:
        await conn.close()
    await guard.fetch_sources(sources, object(), failures)
    assert calls == ["stalled", "healthy", "healthy"]
    failures["stalled"] = 0
    await guard.fetch_sources([Source("stalled", healthy)], object(), failures)
    assert "stalled" not in failures


@pytest.mark.asyncio
async def test_fetch_cancellation_propagates_without_cooldown():
    async def cancelled(_):
        raise asyncio.CancelledError

    failures = {}
    with pytest.raises(asyncio.CancelledError):
        await guard.fetch_sources([Source("cancel", cancelled)], object(), failures)
    assert not failures


@pytest.mark.asyncio
async def test_slow_fetch_does_not_block_another_tier_db_work(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    lock = asyncio.Lock()
    monkeypatch.setitem(main.state, "collect_lock", lock)
    monkeypatch.setitem(main.state, "http", object())
    monkeypatch.setitem(main.state, "source_failures", {})

    async def slow(_):
        started.set()
        await release.wait()
        return []

    async def fast(_):
        return []

    sources = {"slow": Source("slow", slow), "fast": Source("fast", fast)}
    monkeypatch.setattr(main, "get_sources", lambda names: [sources[n] for n in names])

    async def save(names, *, sources):
        assert lock.locked()
        assert await sources[0].fetch_latest(None) == []
        return {"saved": names[0]}

    monkeypatch.setattr(main, "_run_collect", save)
    task = asyncio.create_task(main._run_collect_serialized(["slow"]))
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert not lock.locked()
        result = await asyncio.wait_for(main._run_collect_serialized(["fast"]), 1)
        assert result == {"saved": "fast"}
        release.set()
        assert await task == {"saved": "slow"}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_writer_deadline_releases_lock_and_runs_cleanup(monkeypatch):
    lock = asyncio.Lock()
    monkeypatch.setitem(main.state, "collect_lock", lock)
    monkeypatch.setattr(main, "COLLECTION_SLOT_TIMEOUT_SECONDS", .02)
    cleaned = False
    with pytest.raises(TimeoutError):
        async with main._collection_slot():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned = True
    assert cleaned and not lock.locked()
    async with main._collection_slot():
        assert lock.locked()


@pytest.mark.asyncio
async def test_writer_wait_deadline_does_not_release_another_tasks_lock(monkeypatch):
    lock = asyncio.Lock()
    monkeypatch.setitem(main.state, "collect_lock", lock)
    monkeypatch.setattr(main, "COLLECTION_SLOT_TIMEOUT_SECONDS", .02)
    async with lock:
        with pytest.raises(TimeoutError):
            async with main._collection_slot():
                pytest.fail("must not enter while another writer owns the lock")
        assert lock.locked()


@pytest.mark.asyncio
async def test_timed_out_transaction_rolls_back_and_next_writer_can_commit(monkeypatch, tmp_path):
    path = tmp_path / "rollback.db"
    conn = await connect(path)
    await conn.close()

    async def open_db():
        return await connect(path)

    monkeypatch.setattr(main, "connect", open_db)
    monkeypatch.setitem(main.state, "collect_lock", asyncio.Lock())
    monkeypatch.setattr(main, "COLLECTION_SLOT_TIMEOUT_SECONDS", 2)
    with pytest.raises(TimeoutError):
        async with main._collection_slot():
            async with main._own_db() as conn:
                await conn.execute("INSERT INTO meta(key,value) VALUES('cancelled','1')")
                await asyncio.Event().wait()
    monkeypatch.setattr(main, "COLLECTION_SLOT_TIMEOUT_SECONDS", 5)
    async with main._collection_slot():
        async with main._own_db() as conn:
            cur = await conn.execute("SELECT value FROM meta WHERE key='cancelled'")
            assert await cur.fetchone() is None
            await conn.execute("INSERT INTO meta(key,value) VALUES('recovered','1')")
            await conn.commit()


@pytest.mark.asyncio
async def test_cancelled_db_initialization_closes_unreturned_connection(monkeypatch, tmp_path):
    import app.db as db

    captured = []

    async def cancelled_init(conn):
        captured.append(conn)
        await conn.execute("INSERT INTO meta(key,value) VALUES('pending','1')")
        raise asyncio.CancelledError

    monkeypatch.setattr(db, "_ensure_columns", cancelled_init)
    with pytest.raises(asyncio.CancelledError):
        await db.connect(tmp_path / "init.db")
    assert len(captured) == 1
    with pytest.raises(ValueError, match="no active connection"):
        await captured[0].execute("SELECT 1")
