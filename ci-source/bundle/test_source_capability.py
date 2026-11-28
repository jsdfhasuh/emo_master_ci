import json
import unittest
from source_capability import IDS, parse_capability


class CapabilityTest(unittest.TestCase):
    def test_exact_binding_and_fail_closed(self):
        binding = dict.fromkeys(IDS,1) | {"source_sha":"a"*40,"worker_sha":"b"*40}
        host = "approved-actions-storage.blob.core.windows.net"
        obj = binding | dict(archive_sha256="c"*64,issued_at=1,expires_at=301,
                             url=f"https://{host}/object?sig=example-only")
        parse = lambda o: parse_capability(json.dumps(o).encode(),binding,10,{host})
        self.assertNotIn("url",parse(obj)[0])
        for key,value in [("worker_attempt",True),("origin_run",2),("source_sha","d"*40),
                          ("expires_at",302),("expires_at",10),("url","https://evil.example/path?sig=secret")]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,"^invalid source capability$"):
                parse(obj | {key:value})
