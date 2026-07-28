"""Shared "open a raw post" logic used by any screen listing un-curated posts."""

from __future__ import annotations

from textual.screen import Screen

from reddit_reader.service import ReaderService


def open_post(screen: Screen[None], service: ReaderService, post_id: str) -> None:
    """Jump to the story containing this post, or curate its detected series."""
    for story in service.stories.all_stories():
        if post_id in service.stories.part_post_ids(story.id):
            from reddit_reader.tui.screens.story_detail import StoryDetailScreen

            screen.app.push_screen(StoryDetailScreen(service, story.id))
            return

    meta = service.posts.get_meta(post_id)
    if meta is None:
        return

    from reddit_reader.detection import group_posts
    from reddit_reader.tui.screens.curation import CurationScreen

    author_posts = service.posts.by_author(meta.author)
    candidates = [
        match
        for match in group_posts(
            author_posts,
            service.settings.subreddits,
            window_hours=service.settings.dedupe_window_hours,
        )
        if post_id in match.post_ids
    ]
    if candidates:
        screen.app.push_screen(CurationScreen(service, candidates))
