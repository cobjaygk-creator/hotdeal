from app.engine.category import classify


def test_classify_food_and_game_seller():
    assert classify("카누 미니 마일드 120개입", "네이버") == "식품"
    assert classify("닌텐도 스위치2 본체", "네이버") == "게임"
    assert classify("귀무자 디럭스", "스팀") == "게임"
    assert classify("스파오 클리어런스 후드", "스파오") == "의류"
    assert classify("공기청정기 블루스카이", "G마켓") == "가전"
    assert classify("좋은느낌 입오버", "G마켓") == "생활"
    assert classify("알 수 없는 상품", "기타몰") == "기타"


def test_classify_live_misc_titles():
    assert classify("삼다수 2L 24개", "제주삼다수") == "식품"
    assert classify("몬스터 에너지 울트라 355ml 24캔", "롯데온") == "식품"
    assert classify("26년 수향미 특등급 당일도정 10kg", "오늘의집") == "식품"
    assert classify("1등급 한돈 찌개용 냉장 2kg", None) == "식품"
    assert classify("난각번호 1번 유정란 대란 40구", "11번가") == "식품"
    assert classify("오리온 초코파이 48P", "G마켓") == "식품"
    assert classify("지오다노 옥스포드 셔츠", "SSG") == "의류"
    assert classify("네파 남녀 캐쥬얼 코튼 팬츠", "롯데온") == "의류"
    assert classify("젤다의 전설 지혜의 투영", "쿠팡") == "게임"
    assert classify("JBL BAR 1000 MK2 사운드바", "G마켓") == "가전"
    assert classify("Lenovo IdeaPad Slim 3 15ABR8 / Win11", "하이마트몰") == "PC"
    assert classify("리얼실키 미용티슈 250매", "오늘의집") == "생활"
    assert classify("cas 카스 가정용 혈압측정기 혈압계 MD2540", "옥션") == "가전"


def test_classify_uses_source_category_only_as_fallback():
    # No keyword/heuristic hit on the product name -> the source's own badge
    # (quasarzone v2-badge / eomisae span.cate) rescues it from "기타".
    assert classify("무명브랜드 XZ-100", None, "PC/하드웨어") == "PC"
    assert classify("무명브랜드 XZ-100", None, "게임/SW") == "게임"
    assert classify("무명브랜드 XZ-100", None, "패션/의류") == "의류"
    assert classify("무명브랜드 XZ-100", None, "가전/TV") == "가전"
    assert classify("무명브랜드 XZ-100", None, "유아동") == "유아"
    # Ambiguous combined badge (quasarzone bundles life+food under one tag):
    # no reliable signal, stays 기타 rather than guessing.
    assert classify("무명브랜드 XZ-100", None, "생활/식품") == "기타"
    assert classify("무명브랜드 XZ-100", None, "기타") == "기타"
    assert classify("무명브랜드 XZ-100", None, None) == "기타"
    # A specific product-name keyword always wins over a coarser source badge.
    assert classify("삼겹살 1kg", None, "PC/하드웨어") == "식품"
    assert classify("젠하이저 헤드폰", None, "가전/TV") == "PC"


def test_classify_ham_products_not_misc():
    # fmkorea has no source-category badge, so this relied purely on keyword
    # coverage — "햄" itself was missing and it fell into "기타".
    assert classify("목우촌 주부9단 살코기햄 1kg 2개", "네이버") == "식품"
    assert classify("오뚜기 리챔 런천미트 340g 3캔", "쿠팡") == "식품"
    assert classify("아침에 베이컨 500g", None) == "식품"


def test_classify_seafood_not_misc():
    # ppomppu (also no source-category badge) — same gap pattern as ham:
    # common seafood nouns were simply absent from the keyword list.
    assert classify("홍대쭈꾸미 300g x 6팩", None) == "식품"
    assert classify("자숙 문어숙회 200g", None) == "식품"
    assert classify("코다리조림 밀키트", None) == "식품"
    assert classify("바지락 손질 1kg", None) == "식품"


def test_mine_keyword_candidates_finds_new_but_not_known_words():
    from app.engine.category import mine_keyword_candidates

    labeled = [
        ("가리비관자 냉동 300g", "식품"),
        ("관자 특대 자숙 500g", "식품"),
        ("관자 구이용 1kg", "식품"),
        ("레깅스 하이웨스트 요가복", "의류"),
        ("레깅스 9부 짐웨어", "의류"),
        ("짐웨어 크롭탑 세트", "의류"),
        # already-covered words must never surface as "new" candidates
        ("쭈꾸미볶음 밀키트 300g", "식품"),
        ("쭈꾸미볶음 매운맛 300g", "식품"),
    ]
    candidates = mine_keyword_candidates(labeled, min_count=2)
    assert ("관자", 2) in candidates.get("식품", [])
    assert ("짐웨어", 2) in candidates.get("의류", [])
    food_tokens = {tok for tok, _ in candidates.get("식품", [])}
    assert "쭈꾸미" not in food_tokens and "쭈꾸미볶음" not in food_tokens


