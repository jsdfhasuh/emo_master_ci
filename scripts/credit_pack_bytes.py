"""Seal four independently bounded suites of actual synthetic Credit PNG bytes."""
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile

ARMS=("trial-0-credit-off","trial-1-credit-on","trial-2-credit-on","trial-3-credit-off")
CAP=8*1024*1024
PNG=b"\x89PNG\r\n\x1a\n"
V2="ba311eeae31312c73f57c9a2cc4c80bbb58380e7c3df956db1d09432b79cca87"
UUID=re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def require(x):
    if not x: raise ValueError("credit actual bytes refused")


def read_json(path,cap):
    with path.open("rb") as f:
        raw=f.read(cap+1)
    require(len(raw)<=cap)
    return json.loads(raw)


def plan(link_root,trial_root):
    links=read_json(link_root/"links.json",64*1024)
    require(links["version"]==1 and links["errors"]==0 and len(links["files"])==96)
    trial=read_json(trial_root/"trial.json",24*1024*1024)
    rows=trial["observed_result_outcomes"]
    require(len(rows)==96 and {r["ordinal"] for r in rows.values()}==set(range(1,97)))
    require(len({r["result_key"] for r in links["files"]})==96
            and len({r["asset"] for r in links["files"]})==96
            and {r["result_key"] for r in links["files"]}==set(rows))
    members=[]
    for row in links["files"]:
        key=row["result_key"]
        result=rows[key]
        image=result["source_outcomes"]["image"]
        require(UUID.fullmatch(key) and UUID.fullmatch(row["asset"]) and row["job"]==trial["job"]
                and result["status"]=="COMPLETE" and image["state"]=="AVAILABLE" and image["image_present"] is True
                and type(row["size"]) is int and 8<=row["size"]<=CAP and re.fullmatch("[a-f0-9]{64}",row["sha256"]))
        members.append((result["ordinal"],link_root/(key+".png"),row))
    require({p.name for p in link_root.iterdir()}=={"links.json",*(p.name for _,p,_ in members)})
    return sorted(members)


class CheckedReader:
    def __init__(self,handle):
        self.handle=handle
        self.sha=sha256()
        self.count=0
    def read(self,n):
        b=self.handle.read(n)
        self.count+=len(b)
        self.sha.update(b)
        return b


def seal_arm(process,plan_rows,identity):
    manifest={**identity,"files":[]}
    with process.stdin as pipe, tarfile.open(fileobj=pipe,mode="w|") as tar:
        for ordinal,path,row in plan_rows:
            size=row["size"]
            original=path.lstat()
            require(stat.S_ISREG(original.st_mode) and not getattr(original,"st_file_attributes",0)&0x400)
            with path.open("rb") as f:
                current=os.fstat(f.fileno())
                require(os.path.samestat(current,original) and current.st_size==size and f.read(8)==PNG)
                f.seek(0)
                member=tarfile.TarInfo(f"{ordinal:03d}.png")
                member.size=size;member.mode=0o600
                reader=CheckedReader(f)
                tar.addfile(member,reader)
                require(reader.count==size and reader.sha.hexdigest()==row["sha256"])
                manifest["files"].append(dict(name=member.name,ordinal=ordinal,**row))
        raw=json.dumps(manifest,sort_keys=True,separators=(",",":")).encode("ascii")
        require(len(raw)<=64*1024)
        member=tarfile.TarInfo("manifest.json")
        member.size=len(raw);member.mode=0o600
        tar.addfile(member,io.BytesIO(raw))


def main():
    env=os.environ
    root=Path(env["RUNNER_TEMP"])
    runner=root/"credit-v2"
    status=read_json(runner/"status.json",65536)
    run,attempt=env["GITHUB_RUN_ID"],env["GITHUB_RUN_ATTEMPT"]
    require(attempt=="1" and status["run"]==run and status["attempt"]==attempt
            and status["product"]==env["SOURCE_SHA"] and status["controller"]==env["GITHUB_WORKFLOW_SHA"]
            and [s.get("rc") for s in status["stages"]]==[0,0,0,0])
    recipient=env["RECIPIENT"]
    require(re.fullmatch(r"age1[023456789ac-hj-np-z]{58}",recipient) and sha256(recipient.encode("ascii")).hexdigest()==V2)
    bytes_root=runner/"scratch"/"credit-bytes"
    raw_root=runner/"scratch"/f"export-credit-{run}-{attempt}"
    arms=[plan(bytes_root/name,raw_root/name) for name in ARMS]
    require(sum(row["size"] for a in arms for _,_,row in a)<=384*CAP)
    outputs=[]
    try:
        for number,rows in enumerate(arms):
            output=root/f"credit-actual-arm-{number}.tar.age"
            require(not output.exists())
            outputs.append(output)
            with subprocess.Popen([str(root/"credit-age.exe"),"-r",recipient,"-o",str(output)],
                                  stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as child:
                try:
                    seal_arm(child,rows,dict(version=1,encryption_profile="V2",
                        scope="credit-original-actual-pngs",group=number,observer=("off","on","on","off")[number],
                        source_sha=env["SOURCE_SHA"],workflow_sha=env["GITHUB_WORKFLOW_SHA"],
                        run=run,attempt=attempt,repository_id=env["GITHUB_REPOSITORY_ID"]))
                    require(child.wait(timeout=90)==0)
                finally:
                    if child.poll() is None:
                        child.kill();child.wait()
            with output.open("rb") as f:
                require(f.readline(64)==b"age-encryption.org/v1\n")
            require(output.stat().st_size<=96*CAP+4*1024*1024)
    except BaseException:
        for output in outputs:output.unlink(missing_ok=True)
        raise
    print("credit_actual_pngs=384; groups=4")


if __name__=="__main__":
    try: main()
    except Exception: raise SystemExit("credit_actual_bytes=refused") from None
