"""Extract executable Web/Runtime steps from the reviewed product workflow."""
from hashlib import sha1
from pathlib import Path
import subprocess

import yaml

WORKFLOW = Path(".github/workflows/web-panel-ci.yml")
PRODUCT_SHA = "5b08d7455b665ba1ac83f46890c83194bc92014f"
WORKFLOW_BLOB = "ef1c2ee03cc391475816d5309ad44a5b12cf6448"
PROFILES = {
    "web-panel": (["ubuntu-latest", "windows-latest"], 23),
    "product-runtime": (["windows-latest"], 7),
}


def load_recipe(product):
    git = ["git", "-C", str(product)]
    def read(*args):
        result = subprocess.run([*git, *args], capture_output=True, check=False)
        if result.returncode:
            raise ValueError("product Git identity unavailable")
        return result.stdout
    if read("rev-parse", "HEAD").strip().decode("ascii") != PRODUCT_SHA:
        raise ValueError("unexpected product SHA")
    raw = read("show", f"HEAD:{WORKFLOW.as_posix()}")
    header = f"blob {len(raw)}\0".encode()
    if sha1(header + raw).hexdigest() != WORKFLOW_BLOB:
        raise ValueError("unreviewed product Web workflow")
    return parse_recipe(raw)


def parse_recipe(raw):
    result = {}
    workflow = yaml.safe_load(raw)
    for job, (platforms, count) in PROFILES.items():
        selected = workflow["jobs"][job]
        defaults = selected.get("defaults", {}).get("run", {})
        steps = []
        for step in selected["steps"]:
            if "run" not in step or step["name"] == "Report Web test coverage":
                continue
            if step.keys() - {"name", "run", "shell", "if"}:
                raise ValueError("unsupported Web step directives")
            condition = step.get("if")
            if condition not in {None, "env.FULL_WEB_LOGIC == 'true'", "env.FULL_WEB_LOGIC == 'false'"}:
                raise ValueError("unsupported Web step condition")
            steps.append({
                "id": len(steps) + 1,
                "name": step["name"], "run": step["run"],
                "shell": step.get("shell", defaults.get("shell", "pwsh")),
                "full_only": condition == "env.FULL_WEB_LOGIC == 'true'",
                "subset_only": condition == "env.FULL_WEB_LOGIC == 'false'",
            })
        if len(steps) != count:
            raise ValueError("Web step inventory changed")
        result[job] = {
            "platforms": platforms, "steps": steps,
            "cwd": defaults.get("working-directory", "."),
            "env": {k: str(v) for k, v in selected.get("env", {}).items() if k != "FULL_WEB_LOGIC"},
        }
    return {"jobs": result}
