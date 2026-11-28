"""Opt-in pytest plugin for the encrypted staging directory; no extra store reads."""
import json
import os
from pathlib import Path
import pytest
TARGET = "tests/runtime/test_dispatch_queue_integration.py::testWaitingCaptureAndCancellationThroughRealProcesses[slots1-False]"

def field(obj, key):
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return getattr(value, "value", value)

def describe(result):
    return {"status": field(result, "status"), "terminal": field(result, "executionTerminal"),
            "expected": list(result.expectedSourceIds),
            "times_ns": {k: field(result.timing, k) for k in ("captureStartedNs","scopeEndedNs","closedNs")},
            "sources": [{"id": s.sourceId, "state": field(s,"state"), "reason_code": field(s,"reasonCode"),
                         "has_image": field(s,"image") is not None, "has_value": field(s,"valueJson") is not None}
                        for s in result.sources]}

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item, call):
    dest = os.environ.get("EMO_PRIVATE_DISPATCH_TRACE")
    if not dest or item.nodeid != TARGET or call.when != "call" or call.excinfo is None:
        return
    try:
        tb = call.excinfo.value.__traceback__
        data = {"schema": 1, "nodeid": TARGET, "phase": call.when, "duration_s": call.duration}
        while tb is not None:
            if tb.tb_frame.f_code.co_name == "testWaitingCaptureAndCancellationThroughRealProcesses":
                data["line"] = tb.tb_lineno
                result = tb.tb_frame.f_locals.get("result")
                if result is not None:
                    data["result"] = describe(result)
                break
            tb = tb.tb_next
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
        temp.replace(path)
    except Exception:
        # Telemetry must never replace or alter the original pytest result.
        return
