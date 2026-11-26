"""Run only pre-reviewed commands from the fixed product workflow; never echo product output."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SOURCE = "7fccb4988ad0e4abd390110dbb29c80151f5bb3b"
RECIPE = ".github/workflows/runtime-a18-diagnostics.yml"
# (start line, end line inclusive, shell), exact UTF-8 workflow text after git checkout.
SPANS = [(35, 35, 'pwsh'), (39, 40, 'pwsh'), (45, 47, 'pwsh'), (54, 90, 'python'), (96, 99, 'pwsh')]
DIGEST = "0361558c017e43f2f20a40eb6770c96bb85b906370d83b8f40431689968ef545"

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
               GITHUB_RUN_ATTEMPT=parent["GITHUB_RUN_ATTEMPT"], QT_QPA_PLATFORM="offscreen",
               PYTHONUNBUFFERED="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env

def main():
    product = Path(sys.argv[1]).resolve()
    controller = Path(__file__).resolve().parents[1]
    requested = json.loads((controller/".github/diagnostic-activation/a18-original-v2.json").read_text(encoding="utf-8"))
    if requested != {"product_sha":SOURCE,"profile":"a18-original-v2","validation":"outer_pytest_cli_isolation"}:
        raise ValueError("activation_identity")
    public_head = subprocess.check_output(["git","-C",str(controller),"rev-parse","HEAD"],text=True).strip()
    if public_head != os.environ["GITHUB_WORKFLOW_SHA_FIXED"]:
        raise ValueError("controller_identity")
    base = Path(os.environ["RUNNER_TEMP"]) / "a18-v2"
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
    # The same hosted pytest inventory used nearly 70 min in measured full observation.
    deadline=time.monotonic()+103*60
    for i,(shell,script) in enumerate(steps((product/RECIPE).read_text(encoding="utf-8"))):
        if i < 3 and any(row.get("rc")!=0 for row in receipt["stages"]):
            receipt["stages"].append({"state":"skipped"});save();continue
        if i>=3:
            env["ORIGINAL_TEST_STEP"]={0:"success",124:"failure",None:"skipped"}.get(receipt["stages"][2].get("rc"),"failure")
        if i==2:
            env["PYTHONPATH"]=str(controller/"scripts")
            env["EMO_SQLITE_PHASE_JOURNAL"]=str(scratch/"observed-phases.jsonl")
            env["EMO_SQLITE_IMMEDIATE_FAILURES"]="1"
            # Use explicit flags on the pinned outer pytest command only.
            # PYTEST_ADDOPTS leaks into tests that run pytest in separate projects.
            env["EMO_DIAG_JUNIT"] = str(scratch/"observed-junit.xml")
            invocation = "python -m pytest -q "
            if shell != "pwsh" or script.count(invocation) != 1:
                raise ValueError("observed_pytest_invocation")
            script = script.replace(invocation, invocation +
                                    '-p sqlite_phase_journal --junitxml $env:EMO_DIAG_JUNIT ', 1)
        elif i>2:
            for name in ("EMO_DIAG_JUNIT","PYTHONPATH","EMO_SQLITE_PHASE_JOURNAL","EMO_SQLITE_IMMEDIATE_FAILURES"):
                env.pop(name, None)
        f=base/("recipe."+("py" if shell=="python" else "ps1"))
        f.write_text(script+("\nexit $LASTEXITCODE\n" if i==0 else ""),encoding="utf-8")
        args=[sys.executable,str(f)] if shell=="python" else [shutil.which("pwsh"),"-NoProfile","-NonInteractive","-File",str(f)]
        row={"index":i,"state":"running","start":time.time()};receipt["stages"].append(row);save()
        stage_timeout = (600, 60, 90*60, 120, 120)[i]
        with (base/("stage-%d.log"%i)).open("xb") as log:
            p=subprocess.Popen(args,cwd=product,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            try: rc=p.wait(timeout=min(stage_timeout, max(0.1, deadline-time.monotonic())) if i<3 else stage_timeout)
            except subprocess.TimeoutExpired:
                subprocess.run([str(Path(os.environ["SystemRoot"])/"System32/taskkill.exe"),"/F","/T","/PID",str(p.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=False)
                if p.poll() is None:
                    p.kill()
                p.wait(timeout=15);rc=124
        row.update(state="finished",rc=rc,end=time.time());save()
    if any(stage.get("rc")!=0 for stage in receipt["stages"]):
        return 1
    if not (scratch/"observed-junit.xml").is_file():
        return 1
    return 0

if __name__=="__main__":
    try: code=main()
    except Exception: code=1
    sys.exit(code)

