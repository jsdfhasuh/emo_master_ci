"""Seal only the cold-start diagnostic allowlist."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile


def require(ok):
    if not ok:raise ValueError("cold-arm encryption refused")


def main():
    e=os.environ
    recipient=e["RECIPIENT"]
    require(re.fullmatch(r"age1[023456789ac-hj-np-z]{58}",recipient)
            and hashlib.sha256(recipient.encode("ascii")).hexdigest()=="ba311eeae31312c73f57c9a2cc4c80bbb58380e7c3df956db1d09432b79cca87")
    temp=Path(e["RUNNER_TEMP"])
    root=temp/"cold-credit"
    entries={
        "cold-arm-summary.json":(root/"cold-arm-summary.json",16*1024),
        "startup-readiness-detail.json":(root/"detail/startup-readiness-detail.json",16*1024),
        "hosted-guard.json":(root/"original-control/hosted-guard.json",16*1024),
        "process.log":(root/"original-control/trial-0-credit-off/process.log",4*1024**2),
        "cold-launcher.log":(temp/"cold-launcher.log",128*1024),
        "package-setup.log":(temp/"cold-pip.log",1024*1024),
    }
    payload={}
    for name,(path,cap) in entries.items():
        try:st=path.lstat()
        except FileNotFoundError:continue
        require(stat.S_ISREG(st.st_mode) and not getattr(st,"st_file_attributes",0)&0x400
                and st.st_nlink==1 and 0<=st.st_size<=cap)
        with path.open("rb") as f:
            require(os.path.samestat(st,os.fstat(f.fileno())))
            raw=f.read(cap+1)
        require(len(raw)==st.st_size)
        payload[name]=raw
    require(payload)
    if e["WORKLOAD_OUTCOME"]=="success":
        require(all(name in payload for name in ("cold-arm-summary.json","startup-readiness-detail.json","hosted-guard.json")))
    pins={"version":1,"profile":"V2","role":"credit_group0_cold_start_diagnostic_only","group":0,
          "source_sha":e["SOURCE_SHA"],"workflow_sha":e["GITHUB_WORKFLOW_SHA"],"run":e["GITHUB_RUN_ID"],
          "attempt":e["GITHUB_RUN_ATTEMPT"],"repository_id":e["GITHUB_REPOSITORY_ID"],
          "outcome":e["WORKLOAD_OUTCOME"],"formal_credit_acceptance":False,"files":{
              name:{"size":len(raw),"sha256":hashlib.sha256(raw).hexdigest()} for name,raw in payload.items()}}
    payload["manifest.json"]=json.dumps(pins,sort_keys=True,separators=(",",":")).encode("ascii")
    out=temp/"cold-credit-arm0.tar.age"
    try:
        with subprocess.Popen([str(temp/"credit-age.exe"),"-r",recipient,"-o",str(out)],stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as p:
            with p.stdin as pipe,tarfile.open(fileobj=pipe,mode="w|") as tar:
                for name,raw in sorted(payload.items()):
                    member=tarfile.TarInfo(name);member.size=len(raw);member.mode=0o600
                    tar.addfile(member,io.BytesIO(raw))
            require(p.wait(timeout=60)==0)
        with out.open("rb") as file:require(file.readline(64)==b"age-encryption.org/v1\n")
    except BaseException:
        out.unlink(missing_ok=True)
        raise


if __name__=="__main__":
    try:main()
    except Exception:raise SystemExit("credit_cold_seal=refused") from None
