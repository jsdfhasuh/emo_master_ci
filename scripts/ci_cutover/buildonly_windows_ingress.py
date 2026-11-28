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


def check(operator, message, read=fetch):
    """Require trusted dispatch actor guard in the workflow, then prove public source."""
    keys={"schema","source_run","source_attempt","artifact_id","artifact_digest","head","base","execution","pr","route"}
    require(type(message) is dict and set(message)==keys and message["route"]==operator["route"] and
            type(message["schema"]) is int and message["schema"]==1)
    number=ident(message["source_run"])
    attempt=ident(message["source_attempt"])
    aid=ident(message["artifact_id"])
    head,execution=sha(message["head"]),sha(message["execution"])
    require(head==sha(operator["expected_native_head"]))
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
    designer_fixed=operator["route"]=="windows-package" and "expected_execution_sha" in operator
    if designer_fixed:
        require(event=="workflow_dispatch" and execution==sha(operator["expected_execution_sha"]))
        commit=read("/git/commits/"+execution)
        require(commit.get("sha")==execution)
    release_tag=""
    if operator["route"]=="release-source":
        release_tag=run["head_branch"]
        require(event=="push" and message["base"] is message["pr"] is None and execution==head)
        require(re.fullmatch(r"v[0-9]+(?:\.[0-9]+){1,3}(?:[-.][A-Za-z0-9._-]+)?",release_tag))
        obj=read("/git/ref/tags/"+quote(release_tag,safe=""))["object"]
        for _ in range(8):
            if obj["type"]!="tag":
                break
            obj=read("/git/tags/"+sha(obj["sha"]))["object"]
        require(obj["type"]=="commit" and obj["sha"]==execution)
    elif event=="pull_request":
        require(operator["route"]=="windows-package")
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
        require(event=="workflow_dispatch" and message["base"] is message["pr"] is None and
                (head==execution or operator["route"]=="runtime-windows" or designer_fixed))
        allowed=operator["trusted_push_branches"] if event=="push" else operator["trusted_manual_branches"]
        require(run["head_branch"] in allowed and ref("heads/"+run["head_branch"])==head)
    path=operator["origin_path"]
    require(re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml",path))
    emitter_revision=head if operator["route"]=="runtime-windows" or designer_fixed else execution
    blob=read(f"/contents/{path}?ref={emitter_revision}")
    require(blob.get("sha")==sha(operator["approved_emitter_blob"]) and blob.get("type")=="file")
    helpers=operator["helper_blobs"]
    require(type(helpers) is dict and set(helpers)=={".github/workflows/emit-ci-cutover-request.yml","scripts/ci_cutover/request_emitter.py"})
    for helper,expected in helpers.items():
        actual=read(f"/contents/{helper}?ref={emitter_revision}")
        require(actual.get("type")=="file" and actual.get("sha")==sha(expected))
    return execution, release_tag


def main():
    import os
    try:
        require(re.fullmatch(r"[0-9a-f]{64}",os.environ["WORKER_RECEIPT"]))
        raw=os.environ.get("WORKER_REQUEST","").encode("ascii")
        require(0<len(raw)<=4096)
        def decode_unique(pairs):
            obj={}
            for k,v in pairs:
                require(k not in obj)
                obj[k]=v
            return obj
        route=os.environ.get("WORKER_ROUTE")
        require(route == "windows-package")
        with open(f"controller/.github/ci-cutover/{route}-public-policy.json","rb") as handle:
            policy=json.load(handle,object_pairs_hook=decode_unique)
        require(policy.get("enabled") is True and policy.get("route")==route)  # no fallback or variable loosening
        execution, release_tag=check(policy,json.loads(raw,object_pairs_hook=decode_unique),fetch)
        with open(os.environ["GITHUB_OUTPUT"],"a",encoding="ascii") as out:
            out.write(f"execution_sha={execution}\nrelease_tag={release_tag}\n")
    except Exception:
        raise SystemExit("source_public_ingress=refused") from None


if __name__=="__main__":
    main()
