from reddit_reader.navlinks import extract_all_post_ids, extract_post_id, parse_nav_links

NAV_BLOCK = """
Some story text here.

[First](https://www.reddit.com/r/HFY/comments/aaa111/road_part_1/) |
[Prev](https://www.reddit.com/r/HFY/comments/bbb222/road_part_11/) |
[Next](https://www.reddit.com/r/HFY/comments/ccc333/road_part_13/)
"""


def test_extract_post_id_from_full_url() -> None:
    url = "https://www.reddit.com/r/HFY/comments/abc123/some_title/"
    assert extract_post_id(url) == "abc123"


def test_extract_post_id_from_short_url() -> None:
    assert extract_post_id("https://redd.it/abc123") == "abc123"


def test_extract_post_id_returns_none_for_unrelated_url() -> None:
    assert extract_post_id("https://patreon.com/bluefishcake") is None


def test_parses_all_three_links() -> None:
    links = parse_nav_links(NAV_BLOCK)
    assert links.first == "aaa111"
    assert links.previous == "bbb222"
    assert links.next == "ccc333"


def test_previous_spelled_out_is_recognized() -> None:
    text = "[Previous](https://www.reddit.com/r/HFY/comments/bbb222/x/)"
    assert parse_nav_links(text).previous == "bbb222"


def test_missing_links_are_none() -> None:
    links = parse_nav_links("Just a story with no navigation.")
    assert links.first is None
    assert links.previous is None
    assert links.next is None


def test_link_labels_are_case_insensitive() -> None:
    text = "[NEXT](https://www.reddit.com/r/HFY/comments/ccc333/x/)"
    assert parse_nav_links(text).next == "ccc333"


def test_non_reddit_link_is_ignored() -> None:
    text = "[Next](https://royalroad.com/fiction/1)"
    assert parse_nav_links(text).next is None


def test_extract_all_post_ids_finds_an_unlabeled_inline_mention() -> None:
    text = "Catch up here: https://www.reddit.com/r/HFY/comments/aaa111/x/ if you missed it."
    assert extract_all_post_ids(text) == ["aaa111"]


def test_extract_all_post_ids_covers_markdown_and_short_links() -> None:
    text = (
        "[First](https://www.reddit.com/r/HFY/comments/aaa111/x/) "
        "and also https://redd.it/bbb222 mentioned inline."
    )
    assert extract_all_post_ids(text) == ["aaa111", "bbb222"]


def test_extract_all_post_ids_deduplicates_and_preserves_order() -> None:
    text = (
        "https://redd.it/bbb222 ... "
        "https://www.reddit.com/r/HFY/comments/aaa111/x/ ... "
        "https://redd.it/bbb222"
    )
    assert extract_all_post_ids(text) == ["bbb222", "aaa111"]


def test_extract_all_post_ids_returns_empty_list_for_plain_text() -> None:
    assert extract_all_post_ids("Just a story with no links.") == []
