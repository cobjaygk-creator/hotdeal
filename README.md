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
