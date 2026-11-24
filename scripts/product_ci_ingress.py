"""Trusted public orchestration ingress. Never executes product files."""
import argparse
import hashlib
import io
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile


PRODUCT = "https://api.github.com/repos/jsdfhasuh/emo_master"
PRODUCT_ID = 1343796337
DISPATCHER_PATH = ".github/workflows/product-ci-dispatch.yml"
SHA = re.compile(r"[a-f0-9]{40}")
BLOB = re.compile(r"(?:[a-z0-9-]+\.)?(?:blob\.core\.windows\.net|actions\.githubusercontent\.com)")
MAX = 256 * 1024


class Invalid(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url, token=None):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
    if token:
        if not url.startswith(PRODUCT + "/"):
            raise Invalid("credential restricted to product API")
        headers["Authorization"] = "Bearer " + token
    try:
        with build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=20) as response:
            data = response.read(MAX + 1)
            if len(data) > MAX:
                raise Invalid("API response over limit")
            return response.status, data
    except HTTPError as error:
        try:
            if error.code != 302:
                raise Invalid(f"HTTP {error.code}") from None
            return error.code, error.headers.get("Location", "")
        finally:
            error.close()


def safe_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Invalid("duplicate JSON key")
            result[key] = value
        return result
    parsed = json.loads(data, object_pairs_hook=unique)
    if not isinstance(parsed, dict):
        raise Invalid("expected JSON object")
    return parsed


def require(value, message):
    if not value:
        raise Invalid(message)


def sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) and value != "0" * 40


def acquire(*, run_id, artifact_id, workflow_id, dispatcher_blob, worker_sha, token, transport=fetch):
    for number in (run_id, artifact_id, workflow_id):
        require(type(number) is int and number > 0, "invalid GitHub ID")
    require(sha(dispatcher_blob) and sha(worker_sha), "unpinned workflow")

    def api(path):
        status, body = transport(PRODUCT + path, token)
        require(status == 200, "unexpected GitHub API response")
        return safe_json(body)

    run = api(f"/actions/runs/{run_id}")
    require(run.get("id") == run_id and run.get("workflow_id") == workflow_id
            and run.get("path") == DISPATCHER_PATH and run.get("repository", {}).get("id") == PRODUCT_ID
            and run.get("head_repository", {}).get("id") == PRODUCT_ID, "unexpected dispatcher identity")
    attempt = run.get("run_attempt")
    require(type(attempt) is int and attempt > 0, "missing run generation")
    require(run.get("event") in ("push", "pull_request_target"), "unsupported origin event")
    run_head = run.get("head_sha")
    require(sha(run_head), "missing origin head")

    if run["event"] == "push":
        head = run_head
        require(run.get("head_branch") == "main", "unsupported push branch")
        ref = "refs/heads/main"
        tip = api("/git/ref/heads/main")
        require(tip.get("object", {}).get("sha") == head, "push superseded")
        execution = head
        base = number = None
        event = "push"
        trusted_definition_sha = head
    else:
        linked = run.get("pull_requests")
        require(isinstance(linked, list) and len(linked) == 1, "PR not bound to dispatcher run")
        number = linked[0].get("number")
        require(type(number) is int and number > 0, "bad PR association")
        pr = api(f"/pulls/{number}")
        base_head, pr_head = pr.get("base", {}), pr.get("head", {})
        execution, base = pr.get("merge_commit_sha"), base_head.get("sha")
        head = pr_head.get("sha")
        require(pr.get("number") == number and pr.get("state") == "open"
                and base_head.get("ref") == "main" and base_head.get("repo", {}).get("id") == PRODUCT_ID
                and pr_head.get("repo", {}).get("id") == PRODUCT_ID
                and sha(head) and run_head == base and pr.get("mergeable") is True
                and linked[0].get("head", {}).get("sha") == head
                and linked[0].get("base", {}).get("sha") == base and sha(base) and sha(execution),
                "PR stale, foreign, or not mergeable")
        merge = api(f"/git/ref/pull/{number}/merge")
        require(merge.get("object", {}).get("sha") == execution, "PR merge ref mismatch")
        commit = api(f"/git/commits/{execution}")
        require([p.get("sha") for p in commit.get("parents", [])] == [base, head], "merge parents mismatch")
        ref = "refs/heads/main"
        event = "pull_request"
        trusted_definition_sha = base

    definition = api(f"/contents/{DISPATCHER_PATH}?ref={trusted_definition_sha}")
    require(definition.get("path") == DISPATCHER_PATH and definition.get("type") == "file"
            and definition.get("sha") == dispatcher_blob, "unapproved product dispatcher definition")

    meta = api(f"/actions/artifacts/{artifact_id}")
    digest = meta.get("digest")
    require(meta.get("id") == artifact_id and meta.get("workflow_run", {}).get("id") == run_id
            and meta.get("expired") is False and meta.get("name") == f"ci-request-{run_id}-{attempt}"
            and isinstance(digest, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
            and type(meta.get("size_in_bytes")) is int and 0 < meta["size_in_bytes"] <= MAX,
            "unbound or unverifiable request artifact")
    status, redirect = transport(PRODUCT + f"/actions/artifacts/{artifact_id}/zip", token)
    require(status == 302 and isinstance(redirect, str), "artifact redirect absent")
    address = urlsplit(redirect)
    require(address.scheme == "https" and address.hostname and BLOB.fullmatch(address.hostname)
            and address.username is None and address.password is None and address.port in (None, 443),
            "unapproved artifact download host")
    status, data = transport(redirect, None)
    require(status == 200 and len(data) == meta["size_in_bytes"]
            and "sha256:" + hashlib.sha256(data).hexdigest() == digest, "artifact digest or size mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        require(len(members) == 1 and members[0].filename == "request.json"
                and 0 < members[0].file_size <= 16 * 1024, "unexpected request archive")
        with archive.open(members[0]) as stream:
            request = safe_json(stream.read(16 * 1024 + 1))
    expected = {
        "schema_version": 1, "source_repository_id": PRODUCT_ID, "request_id": f"{run_id}-{attempt}",
        "ci_workflow_sha": worker_sha, "source_head_sha": head, "check_sha": execution,
        "source_event_name": event, "source_ref": ref, "execution_sha": execution,
    }
    if number is not None:
        expected.update(source_pr_number=number, source_base_sha=base, source_merge_sha=execution)
    require(all(type(request.get(k)) is type(v) and request[k] == v for k, v in expected.items()),
            "request does not match fresh authoritative provenance")
    final_run = api(f"/actions/runs/{run_id}")
    require(final_run.get("run_attempt") == attempt and final_run.get("head_sha") == run_head, "dispatcher superseded")
    return {"execution_sha": execution, "source_event": event, "source_ref": ref,
            "request_id": expected["request_id"], "suites": '["ci"]'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=int, required=True)
    p.add_argument("--artifact", type=int, required=True)
    args = p.parse_args()
    try:
        token = os.environ["EMO_CI_TOKEN"]
        require(re.fullmatch(r"[A-Za-z0-9_]+", token), "invalid token configuration")
        outputs = acquire(run_id=args.run, artifact_id=args.artifact,
                          workflow_id=int(os.environ["PRODUCT_DISPATCHER_ID"]),
                          dispatcher_blob=os.environ["PRODUCT_DISPATCHER_BLOB"],
                          worker_sha=os.environ["APPROVED_WORKER_SHA"], token=token)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as stream:
            for key, value in outputs.items():
                stream.write(f"{key}={value}\n")
    except (ValueError, OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile):
        p.exit(1, "Product ingress rejected unverifiable input.\n")


if __name__ == "__main__":
    main()
