import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
from source_bundle import extract_verified


class BundleTest(unittest.TestCase):
    def exercise(self, entries, expected=True, wrong_digest=False):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "source.zip"
            with zipfile.ZipFile(p,"w") as z:
                for name, mode in entries:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = mode << 16
                    z.writestr(info,b"data")
            h = hashlib.sha256(p.read_bytes()).hexdigest() if not wrong_digest else "0"*64
            if expected:
                self.assertEqual((extract_verified(p,h,d)/entries[0][0]).read_bytes(), b"data")
            else:
                with self.assertRaises(ValueError):
                    extract_verified(p,h,d)
                self.assertEqual(list(Path(d).iterdir()),[p])

    def test_regular_and_wrong_digest(self):
        self.exercise([("dir/file.txt",stat.S_IFREG)])
        self.exercise([("dir/file.txt",stat.S_IFREG)],False,True)

    def test_unsafe_paths_and_types(self):
        for name,mode in [("../outside",stat.S_IFREG),("C:/outside",stat.S_IFREG),
                          ("x/NUL.txt",stat.S_IFREG),("tree/.git/config",stat.S_IFREG),
                          ("link",stat.S_IFLNK),("fifo",stat.S_IFIFO)]:
            with self.subTest(name=name):
                self.exercise([(name,mode)],False)

    def test_path_collisions(self):
        for a,b in [("A/a","a/b"),("a","a/b"),("a","a")]:
            with self.subTest(a=a,b=b):
                self.exercise([(a,stat.S_IFREG),(b,stat.S_IFREG)],False)

    def test_source_mutation_after_snapshot_does_not_change_extracted_bytes(self):
        from unittest.mock import patch
        real_zip = zipfile.ZipFile
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)/"archive.zip"
            with real_zip(src,"w") as z:
                z.writestr("source.txt",b"original")
            h = hashlib.sha256(src.read_bytes()).hexdigest()
            def mutate_then_parse(fi):
                with real_zip(src,"w") as z:
                    z.writestr("source.txt",b"mutated")
                return real_zip(fi)
            with patch("source_bundle.zipfile.ZipFile", side_effect=mutate_then_parse):
                root = extract_verified(src,h,d)
            self.assertEqual((root/"source.txt").read_bytes(),b"original")