def test_mine_keyword_candidates_needs_purity_and_frequency():
    from app.engine.category import mine_keyword_candidates

    # "온라인" shows up once per category -> not distinctive to either.
    labeled = [
        ("온라인 특가 삼겹살 1kg", "식품"),
        ("온라인 특가 레깅스", "의류"),
        ("바지락 손질 1kg", "식품"),  # appears only once -> below min_count
    ]
    candidates = mine_keyword_candidates(labeled, min_count=2)
    all_tokens = {tok for toks in candidates.values() for tok, _ in toks}
    assert "온라인" not in all_tokens
    assert "바지락" not in all_tokens


def test_classify_real_misc_audit_2026_09():
    """Pulled from production's actual 기타 bucket and reviewed by hand —
    each of these is unambiguously one category, just missing a keyword."""
    assert classify("하이디라오 마라샹궈 소스, 220g, 1개", None) == "식품"
    assert classify("미트엔조이 목전지 2kg 네이버멤버십", "네이버") == "식품"
    assert classify("호주산 냉장 치마살 1kg 구이용", None) == "식품"
    assert classify("소머리곰탕 600g x 6봉 임박", None) == "식품"
    assert classify("동원샘물 무라벨 2L 30병", "동원") == "식품"
    assert classify("(농할) 국내산 양파 대 사이즈 5kg", None) == "식품"
    assert classify("GNC 밀크씨슬 1300mg 120정 1통", None) == "식품"
    assert classify("탄산워싱소다 3kg x 2개+ 베이킹소다 3kg", None) == "생활"
    assert classify("닥터클로 곰팡이제거제 500ml 2개", None) == "생활"
    assert classify("올트라이탄 밀폐용기 350ml 2개+1.2L 1개", None) == "생활"
    assert classify("스케쳐스 여성 슬립온 아치핏 리파인 3종 택1", "스케쳐스") == "의류"
    assert classify("크록스 바야밴드 클로그", "크록스") == "의류"
    assert classify("주니어 챔스 풋살화 축구화", None) == "의류"
    assert classify("BYC 순면런닝 10개", "BYC") == "의류"
    assert classify("LG 나노셀 AI TV 75NANO90ABA", "LG") == "가전"
    assert classify("아이나비 QXD9900mini 64gb 메모리업+외장 GPS", None) == "PC"
    # Guard against the obvious false-positive traps these additions could
    # have opened up (luggage/car trunk vs underwear "트렁크"; treadmill vs
    # the "런닝" in a Korean-style undershirt name).
    assert classify("SUV 트렁크 정리함 수납박스", None) != "의류"
    assert classify("휴대용 접이식 런닝머신", None) != "의류"


def test_classify_former_misc_buckets():
    assert classify("처음 읽는 한국사1/삼국지5/그리스로마신화 15", "G마켓") == "도서"
    assert classify("아이폰 15 프로 자급제", "쿠팡") == "PC"
    assert classify("에어팟 프로 2세대", "애플") == "PC"
    assert classify("하기스 매직팬티 6단계", "쿠팡") == "유아"
    assert classify("무신사스탠다드 사피아노 신세틱 레더 벨트 30mm", "무신사") == "의류"
    assert classify("토트백 숄더백 여성", "지그재그") == "의류"
    assert classify("비타민C 1000 영양제", "네이버") == "식품"
    assert classify("강아지 사료 6kg", "쿠팡") == "생활"
    assert classify("알라딘 양장본 세트", "알라딘") == "도서"


def test_classify_mall_domain_rescues_cryptic_titles():
    # Cryptic title, no keyword, no source badge — the buy link is a
    # category-locked mall, used only as the last signal before 기타.
    assert classify("오늘만 이 가격", None, mall_url="https://www.kurly.com/goods/1") == "식품"
    assert classify("BLACK FRIDAY", None, mall_url="https://www.musinsa.com/app/goods/9") == "의류"
    assert classify("재입고 알림", None, mall_url="https://prod.danawa.com/info/?pcode=1") == "PC"
    assert classify("품절 임박", None, mall_url="https://www.yes24.com/Product/Goods/1") == "도서"
    # Generic marketplace -> no mall signal, falls through to 기타
    assert classify("오늘만 이 가격", None, mall_url="https://www.coupang.com/vp/products/1") == "기타"
    # A real product keyword still wins over the mall domain.
    assert classify("립톤 아이스티 분말 2개", None, mall_url="https://www.kurly.com/x") == "식품"


