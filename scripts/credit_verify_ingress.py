"""Read-only fixed rehearsal guard. Deployment must supply independently reviewed pins."""
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen

PRODUCT="jsdfhasuh/emo_master"; PUBLIC="jsdfhasuh/emo_master_ci"
BRANCH="dot/credit-readiness-native-receipt-20261127"; TAG="ci-worker-credit-readiness-native-proof-20261127"
PATH=".github/workflows/dispatch-credit.yml"
ORIGIN_PATH=".github/workflows/runtime-credit-diagnostics.yml"
OWNER=49879362


def check(ok):
    if not ok:raise ValueError


def fetch(repo,path):
    request=Request(f"https://api.github.com/repos/{repo}{path}",headers={
        "Accept":"application/vnd.github+json","User-Agent":"emo-ci-credit-witness"})
    with urlopen(request,timeout=15) as f:
        raw=f.read(2*1024*1024+1)
    check(len(raw)<=2*1024*1024)
    return json.loads(raw)


def main():
    e=os.environ
    pins=json.loads((Path(__file__).resolve().parents[1]/".github/credit-review/ingress.json").read_text())
    sha=e["GITHUB_WORKFLOW_SHA"]; source=pins["source_sha"]
    check(sha==e["GITHUB_SHA"] and e["SOURCE_SHA"]==source and
          e["GITHUB_WORKFLOW_REF"]==f"{PUBLIC}/{PATH}@refs/tags/{TAG}")
    check(e["GITHUB_REPOSITORY_ID"]=="1468905732" and e["GITHUB_EVENT_NAME"]=="workflow_dispatch"
          and e["GITHUB_ACTOR_ID"]==str(OWNER) and e["GITHUB_RUN_ATTEMPT"]=="1" and
          e["GITHUB_REF"]==f"refs/tags/{TAG}")
    tag=fetch(PUBLIC,f"/git/ref/tags/{TAG}")["object"]
    check(tag["sha"]==sha and tag["type"]=="commit")
    registry=fetch(PUBLIC,f"/actions/workflows/{PATH.rsplit('/',1)[1]}")
    worker_id=registry["id"];check(registry["path"]==PATH and registry["state"]=="active")
    req=pins["request"]; wire=json.dumps(req,sort_keys=True,separators=(",",":"),ensure_ascii=True)
    check(req["route"]=="credit" and req["execution"]==source and req["head"]==pins["receipt_sha"]
          and req["base"] is None and req["pr"] is None and req["source_attempt"]==1 and e["WORKER_REQUEST"]==wire)
    key=hashlib.sha256(json.dumps([worker_id,PATH,TAG,sha,OWNER,wire],separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
    check(key==e["WORKER_RECEIPT"])
    current=fetch(PUBLIC,f"/actions/runs/{int(e['GITHUB_RUN_ID'])}")
    check(current["workflow_id"]==worker_id and current["head_sha"]==sha and current["actor"]["id"]==OWNER
          and current["run_attempt"]==1 and current["head_branch"]==TAG and current["status"]=="in_progress"
          and current["path"]==PATH and current["display_title"]==f"emo-ci-candidate-{key}")
    origin=fetch(PRODUCT,f"/actions/runs/{req['source_run']}")
    check(origin["workflow_id"]==pins["origin_workflow_id"] and origin["path"]==ORIGIN_PATH
          and origin["head_sha"]==req["head"] and origin["head_branch"]==BRANCH and origin["actor"]["id"]==OWNER
          and origin["repository"]["id"]==origin["head_repository"]["id"]==1343796337
          and origin["run_attempt"]==1 and origin["event"]=="workflow_dispatch"
          and origin["status"]=="completed" and origin["conclusion"]=="success")
    check(fetch(PRODUCT,f"/git/ref/heads/{BRANCH}")["object"]["sha"]==req["head"])
    comparison=fetch(PRODUCT,f"/compare/{source}...{req['head']}?per_page=1&page=1")
    check(comparison["status"]=="ahead" and comparison["total_commits"]==1
          and comparison["merge_base_commit"]["sha"]==source
          and [(x["filename"],x["status"],x["sha"]) for x in comparison["files"]]
          ==[(ORIGIN_PATH,"modified",pins["origin_blob"])])
    art=fetch(PRODUCT,f"/actions/artifacts/{req['artifact_id']}")
    check(art["name"]==f"credit-native-request-{req['source_run']}-1" and art["digest"]==req["artifact_digest"]
          and art["size_in_bytes"]==pins["artifact_size"] and art["expired"] is False
          and art["workflow_run"]["id"]==req["source_run"] and art["workflow_run"]["head_sha"]==req["head"])

if __name__=="__main__":
    try:main()
    except Exception:raise SystemExit("credit_native_proof=refused") from None
