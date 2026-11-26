"""Observe the exact Linux UI timeout, only before original cleanup."""
import functools
import json
import os
from pathlib import Path

import pytest

TARGET = "tests/ui/page_designer/test_dispatch_live_page.py::testLeftUpdatesWhileDetectionIsBlocked[consumer]"


def identifier(value):
    value = getattr(value, "value", value)
    return value if type(value) is str and 0 < len(value) <= 80 and all(c.isalnum() or c in "_-" for c in value) else None


def summarize(result):
    if result is None:
        return None
    return {
        "ordinal": result.identity.resultOrdinal,
        "status": identifier(result.status),
        "sources": [{"id": identifier(s.sourceId), "state": identifier(s.state), "reason_code": identifier(s.reasonCode)}
                    for s in result.sources[:8]],
    }


def capture(locals_, path):
    view = locals_["view"]
    slot = locals_["group"].slots["detection"]
    widget = view.widgets["consumer"]["image"][1]
    scope = view.displayed.get("consumption")
    owner = locals_["runtime"]._presentationOwner
    stored = owner.store.snapshot(slot.jobId)["results"]
    data = {
        "nodeid": TARGET,
        "slot": {"queued": len(slot.queue), "processing": int(bool(slot.active)),
                 "completed": int(slot.completedTotal), "skipped": int(slot.skippedTotal),
                 "failed": int(slot.failedTotal)},
        "stored_count": len(stored),
        "stored": [summarize(r) for r in stored[:8]],
        "rendered": summarize(scope.result) if scope else None,
        "scope_has_image": bool(scope and "image" in scope.images),
        "scope_failure_count": len(scope.failures) if scope else 0,
        "qt_null": widget.image.isNull(),
        "qt_matches_scope": bool(scope and widget.key == scope.result.identity.resultKey),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def wrap(wait, destination):
    @functools.wraps(wait)
    def wrapped(*args, **kwargs):
        try:
            return wait(*args, **kwargs)
        except AssertionError:
            try:
                predicate = args[0] if args else kwargs["predicate"]
                # This uniquely matches the first consumer image wait, not a later wait.
                code = predicate.__code__
                if code.co_freevars == ("ordinal", "view") and "consumption" in code.co_consts and 1 in code.co_consts:
                    import sys
                    capture(sys._getframe(1).f_locals, destination)
            except Exception:
                pass
            raise
    return wrapped


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    dest = os.environ.get("EMO_PRIVATE_LIVE_PAGE_TRACE")
    if not dest or item.nodeid != TARGET:
        yield
        return
    original = item.module.waitFor
    patched = wrap(original, Path(dest))
    item.module.waitFor = patched
    try:
        yield
    finally:
        if item.module.waitFor is patched:
            item.module.waitFor = original
