"""Verify one live diagnostic transport and seal a historical evidence witness."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import zipfile
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

HOST="https://api.github.com/repos/"
PRODUCT="jsdfhasuh/emo_master"
PUBLIC="jsdfhasuh/emo_master_ci"
PRODUCT_ID=1343796337
PUBLIC_ID=1468905732
TAG="ci-worker-runtime-diagnostic-owner-rehearsal-20261127"
OWNER=49879362
BRANCH="dot/runtime-native-origin-20261127"
SOURCE="ed7d647ee40831cbae251a37323c3f5dba71c7e7"
BASE="7fccb4988ad0e4abd390110dbb29c80151f5bb3b"
AGE_HASH="46db0db71f146061f7c8fffa912cb806aef1bc8450e27a3abc1744f0591b89fb"
RECIPIENT_HASH="ba311eeae31312c73f57c9a2cc4c80bbb58380e7c3df956db1d09432b79cca87"
LANES={"a18","capture","sqlite-append","sqlite-failure","stop"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*_):
        return None


def need(ok):
    if not ok:
        raise ValueError("diagnostic reuse refused")


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(repo,path):
    need(repo in (PRODUCT,PUBLIC))
    request=Request(HOST+repo+path,headers={"Accept":"application/vnd.github+json",
                    "X-GitHub-Api-Version":"2022-11-28","User-Agent":"emo-ci-diagnostic-reuse"})
    with build_opener(NoRedirect()).open(request,timeout=15) as response:
        raw=response.read(3*1024*1024+1)
    need(len(raw)<=3*1024*1024)
    return json.loads(raw)


def identity_repo(data,name,rid):
    return data.get("id")==rid and data.get("full_name")==name and data.get("private") is False


def artifact(row, *, aid, name, size, hash_, run, repo, head):
    provenance=row["workflow_run"]
    need(row.get("id")==aid and row.get("name")==name and row.get("expired") is False
         and row.get("size_in_bytes")==size and row.get("digest")==hash_
         and provenance.get("id")==run and provenance.get("head_sha")==head
         and provenance.get("repository_id")==repo and provenance.get("head_repository_id")==repo)


def run_identity(row, repo, *, rid, attempt, workflow, path, head, completed):
    need(row.get("id")==rid and row.get("run_attempt")==attempt and row.get("workflow_id")==workflow
         and row.get("path")==path and row.get("head_sha")==head
         and row["repository"].get("id")==repo and row["head_repository"].get("id")==repo)
    if completed:
        need(row.get("status")=="completed" and row.get("conclusion")=="success")
    else:
        need(row.get("status")=="in_progress" and row.get("conclusion") is None)


def diff(data,pins):
    need(data.get("status")=="ahead" and data["base_commit"]["sha"]==BASE and data["merge_base_commit"]["sha"]==BASE
         and data.get("total_commits")==pins["total_commits"])
    rows=data["files"]
    need(type(rows) is list and len(rows)==38 and not any(row.get("previous_filename") for row in rows))
    changed=sorted([[row["filename"],row["status"],row["sha"]] for row in rows])
    need(len({row[0] for row in changed})==38 and changed==pins["files"])
    need(all(row[0] in pins["workflow_paths"] or row[0].startswith("scripts/ci_cutover/")
             or row[0].startswith("openspec/") for row in changed))
    return {"base":BASE,"head":SOURCE,"merge_base":BASE,"changed_files":38,
            "paths_sha256":digest(canonical([row[0] for row in changed]).encode("ascii"))}


def verify(pins,env,read=fetch):
    route=env["WORKER_ROUTE"]
    need(route in LANES and pins["route"]==route)
    source,past=pins["source"],pins["historical"]
    worker_sha=env["GITHUB_WORKFLOW_SHA"]
    path=f".github/workflows/dispatch-{route}.yml"
    need(env["GITHUB_EVENT_NAME"]=="workflow_dispatch" and env["GITHUB_RUN_ATTEMPT"]=="1"
         and env["GITHUB_REPOSITORY_ID"]==str(PUBLIC_ID) and env["GITHUB_ACTOR_ID"]==str(OWNER)
         and env["GITHUB_REF"]==f"refs/tags/{TAG}" and env["GITHUB_SHA"]==worker_sha
         and bool(re.fullmatch(r"[a-f0-9]{40}",worker_sha)) and worker_sha!="0"*40
         and env["GITHUB_WORKFLOW_REF"]==f"{PUBLIC}/{path}@refs/tags/{TAG}")
    need(identity_repo(read(PUBLIC,""),PUBLIC,PUBLIC_ID) and identity_repo(read(PRODUCT,""),PRODUCT,PRODUCT_ID))
    tag=read(PUBLIC,"/git/ref/tags/"+TAG)["object"]
    need(tag.get("type")=="commit" and tag.get("sha")==worker_sha)
    workflow=read(PUBLIC,f"/actions/workflows/{path.rsplit('/',1)[1]}")
    wid=workflow["id"]
    need(type(wid) is int and wid>0 and workflow.get("path")==path and workflow.get("state")=="active")
    request=canonical(pins["request"])
    need(env["WORKER_REQUEST"]==request)
    receipt=digest(canonical([wid,path,TAG,worker_sha,OWNER,request]).encode("ascii"))
    need(receipt==env["WORKER_RECEIPT"])
    public_run=int(env["GITHUB_RUN_ID"])
    current=read(PUBLIC,f"/actions/runs/{public_run}")
    run_identity(current,PUBLIC_ID,rid=public_run,attempt=1,workflow=wid,path=path,head=worker_sha,completed=False)
    need(current["actor"].get("id")==OWNER and current.get("event")=="workflow_dispatch"
         and current.get("head_branch")==TAG and current.get("display_title")==f"emo-ci-candidate-{receipt}")
    need(read(PRODUCT,"/git/ref/heads/"+quote(BRANCH,safe="/"))["object"]["sha"]==SOURCE)
    origin=read(PRODUCT,f"/actions/runs/{source['run']}")
    run_identity(origin,PRODUCT_ID,rid=source["run"],attempt=source["attempt"],workflow=source["workflow_id"],
                 path=source["path"],head=SOURCE,completed=True)
    need(origin.get("event")=="workflow_dispatch" and origin.get("head_branch")==BRANCH and origin["actor"]["id"]==OWNER)
    origin_workflow=read(PRODUCT,f"/actions/workflows/{source['workflow_id']}")
    need(origin_workflow.get("id")==source["workflow_id"] and origin_workflow.get("path")==source["path"]
         and origin_workflow.get("state")=="active")
    origin_blob=read(PRODUCT,f"/contents/{source['path']}?ref={SOURCE}")
    need(origin_blob.get("type")=="file" and origin_blob.get("path")==source["path"]
         and origin_blob.get("sha")==pins["origin_blob"])
    item=read(PRODUCT,f"/actions/artifacts/{source['artifact_id']}")
    artifact(item,aid=source["artifact_id"],name=f"ci-request-{source['run']}-{source['attempt']}",
             size=pins["origin_artifact_size"],hash_=source["artifact_digest"],run=source["run"],repo=PRODUCT_ID,head=SOURCE)
    hrun=read(PUBLIC,f"/actions/runs/{past['run']}")
    run_identity(hrun,PUBLIC_ID,rid=past["run"],attempt=past["attempt"],workflow=pins["historical_workflow_id"],
                 path=past["path"],head=past["workflow_sha"],completed=True)
    job=read(PUBLIC,f"/actions/jobs/{past['job_id']}")
    need(job.get("id")==past["job_id"] and job.get("run_id")==past["run"]
         and job.get("head_sha")==past["workflow_sha"] and job.get("status")=="completed"
         and job.get("conclusion")=="success" and job.get("name")==pins["historical_job_name"])
    item=read(PUBLIC,f"/actions/artifacts/{past['artifact_id']}")
    artifact(item,aid=past["artifact_id"],name=past["artifact_name"],size=past["artifact_size"],
             hash_=past["artifact_digest"],run=past["run"],repo=PUBLIC_ID,head=past["workflow_sha"])
    compared=diff(read(PRODUCT,f"/compare/{BASE}...{SOURCE}?per_page=1&page=1"),pins["diff"])
    return {"schema":1,"encryption_profile":"V2","scope":"diagnostic-evidence-reuse-transport-only",
            "reused_original_workload":True,"original_workload_rerun":False,"route":route,
            "source":source,"source_execution":SOURCE,"worker":{"repository_id":PUBLIC_ID,
            "workflow_id":wid,"path":path,"run":public_run,"attempt":1,"sha":worker_sha,
            "actor_id":OWNER,"tag":TAG,"receipt_key":receipt},
            "historical":past,"diff":compared}


def seal(report,root,recipient):
    need(bool(re.fullmatch(r"age1[023456789ac-hj-np-z]{58}",recipient)) and digest(recipient.encode("ascii"))==RECIPIENT_HASH)
    req=Request("https://github.com/FiloSottile/age/releases/download/v1.2.1/age-v1.2.1-windows-amd64.zip",
                headers={"User-Agent":"emo-ci-diagnostic-reuse"})
    with build_opener().open(req,timeout=35) as response:
        need(response.geturl().startswith("https://"))
        data=response.read(12*1024*1024+1)
    need(digest(data)==AGE_HASH)
    age=root/"diagnostic-reuse-age.exe"
    with zipfile.ZipFile(io.BytesIO(data)) as bundle,age.open("xb") as executable:
        executable.write(bundle.read("age/age.exe"))
    output=root/f"{report['route']}-reuse-witness.age"
    raw=canonical(report).encode("ascii")
    need(len(raw)<=8192 and not output.exists())
    try:
        subprocess.run([str(age),"-r",recipient,"-o",str(output)],input=raw,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=25)
        with output.open("rb") as handle:
            need(handle.readline(64)==b"age-encryption.org/v1\n")
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main():
    try:
        route=os.environ["WORKER_ROUTE"]
        need(route in LANES)
        parent=Path(__file__).resolve().parents[2]
        pins=json.loads((parent/".github"/"ci-cutover"/f"{route}-reuse-pins.json").read_text(encoding="ascii"))
        report=verify(pins,os.environ)
        seal(report,Path(os.environ["RUNNER_TEMP"]),os.environ["RECIPIENT"])
    except Exception:
        raise SystemExit("diagnostic_reuse=refused") from None
    print("diagnostic_reuse=verified; workload_rerun=false")


if __name__=="__main__":
    main()
