import pytest

from app.http_client import FetchResult
from app.sources import detail


class Client:
    async def get(self, url, **kwargs):
        html = "<html><head><title>펨코 상품</title></head><body><p>본문</p></body></html>"
        return FetchResult(url, 200, html, html.encode())


@pytest.mark.asyncio
async def test_fmkorea_partial_proxy_html_continues_to_browser(monkeypatch):
    async def browser_html(url, **kwargs):
        return """
        <div id='bd_capture'><div class='rd_hd'><table class='hotdeal_table'>
          <tr><th>링크</th><td><a href='https://shop.example/item/1'>구매</a></td></tr>
        </table></div><div class='rd_body'><article><p>실제 본문</p></article></div></div>
        """

    async def canonicalize(client, url):
        return url

    monkeypatch.setattr(detail, "FMKOREA_BROWSER_DETAIL", True)
    monkeypatch.setattr("app.sources.fm_browser.fetch_html", browser_html)
    monkeypatch.setattr(detail, "canonicalize_mall_url", canonicalize)

    result = await detail.enrich_post(Client(), "fmkorea", "https://www.fmkorea.com/1")
    assert result.mall_url == "https://shop.example/item/1"
