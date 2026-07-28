from datetime import UTC, datetime, timedelta
from pathlib import Path

from reddit_reader.export import (
    export_filename,
    part_heading,
    render_links,
    render_markdown,
    write_export,
)
from reddit_reader.models import PostMeta, Story
from reddit_reader.ordering import group_segments, resolve_order
from reddit_reader.titles import parse_title

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def post(post_id: str, title: str, *, days: int = 0, available: bool = True) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title=title,
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=BASE + timedelta(days=days),
        score=1,
        available=available,
    )


def a_story(**kwargs: object) -> Story:
    base: dict[str, object] = {
        "id": 1,
        "series_key": "bluefishcake:the long road",
        "title": "The Long Road",
        "author": "BlueFishcake",
    }
    base.update(kwargs)
    return Story(**base)  # type: ignore[arg-type]


def groups_for(*posts: PostMeta) -> list[list[object]]:
    ordered = resolve_order([(p, parse_title(p.title)) for p in posts])
    return group_segments(ordered)  # type: ignore[return-value]


def test_export_filename_includes_author_and_title() -> None:
    assert export_filename(a_story()) == "BlueFishcake-The-Long-Road.md"


def test_export_filename_includes_volume_when_present() -> None:
    assert export_filename(a_story(volume=2)) == "BlueFishcake-The-Long-Road-vol2.md"


def test_export_filename_sanitizes_unsafe_characters() -> None:
    name = export_filename(a_story(title="Road/Home: A Tale?"))
    assert "/" not in name
    assert ":" not in name
    assert "?" not in name


def test_numbered_part_heading_uses_the_number() -> None:
    heading = part_heading(groups_for(post("a", "Road - Part 12"))[0])  # type: ignore[arg-type]
    assert heading.startswith("## Part 12")


def test_numbered_part_heading_avoids_scientific_notation_for_round_numbers() -> None:
    heading = part_heading(groups_for(post("a", "Road - Part 100"))[0])  # type: ignore[arg-type]
    assert heading.startswith("## Part 100")
    assert "E+" not in heading

    heading = part_heading(groups_for(post("a", "Road - Part 10"))[0])  # type: ignore[arg-type]
    assert heading.startswith("## Part 10")
    assert "E+" not in heading


def test_numbered_part_heading_preserves_fractional_part_numbers() -> None:
    heading = part_heading(groups_for(post("a", "Road - Part 12.5"))[0])  # type: ignore[arg-type]
    assert heading.startswith("## Part 12.5")


def test_named_part_heading_uses_the_label_not_part_none() -> None:
    heading = part_heading(groups_for(post("i", "Road - Interlude"))[0])  # type: ignore[arg-type]
    assert "Interlude" in heading
    assert "None" not in heading


def test_segmented_part_gets_one_heading_citing_both_sources() -> None:
    groups = groups_for(
        post("a", "Road - Chapter 12 (1/2)", days=0),
        post("b", "Road - Chapter 12 (2/2)", days=1),
    )
    assert len(groups) == 1
    heading = part_heading(groups[0])  # type: ignore[arg-type]
    assert heading.count("https://reddit.com") == 2


def test_markdown_has_story_title_as_h1() -> None:
    md = render_markdown(a_story(), groups_for(post("a", "Road - Part 1")), {"a": "Text."}, [])  # type: ignore[arg-type]
    assert md.startswith("# The Long Road")


def test_markdown_includes_body_text_in_order() -> None:
    groups = groups_for(post("b", "Road - Part 2", days=1), post("a", "Road - Part 1"))
    md = render_markdown(a_story(), groups, {"a": "First part.", "b": "Second part."}, [])  # type: ignore[arg-type]
    assert md.index("First part.") < md.index("Second part.")


def test_markdown_concatenates_segments_under_one_heading() -> None:
    groups = groups_for(
        post("a", "Road - Chapter 12 (1/2)", days=0),
        post("b", "Road - Chapter 12 (2/2)", days=1),
    )
    md = render_markdown(a_story(), groups, {"a": "Front half.", "b": "Back half."}, [])  # type: ignore[arg-type]
    assert md.count("## Part 12") == 1
    assert "Front half." in md and "Back half." in md


def test_markdown_applies_cleaning() -> None:
    body = "Story text.\n\nSupport me on [Patreon](https://patreon.com/x)!"
    md = render_markdown(a_story(), groups_for(post("a", "Road - Part 1")), {"a": body}, [])  # type: ignore[arg-type]
    assert "patreon" not in md.lower()
    assert "Story text." in md


def test_links_export_lists_permalinks_in_order() -> None:
    groups = groups_for(post("b", "Road - Part 2", days=1), post("a", "Road - Part 1"))
    links = render_links(a_story(), groups)  # type: ignore[arg-type]
    assert links.index("/comments/a/") < links.index("/comments/b/")


def test_links_export_flags_dead_permalinks() -> None:
    groups = groups_for(post("a", "Road - Part 1", available=False))
    assert "unavailable" in render_links(a_story(), groups).lower()  # type: ignore[arg-type]


def test_links_export_cites_alternate_mirrors() -> None:
    """Item 9: a collapsed duplicate/mirror must still be citeable from the
    links export, not silently discarded."""
    groups = groups_for(post("a", "Road - Part 1"))
    mirror = post("m1", "Road - Part 1 [mirror]")
    links = render_links(a_story(), groups, {"a": [mirror]})  # type: ignore[arg-type]
    assert "/comments/m1/" in links


def test_write_export_creates_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.md"
    write_export(target, "# Hello")
    assert target.read_text() == "# Hello"


def test_write_export_overwrites_in_place(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    write_export(target, "old")
    write_export(target, "new")
    assert target.read_text() == "new"
