import hashlib
import io
import json
import unittest
from zipfile import ZipFile

from scripts.product_ci_ingress import DISPATCHER_PATH, PRODUCT, PRODUCT_ID, Invalid, acquire

HEAD = "1" * 40
BLOB = "2" * 40
WORKER = "3" * 40
REDIRECT = "https://actionstest.blob.core.windows.net/a"


class Fake:
    def __init__(self):
        self.downloaded = False
        self.redirect = REDIRECT
        self.expired = False
        self.request = dict(schema_version=1, source_repository_id=PRODUCT_ID, request_id="5-2",
                            ci_workflow_sha=WORKER, source_head_sha=HEAD, check_sha=HEAD,
                            source_event_name="push", source_ref="refs/heads/main", execution_sha=HEAD)

    def __call__(self, url, token):
        if not url.startswith(PRODUCT):
            assert token is None
            self.downloaded = True
            return 200, self.data
        assert token == "test_only"
        identity = {"id": PRODUCT_ID}
        path = url.removeprefix(PRODUCT)
        if path == "/actions/runs/5":
            return 200, json.dumps(dict(id=5, workflow_id=10, path=DISPATCHER_PATH, repository=identity,
                 head_repository=identity, event="push", head_branch="main", head_sha=HEAD, run_attempt=2))
        if path == "/git/ref/heads/main":
            return 200, json.dumps({"object": {"sha": HEAD}})
        if path == f"/contents/{DISPATCHER_PATH}?ref={HEAD}":
            return 200, json.dumps(dict(path=DISPATCHER_PATH, type="file", sha=BLOB))
        if path == "/actions/artifacts/6":
            buf = io.BytesIO()
            with ZipFile(buf, "w") as arc:
                arc.writestr("request.json", json.dumps(self.request))
            self.data = buf.getvalue()
            return 200, json.dumps(dict(id=6, workflow_run={"id": 5}, expired=self.expired,
                             name="ci-request-5-2", size_in_bytes=len(self.data),
                             digest="sha256:" + hashlib.sha256(self.data).hexdigest()))
        if path == "/actions/artifacts/6/zip":
            return 302, self.redirect
        raise AssertionError(path)


class IngressTest(unittest.TestCase):
    def run_ingress(self, fake):
        return acquire(run_id=5, artifact_id=6, workflow_id=10, dispatcher_blob=BLOB,
                       worker_sha=WORKER, token="test_only", transport=fake)

    def test_bound_source_and_no_token_on_download(self):
        fake = Fake()
        self.assertEqual(self.run_ingress(fake)["execution_sha"], HEAD)
        self.assertTrue(fake.downloaded)

    def test_disallowed_redirect_and_expired_artifact_do_not_download(self):
        for updates in ({"redirect": "https://evil.example/a"}, {"expired": True}):
            fake = Fake()
            vars(fake).update(updates)
            with self.assertRaises(Invalid):
                self.run_ingress(fake)
            self.assertFalse(fake.downloaded)

    def test_artifact_cannot_choose_source_or_replay(self):
        for field, value in (("execution_sha", "4" * 40), ("request_id", "5-1")):
            fake = Fake()
            fake.request[field] = value
            with self.assertRaises(Invalid):
                self.run_ingress(fake)


class TargetFake(Fake):
    BASE, MERGE = "5" * 40, "6" * 40

    def __init__(self, *, event="pull_request_target", missing_link=False, wrong_head=False):
        super().__init__()
        self.event, self.missing_link, self.wrong_head = event, missing_link, wrong_head
        self.request.update(source_event_name="pull_request", source_pr_number=42,
                            source_base_sha=self.BASE, source_merge_sha=self.MERGE,
                            check_sha=self.MERGE, execution_sha=self.MERGE)

    def __call__(self, url, token):
        identity = {"id": PRODUCT_ID}
        origin = {"sha": HEAD, "repo": identity}
        target = {"sha": self.BASE, "ref": "main", "repo": identity}
        path = url.removeprefix(PRODUCT)
        values = {
            "/actions/runs/5": dict(id=5, workflow_id=10, path=DISPATCHER_PATH, repository=identity,
                                     head_repository=identity, event=self.event, head_branch="main",
                                     head_sha=HEAD if self.wrong_head else self.BASE, run_attempt=2,
                                     pull_requests=[] if self.missing_link else [
                                         {"number": 42, "head": origin, "base": target}]),
            "/pulls/42": dict(number=42, state="open", base=target, head=origin,
                              mergeable=True, merge_commit_sha=self.MERGE),
            "/git/ref/pull/42/merge": {"object": {"sha": self.MERGE}},
            f"/git/commits/{self.MERGE}": {"parents": [{"sha": self.BASE}, {"sha": HEAD}]},
            f"/contents/{DISPATCHER_PATH}?ref={self.BASE}": {"path": DISPATCHER_PATH, "type": "file", "sha": BLOB},
        }
        if path in values:
            assert token == "test_only"
            return 200, json.dumps(values[path])
        return super().__call__(url, token)


class TargetIngressTest(unittest.TestCase):
    def run_ingress(self, fake):
        return acquire(run_id=5, artifact_id=6, workflow_id=10, dispatcher_blob=BLOB,
                       worker_sha=WORKER, token="test_only", transport=fake)

    def test_target_is_normalized_and_definition_is_authorized_on_base(self):
        result = self.run_ingress(TargetFake())
        self.assertEqual(result["source_event"], "pull_request")
        self.assertEqual(result["execution_sha"], TargetFake.MERGE)

    def test_unsupported_or_unbound_target_fails_before_download(self):
        for options in ({"event": "pull_request"}, {"event": "workflow_dispatch"},
                        {"missing_link": True}, {"wrong_head": True}):
            fake = TargetFake(**options)
            with self.assertRaises(Invalid):
                self.run_ingress(fake)
            self.assertFalse(fake.downloaded)
