"""Parse a short-lived download capability AFTER authenticating the sealed envelope."""
import json
import re
from urllib.parse import urlsplit

IDS = ("origin_repository", "origin_run", "origin_attempt",
       "worker_repository", "worker_run", "worker_attempt")
KEYS = {*IDS, "source_sha", "worker_sha", "archive_sha256",
        "issued_at", "expires_at", "url"}


def parse_capability(payload, expected, now, allowed_hosts):
    def invalid():
        # Deliberately never embed a bearer URL or attacker-controlled value.
        return ValueError("invalid source capability")

    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise invalid()
        return result

    try:
        if type(payload) is not bytes or not 0 < len(payload) <= 8192 or type(now) is not int:
            raise invalid()
        manifest = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
        if not isinstance(manifest, dict) or manifest.keys() != KEYS:
            raise invalid()
        for key in IDS:
            if type(manifest[key]) is not int or manifest[key] <= 0 or manifest[key] != expected[key]:
                raise invalid()
        for key, length in (("source_sha", 40), ("worker_sha", 40), ("archive_sha256", 64)):
            if not re.fullmatch("[a-f0-9]{%d}" % length, manifest[key]):
                raise invalid()
            if key != "archive_sha256" and manifest[key] != expected[key]:
                raise invalid()
        start, end = manifest["issued_at"], manifest["expires_at"]
        if type(start) is not int or type(end) is not int or not (start <= now < end <= start + 300):
            raise invalid()
        url = manifest.pop("url")
        if type(url) is not str or not url.isascii() or any(ord(c) <= 32 or c == chr(127) or c == chr(92) for c in url):
            raise invalid()
        u = urlsplit(url)
        if (u.scheme != "https" or u.hostname not in allowed_hosts or u.netloc != u.hostname or
                u.fragment or not u.query or not u.path.startswith("/") or u.path == "/"):
            raise invalid()
        # Return URL separately to keep identity manifest safe for display; never log the tuple.
        return manifest, url
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        raise invalid() from None
