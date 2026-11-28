"""Opt-in pytest plugin for the encrypted staging directory; no extra store reads."""
import json
import linecache
import os
from pathlib import Path
import pytest
TARGET = "tests/runtime/test_dispatch_queue_integration.py::testWaitingCaptureAndCancellationThroughRealProcesses[slots1-False]"

def field(obj, key):
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return getattr(value, "value", value)

def code(value):
    return value if isinstance(value, str) and len(value) <= 48 and value.isascii() and value.replace("_", "").isalnum() and value.isupper() else None


def describe(result):
    expected = list(result.expectedSourceIds)
    sources = list(result.sources)
    return {"status": code(field(result, "status")), "terminal": code(field(result, "executionTerminal")),
            "expected_count": len(expected), "source_count": len(sources),
            "times_ns": {k: field(result.timing, k) for k in ("captureStartedNs", "scopeEndedNs", "closedNs")},
            "sources": [{"expected_index": expected.index(s.sourceId) if s.sourceId in expected else None,
                         "state": code(field(s, "state")), "reason_code": code(field(s, "reasonCode")),
                         "has_image": field(s, "image") is not None, "has_value": field(s, "valueJson") is not None}
                        for s in sources[:32]]}


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item, call):
    dest = os.environ.get("EMO_PRIVATE_DISPATCH_TRACE")
    if not dest or item.nodeid != TARGET or call.when != "call" or call.excinfo is None:
        return
    try:
        tb = call.excinfo.value.__traceback__
        while tb is not None:
            frame = tb.tb_frame
            if frame.f_code.co_name == "testWaitingCaptureAndCancellationThroughRealProcesses":
                if 'assert result.status == "COMPLETE"' not in linecache.getline(frame.f_code.co_filename, tb.tb_lineno):
                    return
                result = frame.f_locals.get("result")
                if result is None:
                    return
                data = {"schema": 1, "nodeid": TARGET, "phase": call.when, "duration_s": call.duration,
                        "line": tb.tb_lineno, "result": describe(result)}
                path = Path(dest)
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(path.suffix + ".tmp")
                encoded = json.dumps(data, allow_nan=False).encode("ascii")
                if len(encoded) > 16 * 1024:
                    return
                with temp.open("xb") as handle:
                    handle.write(encoded)
                temp.replace(path)
                return
            tb = tb.tb_next
    except Exception:
        pass
