"""Bounded ZIP verifier. Call only after authenticating a request-bound manifest."""
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile

MAX_ARCHIVE = 256 * 1024**2
MAX_TOTAL = 512 * 1024**2
MAX_FILE = 64 * 1024**2
MAX_ENTRIES = 30_000
SEGMENT = re.compile(r"[a-zA-Z0-9_. -]{1,120}")
DEVICE = re.compile(r"(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])", re.I)


def extract_verified(archive, digest, parent):
    """Verify and extract into a new private staging dir; return it only on full success."""
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("invalid authenticated digest")
    with Path(archive).open("rb") as src, tempfile.TemporaryFile(dir=parent) as snapshot:
        h = hashlib.sha256()
        size = 0
        while chunk := src.read(1024**2):
            size += len(chunk)
            if size > MAX_ARCHIVE:
                raise ValueError("compressed size")
            h.update(chunk)
            snapshot.write(chunk)
        if h.hexdigest() != digest:
            raise ValueError("archive digest mismatch")
        snapshot.seek(0)
        with zipfile.ZipFile(snapshot) as z:
            entries = z.infolist()
            if not 0 < len(entries) <= MAX_ENTRIES:
                raise ValueError("entry count")
            explicit = set()
            tree = {}
            paths = []
            total = 0
            for e in entries:
                name = e.orig_filename
                directory = name.endswith("/")
                segs = (name[:-1] if directory else name).split("/")
                if len(name) > 240 or any(not SEGMENT.fullmatch(s) or s in (".","..") or
                            s.endswith((".", " ")) or
                            s.startswith(" ") or DEVICE.fullmatch(s.partition(".")[0]) or
                            s.casefold() == ".git" for s in segs):
                    raise ValueError("unsafe archive path")
                mode = stat.S_IFMT(e.external_attr >> 16)
                if mode not in (0, stat.S_IFDIR if directory else stat.S_IFREG) or e.flag_bits & 1:
                    raise ValueError("unsafe archive entry type")
                total += e.file_size
                if e.file_size > MAX_FILE or total > MAX_TOTAL or (directory and e.file_size):
                    raise ValueError("expanded size")
                for i in range(1, len(segs)+1):
                    spelling = "/".join(segs[:i])
                    key = spelling.casefold()
                    item = spelling, directory or i < len(segs)
                    if tree.setdefault(key, item) != item:
                        raise ValueError("path collision")
                if key in explicit:
                    raise ValueError("duplicate entry")
                explicit.add(key)
                paths.append((e, segs, directory))
            with tempfile.TemporaryDirectory(prefix=".source-staging-", dir=parent) as scratch:
                root = Path(scratch) / "source"
                root.mkdir(mode=0o700)
                for e,segs,directory in paths:
                    target = root.joinpath(*segs)
                    if directory:
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    count = 0
                    with z.open(e) as fi, target.open("xb") as fo:
                        while chunk := fi.read(1024**2):
                            count += len(chunk)
                            if count > e.file_size:
                                raise ValueError("unexpected expanded size")
                            fo.write(chunk)
                    if count != e.file_size:
                        raise ValueError("truncated member")
                published = Path(tempfile.mkdtemp(prefix="verified-source-", dir=parent))
                os.replace(root, published / "source")
                return published / "source"
