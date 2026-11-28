"""Allowlisted Source receipts streamed directly into V2 age ciphertext."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile

from run_linux_health_v2 import CASE, LOG_CAP, PRODUCT
from xml.etree import ElementTree

RECIPIENT_HASH = "ba311eeae31312c73f57c9a2cc4c80bbb58380e7c3df956db1d09432b79cca87"
MIB = 1024 * 1024
REPORTS = {"ci-results.xml": 16*MIB, "ci-shard.json": 8*MIB, "ci-failures.log": 3*MIB,
           "two-job-observation.json": MIB}
RAW = {"stage-report.json": 4096, **{name + ".log": LOG_CAP for name in
       ("dependencies", "display", "verify-display", "source")}}


def recipient():
    value = os.environ["RECIPIENT"]
    if (not re.fullmatch(r"age1[023456789ac-hj-np-z]{58}", value)
            or hashlib.sha256(value.encode("ascii")).hexdigest() != RECIPIENT_HASH):
        raise ValueError("bad V2 recipient")
    return value


def limited(path, cap):
    try:
        initial = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1 or initial.st_size > cap
            or getattr(initial, "st_file_attributes", 0) & 0x400
            or path.resolve(strict=True) != path):
        raise ValueError("unexpected report path, link or size")
    with path.open("rb") as stream:
        if not os.path.samestat(initial, os.fstat(stream.fileno())):
            raise ValueError("report changed before read")
        data = stream.read(cap+1)
    if len(data) != initial.st_size:
        raise ValueError("report changed during read")
    return data


def gather(source, raw, outcome):
    found = {}
    for directory, names in ((source / "build", REPORTS), (raw, RAW)):
        for name, cap in names.items():
            value = limited(directory / name, cap)
            if value is not None:
                found[name] = value
    if "stage-report.json" not in found or (outcome == "success" and
            not found.get("ci-results.xml")):
        raise ValueError("required shard evidence missing")
    if "ci-results.xml" in found:
        xml = found["ci-results.xml"]
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("unexpected xml")
        cases = list(ElementTree.fromstring(xml).iter("testcase"))
        if len(cases) != 1 or cases[0].get("name") != CASE.split("::")[1] or cases[0].get("classname") != "tests.ui.presentation.test_image_demand_health_contract":
            raise ValueError("unexpected scope")
        if outcome == "success" and any(cases[0].find(tag) is not None for tag in ("error", "failure", "skipped")):
            raise ValueError("test did not pass")
    return found


def seal(source, raw, output, executable):
    key = recipient()
    period = {x: os.environ[key] for x, key in (("workflow_sha", "GITHUB_WORKFLOW_SHA"),
              ("run", "GITHUB_RUN_ID"), ("attempt", "GITHUB_RUN_ATTEMPT"),
              ("repository_id", "GITHUB_REPOSITORY_ID"), ("outcome", "SOURCE_OUTCOME"))}
    platform, shard = os.environ["SOURCE_PLATFORM"], os.environ["SOURCE_SHARD"]
    if (platform not in ("linux", "windows") or shard not in ("runtime", "other")
            or period["repository_id"] != "1468905732" or period["outcome"] not in ("success", "failure")
            or not re.fullmatch(r"[0-9a-f]{40}", period["workflow_sha"])
            or not all(re.fullmatch(r"[1-9][0-9]*", period[key]) for key in ("run", "attempt"))):
        raise ValueError("bad hosted identity")
    files = gather(source, raw, period["outcome"])
    manifest = dict(version=1, encryption_profile="V2", suite_family="linux-health-targeted", source_sha=PRODUCT,
                    packager_sha="", job=f"{platform}-{shard}", **period,
                    files={k: dict(size=len(v), sha256=hashlib.sha256(v).hexdigest()) for k, v in files.items()})
    files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("ascii")
    with subprocess.Popen([str(executable), "-r", key, "-o", str(output)], stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
        with child.stdin as pipe, tarfile.open(fileobj=pipe, mode="w|") as archive:
            for name, data in sorted(files.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o600
                archive.addfile(member, io.BytesIO(data))
        if child.wait(timeout=45):
            raise ValueError("age failed")
    with output.open("rb") as encrypted:
        if encrypted.readline(64) != b"age-encryption.org/v1\n":
            raise ValueError("expected age envelope")


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--preflight"]:
            recipient()
        else:
            source, raw, output, executable = map(Path, sys.argv[1:])
            try:
                seal(source.resolve(), raw.resolve(), output, executable)
            except Exception:
                output.unlink(missing_ok=True)
                raise
    except Exception:
        raise SystemExit("source_v2=seal_or_preflight_failed") from None
