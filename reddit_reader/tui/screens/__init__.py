# Fixed width for the long free-text title/story column in list tables, so an
# extremely long title can't balloon its column and push Author/Subreddit
# off screen.
TITLE_COLUMN_WIDTH = 60

# Keys a screen can opt into via a `PAGING_KEYS` class attribute to exempt
# them from the app-wide keypress DEBUG log (see `RedditReaderApp.on_key`) —
# scrolling a long body a page at a time is noisy and not diagnostically
# useful the way a one-off action keypress is.
PAGING_KEYS = frozenset({"space", "b"})
