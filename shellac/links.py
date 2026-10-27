"""Which text in terminal output is a clickable link, and which links may be opened (FR-6).

GTK-free so the pattern and the safety rule are unit tested.
"""

from __future__ import annotations

from urllib.parse import urlparse

# What Ctrl+click may open. OSC 8 hyperlinks can name any scheme, so the allowed ones are
# listed: a program must not be able to launch an arbitrary protocol handler this way.
OPENABLE_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "file", "mailto"})

# Ends on a character that is not sentence punctuation, so "see https://x.org/a." and
# "(https://x.org)" do not swallow the final "." or ")".
URL_PATTERN = (
    r"(?:https?|ftps?|file)://[^\s<>\"'`]*[^\s<>\"'`.,;:!?)\]}]"
    r"|mailto:[^\s<>\"'`]*[^\s<>\"'`.,;:!?)\]}]"
)


def is_openable(uri: str) -> bool:
    return urlparse(uri).scheme.lower() in OPENABLE_SCHEMES
