"""Smoke-test the evidence hook against a synthetic fixture, with no product code."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CASE = """import os
import time
import pytest

@pytest.fixture
def resource():
    yield
    if os.environ["SCENARIO"] == "teardown":
        os._exit(43)

def test_fixture(resource):
    scenario = os.environ["SCENARIO"]
    if scenario == "fail":
        assert False
    if scenario == "exit":
        os._exit(42)
    if scenario == "timeout":
        time.sleep(120)
"""


def require(condition):
    if not condition:
        raise RuntimeError("phase journal smoke contract failed")


def read(path):
    return [json.loads(row) for row in path.read_text(encoding="ascii").splitlines()]


def main():
    workspace = Path(os.environ["RUNNER_TEMP"]) / "sqlite-journal-fixtures"
    workspace.mkdir()
    (workspace / "test_case.py").write_text(CASE, encoding="ascii")
    plugin_dir = Path(__file__).resolve().parent
    for scenario, exitcode in (("pass", 0), ("fail", 1), ("exit", 42),
                               ("teardown", 43), ("timeout", None)):
        path = workspace / f"{scenario}.jsonl"
        with (workspace / f"{scenario}.log").open("xb") as log:
            child = subprocess.Popen(
                [sys.executable, "-m", "pytest", "-q", "-p", "sqlite_phase_journal",
                 "test_case.py"],
                cwd=workspace, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "EMO_SQLITE_PHASE_JOURNAL": str(path),
                     "PYTHONPATH": os.pathsep.join(filter(None, (str(plugin_dir), os.environ.get("PYTHONPATH")))),
                     "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "SCENARIO": scenario},
            )
            try:
                if exitcode is None:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        if child.poll() is not None:
                            break
                        if path.is_file() and any(
                            b'"event":"start"' in line and b'"phase":"call"' in line
                            for line in path.read_bytes().splitlines() if line.endswith(b"}")
                        ):
                            child.kill()
                            child.wait(timeout=10)
                            break
                        time.sleep(0.05)
                    else:
                        raise RuntimeError("did not reach before-kill checkpoint")
                    require(child.returncode not in (0, None))
                else:
                    require(child.wait(timeout=20) == exitcode)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
        records = read(path)
        require([row["seq"] for row in records] == list(range(1, len(records) + 1)))
        require(all(row["v"] == 1 and row["utc_ns"] > 0 for row in records))
        stamps = [row["monotonic_ns"] for row in records]
        require(stamps == sorted(stamps))
        require(all(row.get("nodeid", "test_case.py::test_fixture") ==
                    "test_case.py::test_fixture" for row in records))
        observed = [(row["phase"], row["event"]) for row in records if "phase" in row]
        expected = [(phase, event) for phase in ("setup", "call", "teardown")
                    for event in ("start", "end", "report")]
        if scenario in ("pass", "fail"):
            require(observed == expected)
            require(records[-1]["event"] == "session_finish")
            require(records[-1]["exitstatus"] == exitcode)
            require([row["outcome"] for row in records if row["event"] == "report"] ==
                    ["passed", "passed" if scenario == "pass" else "failed", "passed"])
        else:
            require(observed == expected[:7 if scenario == "teardown" else 4])
            require(records[-1]["event"] == "start")
    print("sqlite_phase_journal_smoke=5/5")


if __name__ == "__main__":
    main()
