"""Synthetic evidence path checks; never run the real project in these tests."""
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, main

from source_recipe import MIB, TRUNCATED, capture_tail, preserve_reports, run_step


class SourceEvidenceTests(TestCase):
    def test_oversized_stream_is_capped_and_preserves_tail(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "checks.stderr.log"
            capture_tail(io.BytesIO(b"a" * MIB + b"diagnosis"), path)
            self.assertEqual(MIB // 2, path.stat().st_size)
            self.assertTrue(path.read_bytes().startswith(TRUNCATED))
            self.assertTrue(path.read_bytes().endswith(b"diagnosis"))

    def test_child_failure_keeps_both_streams_and_exit_status(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)
            status = run_step("checks", [sys.executable, "-c", "import sys; "
                       "print('private-stdout'); print('private-stderr', file=sys.stderr); sys.exit(7)"],
                       path, None, path)
            self.assertEqual(7, status)
            self.assertEqual("private-stdout", (path / "checks.stdout.log").read_text().strip())
            self.assertEqual("private-stderr", (path / "checks.stderr.log").read_text().strip())

    def test_reports_are_allowlisted_and_oversized_report_is_not_truncated(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / "evidence"
            evidence.mkdir()
            build = root / "build"
            build.mkdir()
            (build / "ci-shard.json").write_text("{}")
            (build / "ci-results.xml").write_bytes(b"x" * (16 * MIB + 1))
            (build / "not-allowed.txt").write_text("no")
            reports = preserve_reports(root.resolve(), evidence)
            self.assertEqual("oversize", reports["ci-results.xml"])
            self.assertEqual("retained", reports["ci-shard.json"])
            self.assertEqual(["ci-shard.json"], sorted(p.name for p in evidence.iterdir()))

    def test_report_symlink_does_not_copy_target(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            evidence = root / "evidence"
            evidence.mkdir()
            build = root / "build"
            build.mkdir()
            outside = root / "outside"
            outside.write_text("outside report path")
            try:
                (build / "ci-shard.json").symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation unavailable")
            self.assertEqual("unsafe", preserve_reports(root, evidence)["ci-shard.json"])
            self.assertFalse(any(evidence.iterdir()))


if __name__ == "__main__":
    main()
