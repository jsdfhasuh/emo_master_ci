"""Package bounded real evidence and pin the V2 locally installed recipient/tool."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile

RECIPIENT_HASH = "ba311eeae31312c73f57c9a2cc4c80bbb58380e7c3df956db1d09432b79cca87"

def safe_file(p):
    st=p.lstat()
    return (stat.S_ISREG(st.st_mode) and st.st_nlink == 1
            and not getattr(st,"st_file_attributes",0)&0x400)

def add_tree(p):
    if safe_file(p):
        yield p
    elif stat.S_ISDIR(p.lstat().st_mode) and not getattr(p.lstat(),"st_file_attributes",0)&0x400:
        for x in p.iterdir(): yield from add_tree(x)
    else: raise ValueError("special_file")

def main():
    root=Path(os.environ["RUNNER_TEMP"]);base=root/"stop-v2";scratch=base/"scratch"
    r=os.environ["RECIPIENT"]
    if hashlib.sha256(r.encode("ascii")).hexdigest()!=RECIPIENT_HASH:raise ValueError
    if not base.is_dir() or not safe_file(base/"status.json"):raise ValueError
    files=[base/"status.json",*sorted(base.glob("stage-*.log"))]
    files.extend(scratch/name for name in ['runtime-stop-diagnostics.json', 'runtime-native-thread-origins.json', 'observed-junit.xml', 'observed-phases.jsonl'] if (scratch/name).exists())
    if len(files)>20000 or any(not safe_file(f) for f in files) or sum(f.stat().st_size for f in files)>2*1024**3:raise ValueError
    out=root/"stop-evidence.tar.age"
    with subprocess.Popen([str(root/"stop-age.exe"),"-r",r,"-o",str(out)],stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as proc:
        with proc.stdin as pipe, tarfile.open(fileobj=pipe,mode="w|") as tar:
            manifest={}
            for f in files:
                digest=hashlib.sha256()
                with f.open("rb") as handle:
                    for chunk in iter(lambda:handle.read(1<<20),b""):digest.update(chunk)
                    size=handle.tell();handle.seek(0)
                    name=f.relative_to(base).as_posix();manifest[name]={"bytes":size,"sha256":digest.hexdigest()}
                    info=tarfile.TarInfo(name);info.size=size;tar.addfile(info,handle)
            data=json.dumps(manifest,sort_keys=True).encode();info=tarfile.TarInfo("manifest.json");info.size=len(data);tar.addfile(info,io.BytesIO(data))
        if proc.wait(timeout=90)!=0:raise ValueError
    with out.open("rb") as f:
        if f.readline(64)!=b"age-encryption.org/v1\n":raise ValueError

if __name__=="__main__":
    try:main()
    except Exception:sys.exit(1)
