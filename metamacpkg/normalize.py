"""Normalization helpers shared by matching, review, and tests."""
import re
from urllib.parse import urlparse

GENERIC_HOSTS = {
    "github.com",  # handled by full-path comparison instead
    "gitlab.com",
    "bitbucket.org",
    "sourceforge.net",
}


def norm(name):
    """Lowercase alphanumeric skeleton: gtk+3 -> gtk3, python@3.14 -> python314."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def split_host(url):
    try:
        host = urlparse((url or "").strip()).hostname or ""
    except ValueError:
        return "", ""
    host = host.lower().removeprefix("www.")
    return host, (urlparse((url or "").strip()).path or "")


def norm_homepage(url):
    """Canonical (host, path) pair, or (None, None) for empty/invalid URLs."""
    url = (url or "").strip().rstrip("/")
    if not url or " " in url:
        return None, None
    if "://" not in url:
        url = "https://" + url
    host, path = split_host(url)
    if not host or "." not in host:
        return None, None
    path = re.sub(r"/+", "/", path.rstrip("/").lower())
    if path in ("", "/"):
        path = ""
    # Drop common noise: index pages, trailing .html, /en/ prefixes.
    path = re.sub(r"/(index\.html?|default\.aspx?|home/?)$", "", path)
    return host, path


def homepage_key(url):
    """Matchable homepage identity.

    Generic forge hosts (github.com, ...) only match on the full path, so
    that two different projects on the same forge never compare equal.
    """
    host, path = norm_homepage(url)
    if not host:
        return None
    if host in GENERIC_HOSTS and not path:
        return None
    return (host, path)


def homepage_domain(url):
    host, _ = norm_homepage(url)
    return host


_WORD = re.compile(r"[a-z0-9]+")


def tokens(text, min_len=3):
    return {w for w in _WORD.findall((text or "").lower()) if len(w) >= min_len}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def desc_overlap(a, b):
    return jaccard(tokens(a), tokens(b))
