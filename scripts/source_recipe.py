"""Run original source checks; retain only bounded local evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

MIB = 1024 * 1024
TRUNCATED = b"[output clipped; last bytes follow]\n"
REPORTS = {
    "ci-results.xml": 16 * MIB,
    "ci-shard.json": 8 * MIB,
    "ci-failures.log": 3 * MIB,
    "two-job-observation.json": MIB,
}


def capture_tail(stream, path, limit=MIB // 2):
    """Drain a pipe continuously without exposing output to the Actions log."""
    tail = bytearray()
    total = 0
    capacity = limit - len(TRUNCATED)
    with stream:
        while chunk := stream.read(64 * 1024):
            total += len(chunk)
            tail.extend(chunk)
            if len(tail) > capacity:
                del tail[:-capacity]
    with path.open("xb") as target:
        if total > capacity:
            target.write(TRUNCATED)
        target.write(tail)


def run_step(name, command, source, env, evidence):
    kwargs = dict(cwd=source, env=env, stdin=subprocess.DEVNULL)
    if evidence is None:
        return subprocess.run(command, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, **kwargs).returncode
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs) as child:
        with ThreadPoolExecutor(max_workers=2) as pool:
            stdout = pool.submit(capture_tail, child.stdout, evidence / f"{name}.stdout.log")
            stderr = pool.submit(capture_tail, child.stderr, evidence / f"{name}.stderr.log")
            status = child.wait()
            stdout.result()
            stderr.result()
    return status


def preserve_reports(source, evidence):
    """Copy only expected regular reports without truncating structured files."""
    reports = {}
    build = source / "build"
    if build.resolve() != build:
        return {name: "unsafe" for name in REPORTS}
    for name, limit in REPORTS.items():
        path = build / name
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or path.resolve() != path:
                reports[name] = "unsafe"
                continue
            if info.st_size > limit:
                reports[name] = "oversize"
                continue
            with path.open("rb") as incoming:
                data = incoming.read(limit + 1)
            if len(data) > limit:
                reports[name] = "oversize"
                continue
            with (evidence / name).open("xb") as target:
                target.write(data)
            reports[name] = "retained"
        except FileNotFoundError:
            reports[name] = "missing"
        except (OSError, RuntimeError):
            reports[name] = "unreadable"
    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("platform", choices=("linux", "windows"))
    parser.add_argument("shard", choices=("runtime", "other"))
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    windows = args.platform == "windows"
    if sys.platform != ("win32" if windows else "linux") or sys.version_info[:2] != (3, 10):
        return 2

    try:
        source = args.source.resolve(strict=True)
        evidence = args.evidence_dir
        if evidence is not None:
            # The trusted workflow supplies a fresh, job-local folder.
            if evidence.exists() and (not evidence.is_dir() or any(evidence.iterdir())):
                return 2
            evidence.mkdir(parents=True, exist_ok=True)
            resolved = evidence.resolve()
            if resolved != evidence.absolute() or resolved.is_relative_to(source):
                return 2
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "ACTIONS_", "RUNNER_"))}
        env["QT_QPA_PLATFORM"] = "windows" if windows else "offscreen"
        steps = [("pip", [sys.executable, "-m", "pip", "install", "-r", "requirements-dev.txt"], {})]
        if windows:
            steps.extend([
                ("desktop", ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                 "$ErrorActionPreference='Stop'; Set-DisplayResolution -Width 1920 -Height 1080 -Force"], {}),
                ("qt", [sys.executable, "-c", "import emo_master; from PySide2.QtWidgets import QApplication; "
                 "a=QApplication([]); g=a.primaryScreen().geometry(); "
                 "assert a.platformName()=='windows' and g.width()>=1920 and g.height()>=1080"],
                 {"PYTHONPATH": str(source / "src")}),
            ])
        steps.append(("checks", [sys.executable, "scripts/ci_check.py", "--shard", args.shard], {}))
        statuses = {}
        for name, command, extra in steps:
            try:
                code = run_step(name, command, source, {**env, **extra}, evidence)
            except (OSError, subprocess.SubprocessError):
                code = 1
            statuses[name] = code
            if code:
                break
        status = int(any(statuses.values()) or not (source / "build" / "ci-shard.json").is_file())
        if evidence is not None:
            reports = preserve_reports(source, evidence)
            if not status and any(reports[name] != "retained" for name in ("ci-results.xml", "ci-shard.json")):
                status = 1
            with (evidence / "status.json").open("x", encoding="utf-8") as target:
                json.dump({"platform": args.platform, "shard": args.shard, "steps": statuses,
                           "reports": reports, "status": status}, target)
        return status
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
