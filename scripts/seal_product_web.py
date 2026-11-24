"""Encrypt Web evidence and manifest; never create a plaintext archive."""
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

from load_product_web_workflow import PRODUCT_SHA

RECIPIENT_FINGERPRINT = "ba311eeae31312c73f57c9a2cc4c80bbb58380e7c3df956db1d09432b79cca87"


def validate_recipient(recipient):
    if not re.fullmatch(r"age1[0-9a-z]{58}", recipient) or (
            hashlib.sha256(recipient.encode("ascii")).hexdigest() != RECIPIENT_FINGERPRINT):
        raise ValueError("unexpected V2 recipient")


def seal(root, output, age):
    recipient = os.environ.get("WEB_V2_RECIPIENT", "")
    validate_recipient(recipient)
    manifest = dict(product_sha=PRODUCT_SHA, workflow_sha=os.environ["GITHUB_WORKFLOW_SHA"],
                    run=os.environ["GITHUB_RUN_ID"], attempt=os.environ["GITHUB_RUN_ATTEMPT"],
                    profile=os.environ["WEB_PROFILE"], outcome=os.environ["WEB_OUTCOME"], files={})
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["workflow_sha"]) or any(
        not re.fullmatch(r"[1-9][0-9]*", manifest[k]) for k in ("run", "attempt")
    ):
        raise ValueError("bad workflow metadata")
    if manifest["profile"] not in {"linux-web", "windows-web-auto", "windows-web-full", "windows-owning-runtime"}:
        raise ValueError("unexpected Web profile")
    if manifest["outcome"] not in {"success", "failure", "cancelled", "skipped"}:
        raise ValueError("unexpected Web outcome")
    output.parent.mkdir(parents=True, exist_ok=True)
    members = {}
    if root.is_symlink() or getattr(root.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("unsafe evidence root")
    for i in range(1, 24):
        name = f"step-{i:02}.log"
        path = root / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("unsafe evidence member")
        with path.open("rb") as handle:
            if not os.path.samestat(info, os.fstat(handle.fileno())):
                raise ValueError("changed evidence member")
            data = handle.read(512 * 1024 + 1)
        if len(data) > 512 * 1024:
            raise ValueError("oversized evidence member")
        members[name] = data
        manifest["files"][name] = hashlib.sha256(data).hexdigest()
    members["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    temp = output.with_suffix(".partial")
    try:
        with subprocess.Popen([str(age), "-r", recipient, "-o", str(temp)], stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
            with child.stdin as pipe, tarfile.open(fileobj=pipe, mode="w|") as archive:
                for name, data in members.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = 0o600
                    archive.addfile(member, io.BytesIO(data))
            if child.wait() or temp.stat().st_size == 0:
                raise ValueError("encryption failed")
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "--preflight":
            validate_recipient(os.environ.get("WEB_V2_RECIPIENT", ""))
        else:
            seal(*(Path(arg) for arg in sys.argv[1:]))
    except (OSError, ValueError, KeyError):
        print("web_v2_evidence=failure")
        sys.exit(1)
