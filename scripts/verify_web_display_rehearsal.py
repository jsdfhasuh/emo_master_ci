"""Bind one immutable per-route rehearsal manifest to the broker's exact receipt."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener


class Refused(ValueError):
    pass


def require(value):
    if not value:
        raise Refused("rehearsal receipt refused")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def parse(raw):
    def checked(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=checked)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):
        return None


def public_get(path):
    request=Request("https://api.github.com/repos/jsdfhasuh/emo_master_ci"+path,headers={
        "Accept":"application/vnd.github+json", "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"dot-first-batch-rehearsal"})
    with build_opener(NoRedirect()).open(request,timeout=15) as response:
        raw=response.read(1048577)
    require(len(raw)<=1048576)
    return parse(raw)


def guard(manifest, env, get=public_get):
    route = env["WORKER_ROUTE"]
    require(route in {"web", "display"} and manifest["route"] == route)
    require(manifest["schema"] == 1 and manifest["scope"] == "nonrequired-rehearsal")
    require(env["GITHUB_REPOSITORY_ID"] == "1468905732" and env["GITHUB_RUN_ATTEMPT"] == "1"
            and env["GITHUB_EVENT_NAME"] == "workflow_dispatch")
    actor = int(env["REHEARSAL_ACTOR_ID"])
    require(actor == 49879362
            and env["GITHUB_ACTOR_ID"] == str(actor))
    path = f".github/workflows/dispatch-{route}-candidate.yml"
    tag = manifest["tag"]
    require(re.fullmatch(r"ci-worker-[A-Za-z0-9._-]{1,96}", tag))
    require(env["GITHUB_REF"] == f"refs/tags/{tag}"
            and env["GITHUB_WORKFLOW_REF"] == f"jsdfhasuh/emo_master_ci/{path}@refs/tags/{tag}")
    commit = env["GITHUB_WORKFLOW_SHA"]
    require(re.fullmatch(r"[0-9a-f]{40}", commit) and commit != "0" * 40
            and commit == env["GITHUB_SHA"])
    rid=int(env["GITHUB_RUN_ID"])
    require(rid>0)
    run=get(f"/actions/runs/{rid}")
    workflow=run.get("workflow_id")
    require(type(workflow) is int and workflow>0 and run.get("id")==rid and run.get("path")==path
            and run.get("repository",{}).get("id")==1468905732 and run.get("head_repository",{}).get("id")==1468905732
            and run.get("head_sha")==commit and run.get("event")=="workflow_dispatch" and run.get("head_branch")==tag
            and run.get("actor",{}).get("id")==actor and run.get("triggering_actor",{}).get("id")==actor and run.get("run_attempt")==1)
    ref=get("/git/ref/tags/"+tag)
    require(ref.get("ref")==f"refs/tags/{tag}" and ref.get("object",{}).get("type")=="commit"
            and ref["object"].get("sha")==commit)
    wire = env["WORKER_REQUEST"]
    require(0 < len(wire) <= 4096 and wire.isascii() and wire == canonical(parse(wire))
            and wire == canonical(manifest["request"]) and manifest["request"]["route"] == route)
    receipt = sha256(json.dumps([workflow,path,tag,commit,actor,wire],
                               ensure_ascii=True,separators=(",",":")).encode("ascii")).hexdigest()
    require(receipt == env["WORKER_RECEIPT_KEY"])


if __name__ == "__main__":
    try:
        route = os.environ["WORKER_ROUTE"]
        require(route in {"web", "display"})
        repo = Path(__file__).resolve().parents[1]
        manifest = parse((repo / f".github/ci-cutover/{route}-rehearsal.json").read_text())
        guard(manifest, os.environ)
    except (KeyError, OSError, TypeError, ValueError, UnicodeError):
        raise SystemExit("ci_rehearsal=refused") from None
