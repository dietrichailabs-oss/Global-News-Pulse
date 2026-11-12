"""Shared bounded source capacity; does not grant collection permission."""
MAX_TOTAL_SOURCES = 512
# A complete custom-feed list can exceed the ordinary setting budget.
# Only that specific setting receives this larger, still bounded allowance.
MAX_USER_FEED_SETTING_BYTES = 2_000_000
