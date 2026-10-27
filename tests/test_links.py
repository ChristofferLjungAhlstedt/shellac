import re

import pytest

from shellac.links import URL_PATTERN, is_openable

FIND = re.compile(URL_PATTERN)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see https://example.org/a?b=1, ok", "https://example.org/a?b=1"),
        ("(https://example.org/path)", "https://example.org/path"),
        ("go to http://localhost:8080.", "http://localhost:8080"),
        ("file:///home/me/notes.txt", "file:///home/me/notes.txt"),
        ("write mailto:me@example.org!", "mailto:me@example.org"),
        ('"https://example.org/x"', "https://example.org/x"),
        ("https://en.wikipedia.org/wiki/Foo_(bar)", "https://en.wikipedia.org/wiki/Foo_(bar"),
    ],
)
def test_url_extraction(text, expected):
    match = FIND.search(text)
    assert match is not None and match.group(0) == expected


def test_plain_text_has_no_links():
    assert FIND.search("nothing to see: foo/bar.txt 10:20") is None


def test_only_safe_schemes_open():
    for uri in ("https://a.b", "HTTP://a.b", "file:///x", "mailto:a@b.c", "ftp://h/f"):
        assert is_openable(uri), uri
    for uri in ("javascript:alert(1)", "ssh://host", "x-scheme://thing", "data:text/html,x", ""):
        assert not is_openable(uri), uri
