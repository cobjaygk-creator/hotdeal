import pytest

from app.db import connect
from app.mvno.moyo import parse_plans

# A minimal RSC-style fragment shaped like moyo's real theme-page payload:
# single-escaped JSON planMeta objects embedded in an HTML/JS string.
_FRAGMENT = (
    '<script>self.__next_f.push([1,"...[[\\"$\\",\\"li\\",\\"1\\",{\\"children\\":['
    '\\"$\\",\\"$L32\\",null,{\\"planMeta\\":{\\"id\\":100,\\"name\\":\\"이벤트 5GB\\",'
    '\\"operator\\":{\\"mno\\":\\"KT\\",\\"network\\":\\"LTE\\",\\"brandName\\":\\"테스트모바일\\"},'
    '\\"specifications\\":{\\"voice\\":-1,\\"isVoiceUnlimited\\":true,\\"message\\":-1,'
    '\\"isMessageUnlimited\\":true,\\"data\\":{\\"isUnlimited\\":false,\\"monthly\\":5,\\"daily\\":0,\\"qos\\":0}},'
    '\\"pricing\\":{\\"originalFee\\":19900,\\"discountFee\\":9900,\\"discountPeriod\\":6},'
    '\\"statistics\\":{\\"rating\\":4.5,\\"signup1MonthCount\\":1200},'
    '\\"benefits\\":{\\"giftGroupList\\":[{\\"title\\":\\"네이버페이 1만원 페이백 (6개월)\\"}]}}}]},'
    # a plan with NO promo — must be dropped
    '{\\"planMeta\\":{\\"id\\":101,\\"name\\":\\"노이벤트 3GB\\",'
    '\\"operator\\":{\\"mno\\":\\"SKT\\",\\"network\\":\\"LTE\\",\\"brandName\\":\\"테스트모바일2\\"},'
    '\\"specifications\\":{\\"voice\\":100,\\"isVoiceUnlimited\\":false,\\"message\\":-1,'
    '\\"isMessageUnlimited\\":true,\\"data\\":{\\"isUnlimited\\":false,\\"monthly\\":3,\\"daily\\":0,\\"qos\\":0}},'
    '\\"pricing\\":{\\"originalFee\\":8900,\\"discountFee\\":8900,\\"discountPeriod\\":null},'
    '\\"statistics\\":{\\"rating\\":4.0,\\"signup1MonthCount\\":50},'
    '\\"benefits\\":{\\"giftGroupList\\":[]}}}]\\n"])</script>'
)


def test_parse_plans_keeps_only_promo_plans():
    rows = parse_plans(_FRAGMENT)
    assert [r["plan_id"] for r in rows] == [100]
    r = rows[0]
    assert r["name"] == "이벤트 5GB"
    assert r["mno"] == "KT" and r["network"] == "LTE" and r["mvno"] == "테스트모바일"
    assert r["data_gb"] == 5 and r["data_unlimited"] == 0
    assert r["voice_unlimited"] == 1 and r["sms_unlimited"] == 1
    assert r["original_fee"] == 19900 and r["discount_fee"] == 9900
    assert r["discount_months"] == 6
    assert r["promo"] == "네이버페이 1만원 페이백 (6개월)"
    assert r["plan_url"] == "https://www.moyoplan.com/plans/100"
    assert r["rating"] == 4.5 and r["signup_count"] == 1200


def test_parse_plans_empty_input():
    assert parse_plans("") == []
    assert parse_plans("<html>no plans here</html>") == []


@pytest.mark.asyncio
async def test_collect_mvno_plans_upserts_and_deactivates(tmp_path, monkeypatch):
    from app.mvno.pipeline import collect_mvno_plans

    async def fake_fetch(client, theme_urls=None):
        return [
            {
                "plan_id": 1,
                "name": "A",
                "mvno": "X",
                "mno": "KT",
                "network": "LTE",
                "data_gb": 5,
                "data_unlimited": 0,
                "data_daily_gb": None,
                "qos_kbps": None,
                "voice_min": None,
                "voice_unlimited": 1,
                "sms_unlimited": 1,
                "original_fee": 10000,
                "discount_fee": 5000,
                "discount_months": 3,
                "promo": "5천원 페이백",
                "promo_all": "[]",
                "rating": 4.5,
                "signup_count": 10,
                "plan_url": "https://www.moyoplan.com/plans/1",
                "brand_image": None,
            }
        ]

    monkeypatch.setattr("app.mvno.pipeline.fetch_plans", fake_fetch)
    conn = await connect(tmp_path / "mvno.db")
    try:
        out = await collect_mvno_plans(conn, object())
        assert out["fetched"] == 1
        cur = await conn.execute("SELECT * FROM mvno_plans WHERE plan_id=1")
        row = dict(await cur.fetchone())
        assert row["active"] == 1 and row["promo"] == "5천원 페이백"

        # second run drops plan 1 -> it must be deactivated, not deleted
        async def fake_fetch_empty(client, theme_urls=None):
            return []

        monkeypatch.setattr("app.mvno.pipeline.fetch_plans", fake_fetch_empty)
        await collect_mvno_plans(conn, object())
        cur = await conn.execute("SELECT active FROM mvno_plans WHERE plan_id=1")
        assert (await cur.fetchone())["active"] == 1  # no ids seen -> filter skipped
    finally:
        await conn.close()
