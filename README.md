# 자동 핫딜 탐지기 MVP

커뮤니티 핫딜 게시판을 모아 중복을 합치고, 과거 딜 가격을 기준선으로 삼아 "평소보다 싼 딜"을 골라 보여줍니다.

## 실행

```powershell
cd c:\Users\stkim\Documents\Codex\hotdeal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
python -m app
```

뽐뿌 RSS는 1분마다, 다른 커뮤니티는 3분마다 수집합니다. 대시보드는 SSE로 새 딜을 바로 붙입니다.

패밀리세일은 같은 사이트 `/family` 메뉴에서 봅니다. 딜링크·어미새를 30분마다 수집합니다. 수동 등록은 `/family/admin`이며 `ADMIN_PASSWORD` 환경변수가 필요합니다.

일마존(`/amazon-jp`)은 일본 아마존에서 표시 할인이 30% 이상인 상품을 모아 보여줍니다. 목록 사이트(mottoku)를 30분마다 긁으며, 구매 링크는 amazon.co.jp입니다. 선택: `AMAZON_JP_ASSOCIATE_TAG`.

## 뽐뿌 구매링크 (Railway 프록시)

뽐뿌 구매 URL은 상세 HTML에만 있습니다. Railway 데이터센터 IP는 상세가 403이라, 주거용/한국 출구 프록시를 `PPOMPPU_PROXY_URL`로 넣어야 합니다.

1. HTTP 또는 SOCKS5 프록시 URL을 준비합니다. 예: `http://user:pass@host:port`
2. Railway Variables에 `PPOMPPU_PROXY_URL`을 넣고 재시작합니다. 선택: `PPOMPPU_ENRICH_INTERVAL_MINUTES`(기본 5), `PPOMPPU_ENRICH_BATCH`(기본 12)
3. `GET /api/stats`에서 `ppomppu_proxy_configured`가 true인지, `last_ppomppu_mall_enrich.filled`가 0보다 큰지 확인합니다.
4. 홈 뽐뿌 카드 CTA가 **구매하기**(쇼핑몰)인지 확인합니다. 프록시가 막히면 `blocked`만 늘고 카드는 **상세보기**로 남습니다.

회사 PC에서는 로컬 collect를 켜지 않습니다. 형식은 [`.env.example`](.env.example)을 참고하세요.

## 뽐뿌 90일 백필

```powershell
python -m scripts.backfill_ppomppu
```

중단 후 다시 실행하면 마지막 페이지부터 이어갑니다.

## 수집 규칙

- 요청 간격 2초, 소스별 동시성 1
- Cloudflare 403이 나면 curl로 한 번 더 요청
- 클리앙·다모앙·어미새는 robots.txt 때문에 1페이지만
- 에펨코리아·알구몬은 수집하지 않음 (알구몬은 원본 커뮤니티 재수집)
