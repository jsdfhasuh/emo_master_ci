"""Opt-in pytest phase journal for encrypted SQLite observer evidence."""
import json
import os
import time
from pathlib import Path

import pytest

MAX_BYTES = 64 * 1024 * 1024
MAX_ROW_BYTES = 64 * 1024


class PhaseJournal:
    def __init__(self, path):
        self.stream = Path(path).open("xb", buffering=0)
        self.count = self.size = 0
        self.write("session_start")

    def write(self, event, **fields):
        row = {
            "v": 1,
            "seq": self.count + 1,
            "event": event,
            "utc_ns": time.time_ns(),
            "monotonic_ns": time.monotonic_ns(),
            **fields,
        }
        data = (json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(data) > MAX_ROW_BYTES or self.size + len(data) > MAX_BYTES:
            raise RuntimeError("SQLite phase journal exceeds evidence quota")
        if self.stream.write(data) != len(data):
            raise OSError("incomplete SQLite phase journal write")
        self.count += 1
        self.size += len(data)

    def phase(self, item, phase):
        fields = {"nodeid": item.nodeid, "phase": phase}
        self.write("start", **fields)
        try:
            yield
        finally:
            self.write("end", **fields)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_setup(self, item):
        yield from self.phase(item, "setup")

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_call(self, item):
        yield from self.phase(item, "call")

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item):
        yield from self.phase(item, "teardown")

    def pytest_runtest_logreport(self, report):
        self.write("report", nodeid=report.nodeid, phase=report.when, outcome=report.outcome)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        result = yield
        if result.excinfo is None:
            self.write("session_finish", exitstatus=int(exitstatus))

    def pytest_unconfigure(self, config):
        self.stream.close()


def pytest_configure(config):
    path = os.environ.get("EMO_SQLITE_PHASE_JOURNAL")
    if not path:
        raise RuntimeError("SQLite phase journal path not configured")
    journal = PhaseJournal(path)
    config.pluginmanager.register(journal, "sqlite-phase-journal-instance")