def test_classify_real_misc_audit_2026_09_11():
    """Second audit pass — 246 live 기타 deals pulled from production and
    read by hand (no LLM). ~105/246 recovered; the ones below are the
    representative, unambiguous cases plus the collisions the new keywords
    could have opened up."""
    assert classify("조립PC 완본체 3종 (7500X3D/7800X3D/5060Ti/5070)", "G마켓") == "PC"
    assert classify("LG 그램북 14U40V-GA5CK", "쿠팡") == "PC"
    assert classify("LG 그램 프로 AI 16 Ultra5 16ZD90TS-GX5PK", "쿠팡") == "PC"
    assert classify("시놀로지 DS225+ 나스용 스토리지 여러개", "롯데온") == "PC"
    assert classify("GIGABYTE Z890 AORUS ELITE WIFI7 ICE 피씨디렉트", None) == "PC"
    assert classify("국산콩 지담원 청국장 1kg", "남도장터") == "식품"
    assert classify("한성 모짜렐라 치즈볼 1kg", "네이버") == "식품"
    assert classify("프로즌 원팩 마라탕 보통맛 2팩", "G마켓") == "식품"
    assert classify("빙그레 더단백 드링크 8종 18팩 2박스 골라담기", "11번가") == "식품"
    assert classify("MINTIA 그레이프맛 50알 x 10개", "쿠팡") == "식품"
    assert classify("셰프초이스 제육 불고기 1.5kg", None) == "식품"
    assert classify("파워에이드 마운틴블라스트 900ml 12개", "쿠팡") == "식품"
    assert classify("완숙토마토 1kg", "롯데온") == "식품"
    assert classify("필라델피아 크림치즈 미니 16개", "NS몰") == "식품"
    assert classify("남성 나이키 페가수스 42 IB1873-702", "신세계") == "의류"
    assert classify("스케쳐스 여성 워크아웃 워커 3종 택1", "11번가") == "의류"
    assert classify("네파 공용 휘슬라이저 프로 고어텍스 트레킹화", "G마켓") == "의류"
    assert classify("에디션 프리미엄 사방스판 허리밴딩 바지", "G마켓") == "의류"
    assert classify("인사이 가정용 저소음 음식물 처리기 3L", "인사이") == "가전"
    assert classify("파나소닉 남성용 방수 바디트리머 ER-GY60", None) == "가전"
    assert classify("다이슨 에어스무스 스타일링 브러시", "네이버") == "가전"
    assert classify("삼성 하만카돈 오라스튜디오5 블루투스 스피커", "옥션") == "가전"
    assert classify("칸디다 항균 데일리 질경이 여성청결제 200ml x 2개", "캐시딜") == "생활"
    assert classify("레인 OK 에탄올워셔액 1.8L 6개", "G마켓") == "생활"
    assert classify("하림펫푸드 밥이보약 DOG 튼튼한관절 3.4kg", "토스") == "생활"
    assert classify("모던하우스 비스트로 웍 IH 24cm", "G마켓") == "생활"
    assert classify("레고 크리에이터 3-in-1 31387 전설의 해적선", "쿠팡") == "유아"
    assert classify("어린이학습만화 베스트 골라담기", "G마켓") == "도서"
    assert classify("스팀월렛 25000원권 + 삼성월렛", None) == "게임"
    assert classify("PS판 파이널 판타지 7 리버스", "PS스토어") == "게임"
    # False-positive guards for the new keywords/heuristics themselves:
    # "웍" matches wok cookware but must not fire on a company name ending
    # in "…웍스"; "바지" matches pants but must not fire on "바지락"(clam).
    assert classify("아크시스템웍스 데이브 더 다이버 CE 온라인샵 특전판", None) != "생활"
    assert classify("바지락 손질 1kg", None) == "식품"
    assert classify("바지락 칼국수 밀키트", None) == "식품"


def test_classify_expanded_source_badges():
    assert classify("무명 XZ", None, "먹거리") == "식품"
    assert classify("무명 XZ", None, "의류/잡화") == "의류"
    assert classify("무명 XZ", None, "육아") == "유아"
    assert classify("무명 XZ", None, "도서/음반") == "도서"
    assert classify("무명 XZ", None, "컴퓨터") == "PC"
    assert classify("무명 XZ", None, "화장품") == "생활"
    assert classify("무명 XZ", None, "상품권") == "기타"
