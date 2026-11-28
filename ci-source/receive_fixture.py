import sys,time
from fixture_common import *
def main():
    sha,tag,wid=config(); nonce=os.environ["NONCE"]; run=int(os.environ["GITHUB_RUN_ID"]); d=Path(os.environ["RUNNER_TEMP"])/"source-fixture"
    must(re.fullmatch("[0-9a-f]{32}",nonce) and os.environ["GITHUB_SHA"]==sha and os.environ["GITHUB_REF"]=="refs/tags/"+tag and os.environ["GITHUB_RUN_ATTEMPT"]=="1","run binding")
    if sys.argv[1]=="relay":
        sealed=base64.b64decode(os.environ["SEALED"],validate=True); must(128<=len(sealed)<=8192,"sealed size")
        d.mkdir(mode=0o700); (d/"sealed.der").write_bytes(sealed); return
    if sys.argv[1]=="key":
        must(not os.environ.get("SEALED"),"request shape"); d.mkdir(mode=0o700)
        ossl("req","-x509","-newkey","rsa:3072","-nodes","-days","1","-subj","/CN=fixture","-keyout",d/"one-use.key","-out",d/"recipient.pem")
        (d/"one-use.key").chmod(0o600); return
    token=os.environ.pop("PUBLIC_READ_TOKEN"); title="source-fixture relay "+nonce
    for _ in range(65):
        qs=urllib.parse.urlencode({"event":"workflow_dispatch","head_sha":sha,"per_page":100})
        out=api(PUB,f"/actions/workflows/{wid}/runs?{qs}",token)
        must(out["total_count"]<=100,"run lookup ambiguous; reconcile offline")
        matches=[r for r in out["workflow_runs"] if r["display_title"]==title]
        must(len(matches)<=1,"multiple courier runs")
        if matches and matches[0]["status"]=="completed":
            rid=matches[0]["id"];checked_run(PUB,rid,sha,tag,wid,title,token,complete=True);break
        time.sleep(6)
    else: raise ValueError("no confirmed response")
    sealed=one_artifact(rid,"sealed-"+nonce,sha,"sealed.der",token); (d/"sealed.der").write_bytes(sealed)
    ossl("cms","-decrypt","-binary","-inform","DER","-in",d/"sealed.der","-recip",d/"recipient.pem","-inkey",d/"one-use.key","-out",d/"opened.tmp")
    obj=json.loads((d/"opened.tmp").read_bytes())
    must(obj["binding"]==binding(nonce,run,sha,tag,wid,(d/"recipient.pem").read_bytes()),"wrong request")
    fixture=base64.b64decode(obj["fixture"],validate=True);must(digest(fixture)==FIX_HASH,"fixture SHA")
    challenge=obj["challenge"]; must(re.fullmatch("[0-9a-f]{64}",challenge),"challenge shape")
    (d/"proof.json").write_bytes(canon({"binding":obj["binding"],"challenge_sha256":digest(bytes.fromhex(challenge))}))
    print("private_fixture_received=true sha256="+FIX_HASH+" courier_run="+str(rid))
if __name__=="__main__": main()
