"""Designer-only diagnostics for the unchanged public, unauthenticated gate."""
import http.client
import json
import os
import re
import socket
import time
from urllib.error import HTTPError, URLError

from buildonly_windows_ingress import check, fetch, require

RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})
ATTEMPT_DELAY = (0, 1, 2)
TRANSIENT_TRANSPORT = (TimeoutError, ConnectionError, http.client.IncompleteRead)


def endpoint_label(path):
    for prefix, label in (
        ("/actions/runs/", "origin_run"),
        ("/actions/artifacts/", "origin_artifact"),
        ("/git/commits/", "execution_commit"),
        ("/git/ref/", "origin_ref"),
        ("/contents/.github/workflows/validate-windows-package.yml?", "origin_workflow"),
        ("/contents/", "origin_helper"),
    ):
        if path.startswith(prefix):
            return label
    return "product_repository" if path == "" else "other"


def transient(exc):
    if isinstance(exc, HTTPError):
        if exc.code not in RETRY_STATUS:
            return False
        # Never disregard a GitHub throttle that asks us to wait longer.
        headers = exc.headers or {}
        retry_after = headers.get("Retry-After", "0")
        return (retry_after.isascii() and retry_after.isdigit() and
                len(retry_after) <= 2 and int(retry_after) <= 1 and
                headers.get("X-RateLimit-Remaining") != "0")
    if isinstance(exc, URLError):
        exc = exc.reason
    return (isinstance(exc, TRANSIENT_TRANSPORT) or
            isinstance(exc, socket.gaierror) and exc.errno == socket.EAI_AGAIN)


def failure_kind(exc):
    if isinstance(exc, HTTPError):
        if exc.code in {403, 429}:
            return "http_throttled" if exc.code == 429 or (
                (exc.headers or {}).get("X-RateLimit-Remaining") == "0"
                or (exc.headers or {}).get("Retry-After")
            ) else "http_forbidden"
        if exc.code == 404:
            return "http_missing"
        if 300 <= exc.code < 400:
            return "http_redirect"
        return "http_transient" if exc.code in RETRY_STATUS else "http_error"
    if isinstance(exc, (URLError, OSError, http.client.HTTPException)):
        return "transport"
    return "invalid_body"


def main(reader=fetch, sleep=time.sleep):
    phase = "inputs"
    kind = "invalid"
    retries_left = 2

    def read(path):
        nonlocal phase, kind, retries_left
        phase = endpoint_label(path)
        kind = "invalid_body"
        for i, delay in enumerate(ATTEMPT_DELAY):
            if delay:
                sleep(delay)
            try:
                value = reader(path)
            except Exception as exc:
                kind = failure_kind(exc)
                retry = retries_left > 0 and i + 1 < len(ATTEMPT_DELAY) and transient(exc)
                if isinstance(exc, HTTPError):
                    exc.close()
                if retry:
                    retries_left -= 1
                    continue
                raise
            phase = "validation_after_" + phase
            kind = "mismatch"
            return value

    def unique(pairs):
        obj = {}
        for k, v in pairs:
            require(k not in obj)
            obj[k] = v
        return obj

    try:
        require(re.fullmatch(r"[0-9a-f]{64}", os.environ["WORKER_RECEIPT"]))
        raw = os.environ.get("WORKER_REQUEST", "").encode("ascii")
        require(0 < len(raw) <= 4096)
        require(os.environ.get("WORKER_ROUTE") == "windows-package")
        phase = "policy"
        with open("controller/.github/ci-cutover/windows-package-public-policy.json", "rb") as handle:
            policy = json.load(handle, object_pairs_hook=unique)
        require(policy.get("enabled") is True and policy.get("route") == "windows-package")
        phase = "request"
        message = json.loads(raw, object_pairs_hook=unique)
        kind = "mismatch"
        execution, release_tag = check(policy, message, read)
        phase, kind = "output", "io"
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="ascii") as out:
            out.write(f"execution_sha={execution}\nrelease_tag={release_tag}\n")
    except Exception:
        raise SystemExit(f"source_public_ingress=refused phase={phase} kind={kind}") from None


if __name__ == "__main__":
    main()
