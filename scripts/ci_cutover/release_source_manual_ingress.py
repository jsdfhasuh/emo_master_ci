"""Read-only gate for an exact manual, branch-only, no-publication release-source rehearsal."""
import base64
import hashlib
import json
import os
import re
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

REPO=1343796337
OWNER=49879362
ORIGIN_BRANCH="dot/release-source-manual-origin-20261127"
ORIGIN_PATH=".github/workflows/runtime-windows.yml"
ORIGIN_ID=390286027
ADAPTER="6c0f31b7d96aa0e77d67120cec5b5fb842781c5e"
ROUTE="release-source-manual"
PRODUCT="7fccb4988ad0e4abd390110dbb29c80151f5bb3b"
APP_VERSION="0.6.6"
API="https://api.github.com/repos/jsdfhasuh/emo_master"
PACKAGER_API="https://api.github.com/repos/jsdfhasuh/python_build_scripts"
PACKAGER_CONFIG_SHA="e0204fe6fe83b0f31818d88e4f296c70e230d172"
PACKAGER_TREE="49a22cf7a749c47ac25e0ab65ff4ff5d8a3bbd40"
PACKAGER_CONFIG_BLOBS={
    "configs/emo-master.json":"a93dcf4ef1c9d540621a5ad54d3ebac29c2ec7d3",
    "configs/emo-master-runtime.json":"3b949a2d60643d2750e69a806f5e5dfe279ca84c",
}
MAX=1_048_576
HELPERS={
    ".github/workflows/emit-ci-cutover-request.yml":"e8ca828481afc4f41d0d39a014ab697f86f8f382",
    "scripts/ci_cutover/request_emitter.py":"287bae93af96c277c76b995479a9a8d1a1518d32",
}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def require(ok):
    if not ok:
        raise ValueError("manual source request refused")

def ident(value):
    require(type(value) is int and 0<value<2**63)
    return value

def sha(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{40}",value) and value!="0"*40)
    return value

def _fetch(api,path):
    req=Request(api+path,method="GET",headers={"Accept":"application/vnd.github+json",
                "X-GitHub-Api-Version":"2022-11-28","User-Agent":"emo-ci-release-source-manual"})
    with build_opener(NoRedirect()).open(req,timeout=15) as response:
        data=response.read(MAX+1)
    require(len(data)<=MAX)
    return json.loads(data)

def fetch(path):
    return _fetch(API,path)

def verify_packager_config(read):
    """Verify these precise data files. No checkout, workflow load or builder execution."""
    commit=read("/git/commits/"+PACKAGER_CONFIG_SHA)
    require(commit.get("sha")==PACKAGER_CONFIG_SHA and commit.get("tree",{}).get("sha")==PACKAGER_TREE)
    for path,pinned in PACKAGER_CONFIG_BLOBS.items():
        row=read(f"/contents/{path}?ref={PACKAGER_CONFIG_SHA}")
        require(row.get("path")==path and row.get("type")=="file" and row.get("sha")==pinned
                and row.get("encoding")=="base64" and type(row.get("size")) is int and 0<row["size"]<=8192)
        blob=base64.b64decode("".join(row["content"].split()),validate=True)
        require(len(blob)==row["size"])
        require(hashlib.sha1(f"blob {len(blob)}\0".encode("ascii")+blob).hexdigest()==pinned)
        config=json.loads(blob,object_pairs_hook=unique)
        require(config.get("source_repo")==config.get("release_repo")=="jsdfhasuh/emo_master"
                and config.get("source_version_file")=="${SOURCE_ROOT}/src/emo_master/__init__.py"
                and config.get("python_version")=="3.10")
    return PACKAGER_CONFIG_SHA

def fetch_packager(path):
    return _fetch(PACKAGER_API,path)

def unique(pairs):
    out={}
    for key,value in pairs:
        require(key not in out)
        out[key]=value
    return out

def verify(policy,message,read):
    require(type(policy) is dict and set(policy)=={"enabled","route","origin_sha","adapter_blob"})
    require(policy["enabled"] is True and policy["route"]==ROUTE)
    origin=sha(policy["origin_sha"])
    adapter=sha(policy["adapter_blob"])
    require(adapter==ADAPTER)
    require(type(message) is dict and set(message)=={
        "schema","source_run","source_attempt","artifact_id","artifact_digest","head","base","execution","pr","route","packager_config_sha"})
    require(type(message["schema"]) is int and message["schema"]==1 and message["route"]==ROUTE
            and message["packager_config_sha"]==PACKAGER_CONFIG_SHA)
    number=ident(message["source_run"]); aid=ident(message["artifact_id"])
    require(ident(message["source_attempt"])==1 and message["base"] is message["pr"] is None)
    require(sha(message["head"])==origin and sha(message["execution"])==PRODUCT and origin!=PRODUCT)
    digest=message["artifact_digest"]
    require(type(digest) is str and re.fullmatch("sha256:[0-9a-f]{64}",digest))
    repo=read("")
    require(repo.get("id")==REPO and repo.get("private") is False)
    run=read(f"/actions/runs/{number}/attempts/1")
    require(run.get("id")==number and run.get("run_attempt")==1 and run.get("workflow_id")==ORIGIN_ID
            and run.get("path")==ORIGIN_PATH and run.get("event")=="workflow_dispatch"
            and run.get("head_sha")==origin and run.get("head_branch")==ORIGIN_BRANCH
            and run.get("status")=="completed" and run.get("conclusion")=="success"
            and run.get("repository",{}).get("id")==REPO and run.get("head_repository",{}).get("id")==REPO
            and run.get("actor",{}).get("id")==OWNER and run.get("triggering_actor",{}).get("id")==OWNER
            and run.get("pull_requests")==[])
    art=read(f"/actions/artifacts/{aid}")
    identity=art["workflow_run"]
    require(art.get("id")==aid and art.get("expired") is False
            and art.get("name")==f"ci-request-{number}-1" and art.get("digest")==digest
            and type(art.get("size_in_bytes")) is int and 0<art["size_in_bytes"]<=32768
            and identity.get("id")==number and identity.get("head_sha")==origin
            and identity.get("repository_id")==identity.get("head_repository_id")==REPO)
    pointer=read("/git/ref/heads/"+quote(ORIGIN_BRANCH,safe="/"))["object"]
    require(pointer.get("type")=="commit" and pointer.get("sha")==origin)
    for path,blob in {ORIGIN_PATH:adapter,**HELPERS}.items():
        row=read(f"/contents/{path}?ref={origin}")
        require(row.get("type")=="file" and row.get("sha")==blob)
    require(read("/git/commits/"+PRODUCT).get("sha")==PRODUCT)
    return origin,number,aid,digest

def main(read=fetch,read_packager=fetch_packager):
    try:
        raw=os.environ["WORKER_REQUEST"].encode("ascii")
        require(0<len(raw)<=4096)
        with open("controller/.github/ci-cutover/release-source-manual-public-policy.json","rb") as stream:
            policy=json.load(stream,object_pairs_hook=unique)
        origin,number,aid,digest=verify(policy,json.loads(raw,object_pairs_hook=unique),read)
        checked_config=verify_packager_config(read_packager)
        with open(os.environ["GITHUB_OUTPUT"],"a",encoding="ascii") as out:
            out.write(f"execution_sha={PRODUCT}\nexpected_app_version={APP_VERSION}\norigin_head_sha={origin}\norigin_run={number}\norigin_artifact_id={aid}\norigin_artifact_digest={digest}\npackager_config_sha={checked_config}\n")
    except Exception:
        raise SystemExit("release_source_manual_ingress=refused") from None

if __name__=="__main__":
    main()
