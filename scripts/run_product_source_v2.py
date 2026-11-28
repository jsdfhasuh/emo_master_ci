"""Execute the exact Source CI shard; only bounded local diagnostics escape."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

PRODUCT = "ca57a5641686446360034b8f49cd31286c0a1e2a"
DISPLAY = """import json
import emo_master
from PySide2.QtWidgets import QApplication
app = QApplication([])
screen = app.primaryScreen()
geometry = screen.geometry()
print(json.dumps({"platform": app.platformName(),
    "geometry": geometry.getRect(),
    "available": screen.availableGeometry().getRect(),
    "scale": screen.devicePixelRatio()}), flush=True)
assert app.platformName() == "windows"
assert geometry.width() >= 1920 and geometry.height() >= 1080
"""
LOG_CAP = 512 * 1024


def checked_source_sha(source):
    """Bind the executed checkout to the approved workflow input, or the legacy pin."""
    expected = os.environ.get("EXPECTED_SOURCE_SHA", PRODUCT)
    if not re.fullmatch(r"[0-9a-f]{40}", expected) or expected == "0" * 40:
        raise ValueError("invalid Source pin")
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True,
                                     stderr=subprocess.DEVNULL).strip()
    if actual != expected:
        raise ValueError("checked-out Source revision does not match the pin")
    return actual


def commands(platform, shard, source):
    windows = platform == "windows"
    result = [("dependencies", [sys.executable, "-m", "pip", "install", "-r", "requirements-dev.txt"], {})]
    if windows:
        result.extend([
            ("display", ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                         "$ErrorActionPreference='Stop'; Set-DisplayResolution -Width 1920 -Height 1080 -Force"], {}),
            ("verify-display", [sys.executable, "-c", DISPLAY], {"PYTHONPATH": str(source / "src")}),
        ])
    result.append(("source", [sys.executable, "scripts/ci_check.py", "--shard", shard], {}))
    return result


def drain(stream, target):
    marker = b"[leading bytes omitted]\n"
    tail, total = bytearray(), 0
    with stream:
        while chunk := stream.read(64 * 1024):
            total += len(chunk)
            tail.extend(chunk)
            if len(tail) > LOG_CAP:
                del tail[:-LOG_CAP]
    data = marker + tail[len(marker):] if total > LOG_CAP else tail
    target.write_bytes(data)


def quiet_run(args, *, source, env, output, deadline, windows):
    timeout = max(.01, deadline - time.monotonic())
    with subprocess.Popen(args, cwd=source, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, start_new_session=not windows) as child:
        with ThreadPoolExecutor(max_workers=1) as reads:
            future = reads.submit(drain, child.stdout, output)
            try:
                status = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if windows:
                    subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                                    "/PID", str(child.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
                else:
                    os.killpg(child.pid, signal.SIGKILL)
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
                status = 124
            future.result()
    return status


def main(source, raw, platform, shard):
    windows = platform == "windows"
    raw.mkdir(parents=True, exist_ok=False)
    stage, status = "identity", 1
    try:
        if (platform not in ("linux", "windows") or shard not in ("runtime", "other")
                or sys.platform != ("win32" if windows else "linux") or sys.version_info[:2] != (3, 10)):
            raise ValueError
        checked_source_sha(source)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "ACTIONS_", "RUNNER_"))}
        env["QT_QPA_PLATFORM"] = "windows" if windows else "offscreen"
        deadline = time.monotonic() + (90 if windows else 60) * 60
        for stage, args, extra in commands(platform, shard, source):
            status = quiet_run(args, source=source, env={**env, **extra}, output=raw / (stage + ".log"),
                               deadline=deadline, windows=windows)
            if status:
                break
    except (ValueError, OSError, subprocess.SubprocessError):
        status = 1
    (raw / "stage-report.json").write_text(json.dumps(dict(stage=stage, exitcode=status)), encoding="ascii")
    print("source_v2=" + ("success" if status == 0 else "timeout" if status == 124 else "failure"))
    return int(status != 0)


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]), sys.argv[3], sys.argv[4]))
