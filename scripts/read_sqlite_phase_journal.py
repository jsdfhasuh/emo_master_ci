"""Analyze a decrypted SQLite phase journal. Use only in a private environment."""
import argparse
import collections
import json
from pathlib import Path


def analyze(data):
    truncated = bool(data and not data.endswith(b"\n"))
    lines = data.split(b"\n")[:-1]
    if not lines:
        raise ValueError("missing session start")
    open_phases = {}
    awaiting_reports = {}
    failures = []
    cumulative = collections.Counter()
    modules = collections.Counter()
    phases = collections.Counter()
    outcomes = collections.Counter()
    finish = None
    last = None
    last_stamp = None
    session_started = False
    for seq, line in enumerate(lines, 1):
        row = json.loads(line)
        stamp = row["monotonic_ns"]
        if (row["v"] != 1 or row["seq"] != seq or not isinstance(stamp, int) or row["utc_ns"] <= 0
                or (last_stamp is not None and stamp < last_stamp) or finish is not None):
            raise ValueError("invalid sequence or timestamp")
        last_stamp = stamp
        event = row["event"]
        if event == "session_start":
            if seq != 1:
                raise ValueError("misplaced session start")
            session_started = True
            continue
        if not session_started:
            raise ValueError("missing session start")
        if event == "session_finish":
            if open_phases or awaiting_reports:
                raise ValueError("finish with unmatched phase or report")
            finish = row["exitstatus"]
            continue
        node, phase = row["nodeid"], row["phase"]
        if phase not in ("setup", "call", "teardown") or not isinstance(node, str) or not node:
            raise ValueError("invalid phase")
        key = node, phase
        if event == "start":
            if open_phases or awaiting_reports:
                raise ValueError("concurrent or unmatched phase")
            open_phases[key] = (stamp, row["utc_ns"])
        elif event == "end":
            started, _ = open_phases.pop(key)
            duration = stamp - started
            cumulative[node] += duration
            modules[node.partition("::")[0]] += duration
            phases[phase] += duration
            awaiting_reports[key] = duration
        elif event == "report":
            outcome = row["outcome"]
            if outcome not in ("passed", "failed", "skipped"):
                raise ValueError("invalid phase outcome")
            duration = awaiting_reports.pop(key)
            outcomes[(phase, outcome)] += 1
            if outcome == "failed":
                failures.append({"nodeid": node, "phase": phase, "duration_ns": duration})
        else:
            raise ValueError("unknown journal event")
        last = {"nodeid": node, "phase": phase, "event": event}
    return {
        "records": len(lines),
        "incomplete_final_record": truncated,
        "session_exit": finish,
        "last_phase_event": last,
        "active_phases": [{"nodeid": node, "phase": phase, "started_utc_ns": utc}
                          for (node, phase), (_, utc) in open_phases.items()],
        "awaiting_report": [{"nodeid": node, "phase": phase, "duration_ns": duration}
                            for (node, phase), duration in awaiting_reports.items()],
        "last_failure": failures[-1] if failures else None,
        "outcomes_by_phase": {f"{phase}:{outcome}": count for (phase, outcome), count in outcomes.items()},
        "slowest_50_completed_nodeids_ns": cumulative.most_common(50),
        "module_completed_phase_totals_ns": modules.most_common(),
        "completed_phase_totals_ns": dict(phases),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("journal", type=Path)
    p.add_argument("private_output", type=Path)
    args = p.parse_args()
    with args.journal.open("rb") as handle:
        data = handle.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("journal exceeds evidence quota")
    with args.private_output.open("x", encoding="utf-8") as dest:
        dest.write(json.dumps(analyze(data), indent=2) + "\n")


if __name__ == "__main__":
    main()
