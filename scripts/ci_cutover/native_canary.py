"""Synthetic transport proof. No product downloads, secrets, or execution."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

TAG="ci-worker-native-transport-canary-v3"
PATH=".github/workflows/dispatch-source-candidate.yml"
OWNER=49879362
WID=432245931
REPO=1343796337
ROUTE="transport-canary"
FIELDS={"schema","source_run","source_attempt","artifact_id","artifact_digest","head","base","execution","pr","route"}


class CanaryRefused(ValueError):
    def __init__(self, phase, reason="invariant", *, http=None, retry_after=None):
        super().__init__(phase)
        self.phase, self.reason, self.http, self.retry_after = phase, reason, http, retry_after

    def report(self):
        fields = [f"phase={self.phase}", f"reason={self.reason}"]
        if self.http is not None:
            fields.append(f"http={self.http}")
        if self.retry_after is not None:
            fields.append(f"retry_after={self.retry_after}")
        return "native_canary_refused " + " ".join(fields)


def read_metadata(get, path, phase):
    try:
        return get(path)
    except HTTPError as err:
        with err:
            raw = err.headers.get("Retry-After", "") if err.headers is not None else ""
            retry = int(raw) if re.fullmatch(r"[0-9]{1,8}", raw) else None
            code = err.code
        raise CanaryRefused(phase, "http", http=code, retry_after=retry) from None
    except (TimeoutError, URLError, OSError):
        raise CanaryRefused(phase, "transport") from None
    except (UnicodeError, ValueError):
        raise CanaryRefused(phase, "response") from None


def canon(obj):
    return json.dumps(obj,ensure_ascii=True,sort_keys=True,separators=(",",":"))


def positive(x):
    return type(x) is int and 0<x<2**63


def commit(s):
    return type(s) is str and re.fullmatch(r"[0-9a-f]{40}",s) and s!="0"*40


def make(wire,key,worker_sha,run_id,attempt,get):
    phase="request_binding"
    def need(ok):
        if not ok: raise CanaryRefused(phase)
    def set_phase(value):
        nonlocal phase
        phase=value
    try:
        return validate(wire,key,worker_sha,run_id,attempt,get,need,set_phase)
    except CanaryRefused:
        raise
    except (KeyError,TypeError,ValueError):
        raise CanaryRefused(phase,"shape") from None


def validate(wire,key,worker_sha,run_id,attempt,get,need,set_phase):
    need(type(wire) is str and wire.isascii() and 0<len(wire)<=4096 and commit(worker_sha))
    obj=json.loads(wire)
    need(canon(obj)==wire and set(obj)==FIELDS and obj["route"]==ROUTE and type(obj["schema"]) is int and obj["schema"]==1)
    need(re.fullmatch(r"[a-f0-9]{64}",key) and positive(run_id) and type(attempt) is int and attempt==1)
    need(key==sha256(canon([WID,PATH,TAG,worker_sha,OWNER,wire]).encode("ascii")).hexdigest())
    rid,att,aid=obj["source_run"],obj["source_attempt"],obj["artifact_id"]
    need(all(positive(v) for v in (rid,att,aid)) and commit(obj["head"]) and commit(obj["execution"])
         and re.fullmatch(r"sha256:[a-f0-9]{64}",obj["artifact_digest"]))
    set_phase("origin_metadata")
    source=read_metadata(get,f"/actions/runs/{rid}","origin_metadata")
    event=source.get("event")
    need(event in ("push","pull_request","workflow_dispatch") and source["id"]==rid and source["run_attempt"]==att
         and source["repository"]["id"]==source["head_repository"]["id"]==REPO and source["head_sha"]==obj["head"]
         and source["actor"]["id"]==source["triggering_actor"]["id"]==OWNER)
    if event=="workflow_dispatch":
        set_phase("manual_origin")
        # Isolated manual branch may use the already registered CI path; never
        # select main or the normal heavyweight source workflow.
        need((source["workflow_id"],source["path"],source["head_branch"]) in (
            (433407309,".github/workflows/phase4-native-event-receipt.yml","dot/phase4-event-head"),
            (341122678,".github/workflows/ci.yml","dot/phase4-event-manual")))
    else:
        need((source["workflow_id"],source["path"],source["head_branch"]) ==
             (433407309,".github/workflows/phase4-native-event-receipt.yml","dot/phase4-event-head"))
    if event=="pull_request":
        set_phase("pr_metadata")
        need(positive(obj["pr"]) and commit(obj["base"]))
        pr=read_metadata(get,"/pulls/"+str(obj["pr"]),"pr_metadata")
        need(pr["state"]=="open" and pr["head"]["repo"]["id"]==pr["base"]["repo"]["id"]==REPO
             and pr["head"]["ref"]=="dot/phase4-event-head" and pr["base"]["ref"]=="dot/phase4-event-base"
             and pr["head"]["sha"]==obj["head"] and pr["base"]["sha"]==obj["base"] and pr["merge_commit_sha"]==obj["execution"])
    else:
        need(obj["pr"] is obj["base"] is None and obj["head"]==obj["execution"])
    set_phase("receipt_metadata")
    ar=read_metadata(get,f"/actions/artifacts/{aid}","receipt_metadata")
    need(ar["id"]==aid and ar["name"]==f"ci-request-{rid}-{att}" and ar["expired"] is False and ar["digest"]==obj["artifact_digest"]
         and ar["workflow_run"]["id"]==rid and ar["workflow_run"]["head_sha"]==obj["head"]
         and ar["workflow_run"]["repository_id"]==ar["workflow_run"]["head_repository_id"]==REPO)
    payload=b"emo-ci/native-transport-canary/v1\n"
    return {"schema":1,"kind":ROUTE,"request":key,"origin_run":rid,"origin_attempt":att,
            "event":event,"head":obj["head"],"execution":obj["execution"],"worker_sha":worker_sha,
            "worker_run":run_id,"worker_attempt":attempt,"fixture_sha256":sha256(payload).hexdigest()}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def main():
    env=os.environ
    token=env.pop("PUBLIC_ACTIONS_READ_TOKEN")
    if not token.isascii() or not token or any(c.isspace() for c in token):
        raise CanaryRefused("origin_metadata", "missing_repository_read_token")
    http=build_opener(NoRedirect())
    def get(path):
        req=Request("https://api.github.com/repos/jsdfhasuh/emo_master"+path,
                    headers={"Accept":"application/vnd.github+json","User-Agent":"isolated-native-canary","Authorization":"Bearer "+token})
        with http.open(req,timeout=15) as r: data=r.read(262145)
        if len(data)>262144: raise ValueError("size bound")
        return json.loads(data)
    proof=make(env["REQUEST"],env["KEY"],env["GITHUB_SHA"],int(env["GITHUB_RUN_ID"]),int(env["GITHUB_RUN_ATTEMPT"]),get)
    with (Path(env["RUNNER_TEMP"])/"proof.json").open("x",encoding="ascii") as out: out.write(canon(proof)+"\n")
    print("synthetic_transport_fixture=complete")


if __name__=="__main__":
    try:main()
    except CanaryRefused as err:raise SystemExit(err.report()) from None
    except Exception:raise SystemExit("native_canary_refused phase=runner reason=setup_or_output") from None
