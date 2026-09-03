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
