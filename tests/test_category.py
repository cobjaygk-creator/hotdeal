from app.engine.category import classify


def test_classify_food_and_game_seller():
    assert classify("카누 미니 마일드 120개입", "네이버") == "식품"
    assert classify("닌텐도 스위치2 본체", "네이버") == "게임"
    assert classify("귀무자 디럭스", "스팀") == "게임"
    assert classify("스파오 클리어런스 후드", "스파오") == "의류"
    assert classify("공기청정기 블루스카이", "G마켓") == "가전"
    assert classify("좋은느낌 입오버", "G마켓") == "생활"
    assert classify("알 수 없는 상품", "기타몰") == "기타"
