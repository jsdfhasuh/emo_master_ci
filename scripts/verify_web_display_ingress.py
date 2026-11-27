"""Credential-free Source worker identity check while the product is Public."""
import json
import re
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

REPO_ID=1343796337
BASE="https://api.github.com/repos/jsdfhasuh/emo_master"
MAX=1_048_576


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def fetch(path):
    req=Request(BASE+path,headers={"Accept":"application/vnd.github+json",
                    "X-GitHub-Api-Version":"2022-11-28","User-Agent":"emo-ci-public-source-ingress"})
    with build_opener(NoRedirect()).open(req,timeout=15) as response:
        data=response.read(MAX+1)
    require(len(data)<=MAX)
    return json.loads(data)


def require(ok):
    if not ok:
        raise ValueError("source_request_refused")


def sha(x):
    require(type(x) is str and re.fullmatch(r"[0-9a-f]{40}",x) and x!="0"*40)
    return x


def ident(x):
    require(type(x) is int and 0<x<2**63)
    return x


def check(operator, message, read=fetch, route="source"):
    """Require trusted dispatch actor guard in the workflow, then prove public source."""
    keys={"schema","source_run","source_attempt","artifact_id","artifact_digest","head","base","execution","pr","route"}
    require(type(message) is dict and set(message)==keys and message["route"]==route and
            type(message["schema"]) is int and message["schema"]==1)
    number=ident(message["source_run"])
    attempt=ident(message["source_attempt"])
    aid=ident(message["artifact_id"])
    head,execution=sha(message["head"]),sha(message["execution"])
    digest=message["artifact_digest"]
    require(type(digest) is str and re.fullmatch(r"sha256:[0-9a-f]{64}",digest))
    repo=read("")
    require(repo.get("id")==REPO_ID and repo.get("private") is False)  # separate private relay needed
    run=read(f"/actions/runs/{number}")
    require(run.get("id")==number and run.get("run_attempt")==attempt and
            run.get("workflow_id")==ident(operator["origin_workflow_id"]) and run.get("path")==operator["origin_path"] and
            run.get("repository",{}).get("id")==REPO_ID and run.get("head_repository",{}).get("id")==REPO_ID and
            run.get("head_sha")==head and run.get("status")=="completed" and run.get("conclusion")=="success")
    art=read(f"/actions/artifacts/{aid}")
    identity=art["workflow_run"]
    require(art.get("id")==aid and art.get("expired") is False and art.get("name")==f"ci-request-{number}-{attempt}" and
            art.get("digest")==digest and type(art.get("size_in_bytes")) is int and 0<art["size_in_bytes"]<=32768 and
            identity.get("id")==number and identity.get("head_sha")==head and
            identity.get("repository_id")==REPO_ID and identity.get("head_repository_id")==REPO_ID)
    def ref(path):
        return read("/git/ref/"+quote(path,safe="/"))["object"]["sha"]
    event=run.get("event")
    if event=="pull_request":
        pr=ident(message["pr"]); base=sha(message["base"])
        link=run["pull_requests"]
        require(len(link)==1 and link[0].get("number")==pr and link[0]["head"]["sha"]==head and link[0]["base"]["sha"]==base)
        live=read(f"/pulls/{pr}")
        hb,bb=live["head"],live["base"]
        require(live.get("number")==pr and live.get("state")=="open" and live.get("mergeable") is True and
                live.get("merge_commit_sha")==execution and hb["sha"]==head and bb["sha"]==base and
                hb["repo"]["id"]==bb["repo"]["id"]==REPO_ID and hb["ref"] in operator["trusted_pr_heads"] and
                bb["ref"] in operator["trusted_pr_bases"] and run["head_branch"]==hb["ref"])
        require(ref(f"heads/{hb['ref']}")==head and ref(f"heads/{bb['ref']}")==base and
                ref(f"pull/{pr}/merge")==execution)
        commit=read(f"/git/commits/{execution}")
        require(commit.get("sha")==execution and [p["sha"] for p in commit["parents"]]==[base,head])
    else:
        require(event in ("push","workflow_dispatch") and message["base"] is message["pr"] is None and head==execution)
        allowed=operator["trusted_push_branches"] if event=="push" else operator["trusted_manual_branches"]
        require(run["head_branch"] in allowed and ref("heads/"+run["head_branch"])==head)
    path=operator["origin_path"]
    require(re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml",path))
    blob=read(f"/contents/{path}?ref={execution}")
    require(blob.get("sha")==sha(operator["approved_emitter_blob"]) and blob.get("type")=="file")
    return execution, event



def main():
    import os
    from pathlib import Path
    def unique(pairs):
        out={}
        for key,value in pairs:
            require(key not in out)
            out[key]=value
        return out
    try:
        route=os.environ["WORKER_ROUTE"]
        require(route in {"web","display"})
        policy=json.loads((Path(__file__).resolve().parents[1] /
              f".github/ci-cutover/{route}-public-policy.json").read_text(),object_pairs_hook=unique)
        require(policy["enabled"] is True)
        approved_actor=ident(int(os.environ["REHEARSAL_ACTOR_ID"]))
        require(os.environ["GITHUB_EVENT_NAME"]=="workflow_dispatch" and
                os.environ["GITHUB_REF"].startswith("refs/tags/ci-worker-") and
                os.environ["GITHUB_SHA"]==os.environ["WORKER_CONTROLLER_SHA"] and
                os.environ["GITHUB_REPOSITORY_ID"]=="1468905732" and
                os.environ["GITHUB_ACTOR_ID"]==str(approved_actor) and os.environ["GITHUB_RUN_ATTEMPT"]=="1")
        raw=os.environ["WORKER_REQUEST"].encode("ascii")
        require(0<len(raw)<=4096)
        message=json.loads(raw,object_pairs_hook=unique)
        execution,event=check(policy,message,route=route)
        require(route!="display" or event!="pull_request")
        with open(os.environ["GITHUB_OUTPUT"],"a",encoding="ascii") as out:
            out.write(f"execution_sha={execution}\nsource_event={event}\n")
    except Exception:
        raise SystemExit("ci_event_ingress=refused") from None


if __name__=="__main__":
    main()
