from app.pipeline import _source_category


def test_source_category_from_dict_raw_json():
    """post_to_row() puts RawPost.extra straight in as a dict (fresh fetch)."""
    row = {"raw_json": {"source_category": "PC/하드웨어", "thumbnail_url": "x"}}
    assert _source_category(row) == "PC/하드웨어"


def test_source_category_from_json_string_raw_json():
    """Once round-tripped through the posts table, raw_json is JSON text."""
    row = {"raw_json": '{"source_category": "게임/SW"}'}
    assert _source_category(row) == "게임/SW"


def test_source_category_missing_or_malformed():
    assert _source_category({}) is None
    assert _source_category({"raw_json": None}) is None
    assert _source_category({"raw_json": "not json"}) is None
    assert _source_category({"raw_json": {}}) is None
    assert _source_category({"raw_json": {"source_category": ""}}) is None
    assert _source_category({"raw_json": {"source_category": "  "}}) is None
