from app.engine.auth import merge_bookmark_ids, oauth_cookie_ok, read_user_id, sign_user_id


def test_session_cookie_roundtrip():
    token = sign_user_id(42)
    assert read_user_id(token) == 42
    assert read_user_id(None) is None
    assert read_user_id("42.deadbeef") is None
    assert read_user_id("nope") is None


def test_merge_bookmark_ids_unique_and_cap():
    assert merge_bookmark_ids([3, 1, "1", 0, "x"], [2, 3]) == [3, 1, 2]
    huge = list(range(1, 250))
    assert len(merge_bookmark_ids(huge)) == 200


def test_oauth_state_cookie():
    assert oauth_cookie_ok("kakao:abc", "kakao", "abc")
    assert not oauth_cookie_ok("kakao:abc", "kakao", "xyz")
    assert not oauth_cookie_ok("google:abc", "kakao", "abc")
    assert not oauth_cookie_ok(None, "kakao", "abc")
