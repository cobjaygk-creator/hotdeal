from app.engine.category import classify


def test_classify_food_and_game_seller():
    assert classify("카누 미니 마일드 120개입", "네이버") == "식품"
    assert classify("닌텐도 스위치2 본체", "네이버") == "게임"
    assert classify("귀무자 디럭스", "스팀") == "게임"
    assert classify("스파오 클리어런스 후드", "스파오") == "의류"
    assert classify("공기청정기 블루스카이", "G마켓") == "가전"
    assert classify("좋은느낌 입오버", "G마켓") == "생활"
    assert classify("알 수 없는 상품", "기타몰") == "기타"


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
