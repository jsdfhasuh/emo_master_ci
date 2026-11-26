"""Run only pre-reviewed commands from the fixed product workflow; never echo product output."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SOURCE = "533aa64a72fff55f6339cf837114e5ca9255622b"
RECIPE = ".github/workflows/runtime-credit-diagnostics.yml"
# (start line, end line inclusive, shell), exact UTF-8 workflow text after git checkout.
SPANS = [(52, 52, 'pwsh'), (56, 73, 'python'), (78, 80, 'pwsh'), (87, 89, 'pwsh')]
DIGEST = "968647d05cefa54861975f8a84b322e7e64b2a8c42fd679a04324cd422000477"

def steps(text):
    if hashlib.sha256(text.encode()).hexdigest() != DIGEST:
        raise ValueError("recipe_identity")
    lines = text.splitlines()
    return [(shell, "\n".join(line[10:] for line in lines[first-1:last])+"\n"
             if first != last else lines[first-1].split("run: ", 1)[1]+"\n")
            for first,last,shell in SPANS]

def child_environment(parent, root, product):
    keep = {"SYSTEMROOT","WINDIR","SYSTEMDRIVE","COMSPEC","PATHEXT","PATH","USERPROFILE",
            "APPDATA","LOCALAPPDATA","PROGRAMFILES","PROGRAMFILES(X86)","PROGRAMDATA",
            "NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","HOMEDRIVE","HOMEPATH"}
    env = {k:v for k,v in parent.items() if k.upper() in keep}
    env.update(TEMP=str(root), TMP=str(root), RUNNER_TEMP=str(root), GITHUB_WORKSPACE=str(product),
               GITHUB_SHA=SOURCE, GITHUB_RUN_ID=parent["GITHUB_RUN_ID"],
               GITHUB_RUN_ATTEMPT=parent["GITHUB_RUN_ATTEMPT"], QT_QPA_PLATFORM="windows",
               HUARAY_CAMERA_SMOKE="0", PYTHONUNBUFFERED="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env

def main():
    product = Path(sys.argv[1]).resolve()
    controller = Path(__file__).resolve().parents[1]
    requested = json.loads((controller/".github/diagnostic-activation/credit-original-v2.json").read_text(encoding="utf-8"))
    if requested != {"product_sha":SOURCE,"profile":"credit-original-v2"}:
        raise ValueError("activation_identity")
    public_head = subprocess.check_output(["git","-C",str(controller),"rev-parse","HEAD"],text=True).strip()
    if public_head != os.environ["GITHUB_WORKFLOW_SHA_FIXED"]:
        raise ValueError("controller_identity")
    base = Path(os.environ["RUNNER_TEMP"]) / "credit-v2"
    base.mkdir()
    scratch = base / "scratch"
    scratch.mkdir()
    env = child_environment(os.environ,scratch,product)
    if subprocess.check_output(["git","-C",str(product),"rev-parse","HEAD"],text=True).strip()!=SOURCE:
        raise ValueError("product_identity")
    receipt = {"product":SOURCE,"controller":os.environ["GITHUB_WORKFLOW_SHA_FIXED"],
               "run":env["GITHUB_RUN_ID"],"attempt":env["GITHUB_RUN_ATTEMPT"],"stages":[]}
    def save():
        f=base/"status.tmp"; f.write_text(json.dumps(receipt),encoding="ascii"); f.replace(base/"status.json")
    deadline=time.monotonic()+20*60
    for i,(shell,script) in enumerate(steps((product/RECIPE).read_text(encoding="utf-8"))):
        if i < 3 and any(row.get("rc")!=0 for row in receipt["stages"]):
            receipt["stages"].append({"state":"skipped"});save();continue
        if i==3:
            env["ORIGINAL_CONTROL_STEP"]={0:"success",124:"failure",None:"skipped"}.get(receipt["stages"][2].get("rc"),"failure")
        f=base/("recipe."+("py" if shell=="python" else "ps1"))
        f.write_text(script+("\nexit $LASTEXITCODE\n" if i==0 else ""),encoding="utf-8")
        args=[sys.executable,str(f)] if shell=="python" else [shutil.which("pwsh"),"-NoProfile","-NonInteractive","-File",str(f)]
        row={"index":i,"state":"running","start":time.time()};receipt["stages"].append(row);save()
        with (base/("stage-%d.log"%i)).open("xb") as log:
            p=subprocess.Popen(args,cwd=product,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            try: rc=p.wait(timeout=max(0.1, deadline-time.monotonic()) if i<3 else 120)
            except subprocess.TimeoutExpired:
                subprocess.run([str(Path(os.environ["SystemRoot"])/"System32/taskkill.exe"),"/F","/T","/PID",str(p.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=True)
                p.wait(timeout=15);rc=124
        row.update(state="finished",rc=rc,end=time.time());save()
    report=json.loads((scratch/"export-credit-public.json").read_text(encoding="utf-8"))
    if (any(s.get("rc")!=0 for s in receipt["stages"]) or report.get("expected_sha")!=SOURCE
        or report.get("measurement_status")!="VALID" or report.get("observation_status")!="COMPLETE"):
        return 1
    return 0

if __name__=="__main__":
    try: code=main()
    except Exception: code=1
    sys.exit(code)
