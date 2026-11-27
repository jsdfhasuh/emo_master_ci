"""One original group-0 child and supervisor; diagnostic-only, no full Credit verdict."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def require(ok):
    if not ok:
        raise ValueError("cold-arm identity mismatch")


def check_command(command):
    require("--count" in command and command[command.index("--count")+1]=="96" and
            "--warmup" in command and command[command.index("--warmup")+1]=="8" and
            "--arm" in command and command[command.index("--arm")+1]=="none_qt" and
            "--qt-platform" in command and command[command.index("--qt-platform")+1]=="windows" and
            "--startup-barrier" in command and "--asset-split-trace" in command and
            "--asset-file-subphases" in command and "--hub-tick-trace" not in command and
            "--export-credit-trace" not in command and "--capture-credit-trace" not in command)


def summary(directory, watch, expected):
    out={"role":"credit_group0_cold_start_diagnostic_only","group":0,"observer":"off",
         "config":{"count":96,"warmup":8,"startup_seconds":10,"watchdog_seconds":90,"qt":"windows"},
         "watchdog":{k:watch[k] for k in ("status","exit_code","timeout","log_overflow","log_bytes",
                     "owner_retirement_verified","watchdog_seconds","log_sha256")},
         "trial_payload_present":False,"formal_credit_acceptance":False}
    p=directory/"trial.json"
    if p.is_file():
        with p.open("rb") as f:raw=f.read(24*1024**2+1)
        require(len(raw)<=24*1024**2)
        data=json.loads(raw)
        indices=[row["index"] for row in data["pace"]]
        require(len(indices)<=96 and all(type(i) is int and 1<=i<=96 for i in indices))
        out.update(trial_payload_present=True,pace_count=len(indices),
                   pace_starts_at_one=bool(indices) and indices[0]==1,
                   pace_exact_reset_sequence=indices==list(range(1,97)),
                   exact_ordinal_coverage=expected(data))
    return out


def main():
    require(sys.platform=="win32" and sys.version_info[:2]==(3,10))
    e=os.environ
    product=Path.cwd().resolve()
    source=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    require(source==e["SOURCE_SHA"])
    recipe=(product/".github/workflows/runtime-credit-diagnostics.yml").read_bytes()
    require(hashlib.sha256(recipe.replace(b"\r\n",b"\n")).hexdigest()==
            "968647d05cefa54861975f8a84b322e7e64b2a8c42fd679a04324cd422000477")
    root=Path(e["RUNNER_TEMP"])/"cold-credit"
    root.mkdir()
    detail=root/"detail";detail.mkdir()
    reten=root/"retained";reten.mkdir()
    public_source_env={"EMO_CREDIT_ASSET_FILE_SUBPHASES":"1","EMO_CREDIT_STARTUP_DETAIL":"1",
                       "EMO_CREDIT_STARTUP_DETAIL_DIRECTORY":str(detail),
                       "EMO_CREDIT_RETAIN_BYTES":str(reten),"QT_QPA_PLATFORM":"windows",
                       "HUARAY_CAMERA_SMOKE":"0","PYTHONUNBUFFERED":"1"}
    # App subprocess environment follows the original recipe's smallest
    # allowlist. This worker executes only public product source.
    keep={"SYSTEMROOT","WINDIR","SYSTEMDRIVE","COMSPEC","PATHEXT","PATH","USERPROFILE","APPDATA",
          "LOCALAPPDATA","PROGRAMFILES","PROGRAMFILES(X86)","PROGRAMDATA","NUMBER_OF_PROCESSORS",
          "PROCESSOR_ARCHITECTURE","HOMEDRIVE","HOMEPATH","RUNNER_TEMP","GITHUB_RUN_ID","GITHUB_RUN_ATTEMPT"}
    env={k:v for k,v in os.environ.items() if k.upper() in keep}
    env.update(public_source_env)
    env.update(TEMP=str(root),TMP=str(root),GITHUB_SHA=source,GITHUB_WORKSPACE=str(product))
    os.environ.clear();os.environ.update(env)
    sys.path[:0]=[str(product/"src"),str(product),str(product/"scripts")]
    from scripts import r3_export_credit_control as credit
    from scripts.r3_hosted_credit_guard import execute
    require(credit.COUNT==96 and credit.WARMUP==8 and credit.ORDER[0]=="off" and credit.policy.STARTUP_SECONDS==10)

    def cold(output):
        output.mkdir(exist_ok=False)
        arm=output/"trial-0-credit-off"
        arm.mkdir()
        credit.policy.base.diskPreflight(arm)
        command=credit.childCommand(arm,"windows","off",hubTrace=False,fileSubphases=True)
        check_command(command)
        watcher=credit.policy.base.supervisedTrial(command,arm)
        require(watcher["watchdog_seconds"]==90)
        report=summary(arm,watcher,credit.policy.exactCoverage)
        with (root/"cold-arm-summary.json").open("x",encoding="ascii") as file:
            json.dump(report,file,sort_keys=True)
        # Preserve failure even though encryption runs afterwards.
        returncode=0 if watcher["status"]=="PASS" and report.get("exact_ordinal_coverage") is True else 1
        if returncode:raise SystemExit(returncode)

    return execute(root/"original-control",control=cold)


if __name__=="__main__":
    try:sys.exit(main())
    except Exception:sys.exit(1)
