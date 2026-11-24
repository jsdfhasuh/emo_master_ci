"""Trusted credential proof and detached-checkout gate for hosted source jobs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PRODUCT = "jsdfhasuh/emo_master"
PRODUCT_ID = 1343796337
ORIGIN = "https://github.com/" + PRODUCT
API = "https://api.github.com"
MAX_REPLY = 2 * 1024 * 1024


class SourceAuthError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    # Authorization must never follow a redirect.
    def redirect_request(self, *_args):
        return None


def source_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{40}", value) or value == "0" * 40:
        raise SourceAuthError("exact product commit required")
    return value


def transport(request):
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            return response.status, response.read(MAX_REPLY + 1)
    except HTTPError as error:
        error.close()
        raise SourceAuthError(f"source authentication rejected (HTTP {error.code})") from None
    except (URLError, OSError):
        raise SourceAuthError("source authentication unavailable") from None


def verify_authenticated_source(sha, token, read=transport, *, require_public=False):
    expected = source_sha(sha)
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_]+", token):
        raise SourceAuthError("source transport requires the explicit repository credential")

    def lookup(path):
        status, body = read(Request(API + path, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        }))
        if status != 200 or len(body) > MAX_REPLY:
            raise SourceAuthError("source authentication response was not accepted")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise SourceAuthError("invalid authenticated response")
        return result

    # Unlike the fixed product's current Public read endpoints, /user does
    # not accept an anonymous request. Never print any returned account data.
    user = lookup("/user")
    if type(user.get("id")) is not int or user["id"] <= 0:
        raise SourceAuthError("source credential lacks a verified GitHub identity")
    repo = lookup("/repos/" + PRODUCT)
    if repo.get("id") != PRODUCT_ID or repo.get("full_name") != PRODUCT:
        raise SourceAuthError("wrong product repository")
    if require_public and (repo.get("private") is not False or repo.get("visibility") != "public"):
        raise SourceAuthError("this checkout-only probe is restricted to the still-Public product")
    commit = lookup("/repos/" + PRODUCT + "/git/commits/" + expected)
    if commit.get("sha") != expected:
        raise SourceAuthError("authenticated API returned the wrong commit")


def verify_checkout(directory, sha, *, env=None):
    expected = source_sha(sha)
    env = os.environ if env is None else env
    if any(env.get(key) for key in ("EMO_CI_TOKEN", "INPUT_TOKEN", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")):
        raise SourceAuthError("unexpected credential-bearing checkout environment")

    def git(*args):
        return subprocess.run(["git", "-C", str(directory), *args], capture_output=True,
                              stdin=subprocess.DEVNULL, text=True)

    head = git("rev-parse", "--verify", "HEAD")
    branch = git("symbolic-ref", "-q", "HEAD")
    origin = git("config", "--local", "--get-all", "remote.origin.url")
    secret_config = git("config", "--local", "--name-only", "--get-regexp",
                        r"^(http\..*extraheader|credential\.|include\.|includeif\.)")
    if (head.returncode or head.stdout.strip() != expected or branch.returncode != 1 or origin.returncode
            or origin.stdout.splitlines() not in ([ORIGIN], [ORIGIN + ".git"])
            or secret_config.returncode != 1 or secret_config.stdout or secret_config.stderr):
        raise SourceAuthError("checkout identity or credential cleanup not verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("authenticate", "verify-checkout"))
    parser.add_argument("--require-public", action="store_true")
    parser.add_argument("--directory", type=Path, default=Path("product"))
    args = parser.parse_args()
    try:
        expected = os.environ["PRODUCT_EXECUTION_SHA"]
        if args.stage == "authenticate":
            verify_authenticated_source(expected, os.environ.get("EMO_CI_TOKEN"), require_public=args.require_public)
            print("Existing credential accepted by GitHub; exact product commit read.")
        else:
            verify_checkout(args.directory, expected)
            print("Exact product checkout verified; no credential binding found in checkout config.")
    except (KeyError, OSError, SourceAuthError, ValueError):
        print("Product source authentication or checkout verification did not pass.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
