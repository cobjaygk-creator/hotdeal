from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.sources import brightdata as bd
from app.sources.fmkorea import FmkoreaSource


@pytest.fixture
def budget(monkeypatch, tmp_path):
    monkeypatch.setattr(bd, 'DATA_DIR', tmp_path)
    monkeypatch.setenv('BRIGHTDATA_ENABLED', '1')
    monkeypatch.setenv('BRIGHTDATA_API_KEY', 'test-secret')
    monkeypatch.setenv('BRIGHTDATA_ZONE', 'test-zone')
    monkeypatch.setenv('BRIGHTDATA_MONTHLY_LIMIT', '2')
    monkeypatch.setenv('BRIGHTDATA_INTERVAL_MINUTES', '60')


def test_durable_cooldown_and_global_limit(budget):
    assert bd.reserve('arca')
    assert not bd.reserve('arca')
    assert bd.reserve('fmkorea')
    with pytest.raises(RuntimeError, match='monthly'):
        bd.reserve('coolenjoy')


def test_concurrent_reservations_do_not_overspend(budget, monkeypatch):
    monkeypatch.setenv('BRIGHTDATA_MONTHLY_LIMIT', '1')
    def reserve(source):
        try:
            return bd.reserve(source)
        except RuntimeError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, ['arca', 'quasarzone', 'fmkorea', 'coolenjoy'])) == 1


@pytest.mark.asyncio
async def test_fmkorea_options_and_no_proxy_fallback(budget, monkeypatch):
    monkeypatch.setenv('BRIGHTDATA_MONTHLY_LIMIT', '3')
    calls = []
    async def post(self, url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, text='<html>empty</html>')
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    with pytest.raises(RuntimeError, match='no parsed posts'):
        await FmkoreaSource().fetch_latest(None)
    assert calls[0]['json']['country'] == 'kr'
    assert calls[0]['json']['render'] == 'true'
    # FMKorea gets one bounded retry, and the next scheduler tick is held.
    assert await FmkoreaSource().fetch_latest(None) == []
    assert len(calls) == 2
    assert await FmkoreaSource().fetch_latest(None) == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_details_do_not_use_old_proxy(budget):
    from app.sources.detail import enrich_post
    result = await enrich_post(None, 'fmkorea', 'https://www.fmkorea.com/123')
    assert result.body_html is None


@pytest.mark.asyncio
async def test_provider_errors_do_not_expose_secret(budget, monkeypatch):
    async def post(self, url, **kwargs):
        return httpx.Response(401, text='test-secret')
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    with pytest.raises(RuntimeError, match='HTTP 401') as exc:
        await bd.fetch_posts('https://arca.live/b/hotdeal', lambda html: [])
    assert 'test-secret' not in str(exc.value)
