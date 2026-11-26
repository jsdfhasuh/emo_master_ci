"""Private V2 staging only; read the active exporter once on the exact failure."""
import json
import os
from pathlib import Path
import linecache

import pytest

NAME = "testQtAndWebEquivalentImagesCaptureOnceAndKeepIndependentResultOwnership"
TARGET = "tests/runtime/presentation/test_equivalent_image_capture.py::" + NAME
NUMBERS = ("slot", "lane", "captureAcquiredNs", "submittedNs", "deadline",
           "startupStartedNs", "startupReadyNs", "startupReapedNs",
           "dispatchNs", "snapshotwaitStartedNs", "snapshotwaitEndedNs",
           "snapshotremainingMs", "snapshotReplyNs", "waitStartedNs", "waitEndedNs",
           "remainingMs", "replyNs", "laneReleasedNs", "reapStartedNs", "reapedNs",
           "callbackStartedNs", "callbackEndedNs", "retirementEndedNs")
LABELS = ("stage", "ownerPhase", "outcome", "startupPhase", "startupErrorType",
          "laneReleaseProof", "errorType", "callbackErrorType", "reapErrorType")


def row(raw):
    if raw is None:
        return None
    result = {k: raw[k] for k in (*NUMBERS, "laneReleased") if type(raw.get(k)) in (int, float, bool)}
    result.update({k: raw[k] for k in LABELS if isinstance(raw.get(k), str)
                   and len(raw[k]) <= 80 and raw[k].replace("_", "").isalnum()})
    return result


def summarize(pool, job):
    snapshot = pool.ownershipSnapshot(job)
    return {"clock": "host_monotonic", "observed_ns": snapshot["observedNs"],
            "stats": {k: pool.stats[k] for k in ("completed", "timed_out", "reaped", "failed")
                      if type(pool.stats.get(k)) is int},
            "slots": [{"slot": s.get("slot"), "lock_busy": s.get("unknown") == "owner_lock_busy",
                       "busy": bool(s.get("busy")), "quarantined": bool(s.get("quarantined")),
                       "active": row(s.get("active")),
                       "pending": [row(r) for r in s.get("pendingRaw", [])[:2]]}
                      for s in snapshot["slots"]],
            "recent_retirements": [row(r) for r in snapshot["recentRetirements"][-4:]]}


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item, call):
    dest = os.environ.get("EMO_PRIVATE_CAPTURE_OWNER_TRACE")
    if not dest or item.nodeid != TARGET or call.when != "call" or call.excinfo is None:
        return
    try:
        trace = call.excinfo.value.__traceback__
        while trace is not None:
            frame = trace.tb_frame
            if frame.f_code.co_name == NAME and "frames" in frame.f_locals:
                if "all(frame.status" not in linecache.getline(frame.f_code.co_filename, trace.tb_lineno):
                    return
                values = frame.f_locals
                payload = summarize(values["channel"].exporter, values["job"])
                payload.update(schema=1, nodeid=TARGET, line=trace.tb_lineno)
                path = Path(dest)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
                tmp.replace(path)
                return
            trace = trace.tb_next
    except Exception:
        pass
