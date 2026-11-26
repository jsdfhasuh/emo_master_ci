"""Opt-in, bounded numeric trace for the original Windows viewport test."""
import functools
import json
import os
import time
from pathlib import Path

import pytest

NODE = (
    "tests/ui/page_designer/test_canvas_viewport.py"
    "::testManualViewSurvivesRefreshAndFitRestoresAutomaticMode"
)
STATE = {"writes": 0, "missing": 0}
LIMIT = 256


def sample(view, label, when):
    if STATE["writes"] >= LIMIT:
        return
    try:
        if view.objectName() != "pageCanvas":
            return
        w = view.viewport()
        rect = view.sceneRect()
        center = view._viewportCenter()
        sx, sy = view.horizontalScrollBar(), view.verticalScrollBar()
        data = {
            "method": label, "when": when, "monotonic_ns": time.monotonic_ns(),
            "vp": [w.width(), w.height()],
            "center": [center.x(), center.y()],
            "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
            "ranges": [[s.minimum(), s.maximum(), s.value()] for s in (sx, sy)],
            "dpr": w.devicePixelRatioF(), "zoom": view.getZoomFactor(),
            "autofit": bool(getattr(view, "autoFit", False)),
        }
        fp = Path(os.environ["EMO_CANVAS_RESIZE_TRACE"])
        with fp.open("a", encoding="ascii") as out:
            out.write(json.dumps(data, ensure_ascii=True, allow_nan=False) + "\n")
        STATE["writes"] += 1
    except Exception:
        # Observation cannot change the result or swallow an original exception.
        STATE["missing"] += 1


def wrap(cls, method, label):
    original = cls.__dict__[method]

    @functools.wraps(original)
    def observer(self, *args, **kwargs):
        sample(self, label, "enter")
        try:
            return original(self, *args, **kwargs)
        finally:
            sample(self, label, "exit")

    setattr(cls, method, observer)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if item.nodeid != NODE:
        return
    from emo_master.apps.designer.page_designer.page_canvas import PageCanvas
    from emo_master.apps.designer.ui.designer_graphics_view import DesignerGraphicsView

    wrap(DesignerGraphicsView, "resizeEvent", "native_resize_path")
    wrap(DesignerGraphicsView, "_ensureNavigationBounds", "navigation_bounds")
    wrap(PageCanvas, "updatePageSize", "deferred_page_size")


def pytest_sessionfinish(session, exitstatus):
    fp = Path(os.environ["EMO_CANVAS_RESIZE_TRACE"]).with_suffix(".meta.json")
    fp.write_text(json.dumps(STATE, sort_keys=True), encoding="ascii")
