"""Exact, harmless fixture transport. No arbitrary paths, URLs or executable payload."""
import base64, hashlib, io, json, os, re, subprocess, urllib.error, urllib.parse, urllib.request, zipfile
from pathlib import Path
API="https://api.github.com/repos/jsdfhasuh/"
PUB="emo_master_ci"
PUBLIC_ID=1468905732
PRIVATE_ID=1235125559
OWNER=49879362
WORKFLOW=".github/workflows/source-transport-fixture.yml"
FIX_HASH="08cab61989bb02cdd19a095923a27a224cb976fe91cfa6fe229ddf8754e26ba5"
MAX=1000000
def must(ok, reason):
    if not ok: raise ValueError(reason)
def digest(x): return hashlib.sha256(x).hexdigest()
def canon(x): return json.dumps(x,separators=(',',':'),sort_keys=True).encode()
def tls(blob):
    u=urllib.parse.urlsplit(blob)
    return u.scheme=="https" and not u.username and not u.password and u.port in (443,None) and (u.hostname or "").endswith(".blob.core.windows.net")
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args): return None
def api(repo, path, token, data=None, *, redirect=False):
    must(repo == PUB and (path=='' or path.startswith('/')) and not path.startswith('//'), "API resource")
    headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
    if token: headers["Authorization"]="Bearer "+token
    if data is not None: headers["Content-Type"]="application/json"
    req=urllib.request.Request(API+repo+path,headers=headers,data=None if data is None else canon(data))
    op=urllib.request.build_opener(NoRedirect())
    try:
        with op.open(req,timeout=12) as res:
            b=res.read(MAX+1); must(len(b)<=MAX,"API bound"); return json.loads(b) if b else None
    except urllib.error.HTTPError as e:
        loc=e.headers.get('Location','')
        if redirect and e.code in (302,307) and tls(loc):
            # Fresh request contains no Authorization; do not follow further redirects.
            with op.open(urllib.request.Request(loc),timeout=12) as res:
                b=res.read(MAX+1); must(len(b)<=MAX,"archive bound"); return b
        raise ValueError("GitHub API HTTP "+str(e.code)) from None
def checked_run(repo, run, sha, tag, workflow_id, title, token, *, complete):
    r=api(repo,"/actions/runs/"+str(run)+"/attempts/1",token)
    must(r["id"]==run and r["run_attempt"]==1 and r["event"]=="workflow_dispatch" and
         r["repository"]["id"]==PUBLIC_ID and r["repository"]["full_name"]=="jsdfhasuh/"+PUB and
         r["head_repository"]["id"]==PUBLIC_ID and r["head_sha"]==sha and r["head_branch"]==tag and
         r["actor"]["id"]==OWNER and r["triggering_actor"]["id"]==OWNER and
         r["workflow_id"]==workflow_id and r["path"]==WORKFLOW and r["display_title"]==title and
         ((r["status"],r["conclusion"])==("completed","success") if complete else r["status"]=="in_progress"),"untrusted run")
    return r
def one_artifact(run,name,sha,member,token):
    a=api(PUB,f"/actions/runs/{run}/artifacts?name={name}&per_page=2",token)
    must(a["total_count"]==1,"artifact count")
    m=a["artifacts"][0]; w=m["workflow_run"]
    must(m["name"]==name and m["expired"] is False and 0<m["size_in_bytes"]<=MAX and
         w["id"]==run and w["repository_id"]==PUBLIC_ID and w["head_sha"]==sha,"artifact binding")
    b=api(PUB,f"/actions/artifacts/{m['id']}/zip",token,redirect=True)
    must("sha256:"+digest(b)==m["digest"], "archive SHA256")
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        items=z.infolist()
        must(len(items)==1 and items[0].filename==member and 0<items[0].file_size<=16384,"artifact member")
        return z.read(items[0])
def config():
    sha=os.environ["APPROVED_SHA"]; tag=os.environ["APPROVED_TAG"]; wid=int(os.environ["APPROVED_WORKFLOW_ID"])
    must(re.fullmatch(r'[0-9a-f]{40}',sha) and re.fullmatch(r'dot-transport-fixture-[a-zA-Z0-9.-]{1,64}',tag) and wid>0,"unreviewed config")
    return sha,tag,wid
def fixture_sha():
    pin=os.environ["REVIEWED_FIXTURE_SHA"]
    must(re.fullmatch("[0-9a-f]{40}",pin),"invalid source commit pin")
    return pin

def binding(nonce,run,sha,tag,wid,cert,platform):
    return dict(v=1,platform=platform,nonce=nonce,run=run,attempt=1,controller=sha,tag=tag,workflow=wid,public_repository=PUBLIC_ID,private_repository=PRIVATE_ID,
                source=fixture_sha(),blob_sha256=FIX_HASH,recipient_sha256=digest(cert))
def ossl(*args):
    p=subprocess.run(["openssl",*map(str,args)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    must(p.returncode==0,"openssl verification refused")
