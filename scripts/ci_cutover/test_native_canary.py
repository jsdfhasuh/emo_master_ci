import json
from hashlib import sha256
from unittest import TestCase
import native_canary as n


class Canary(TestCase):
    def call(self,event="push",bad=False):
        head="1"*40; base="2"*40; merge="3"*40; worker="4"*40
        target=merge if event=="pull_request" else head
        data=dict(schema=1,source_run=100,source_attempt=1,artifact_id=110,artifact_digest="sha256:"+"f"*64,
                  head=head,base=base if event=="pull_request" else None,execution=target,
                  pr=29 if event=="pull_request" else None,route=n.ROUTE)
        wire=n.canon(data)
        key=sha256(n.canon([n.WID,n.PATH,n.TAG,worker,n.OWNER,wire]).encode("ascii")).hexdigest()
        def get(path):
            if path=="/actions/runs/100":
                return dict(id=100,run_attempt=1,repository={"id":n.REPO},head_repository={"id":n.REPO},head_sha=head,event=event,
                            actor={"id":n.OWNER},triggering_actor={"id":n.OWNER},workflow_id=433407309,
                            path=".github/workflows/phase4-native-event-receipt.yml",head_branch="main" if bad else "dot/phase4-event-head")
            if path=="/pulls/29":
                return dict(state="open",head={"repo":{"id":n.REPO},"ref":"dot/phase4-event-head","sha":head},
                            base={"repo":{"id":n.REPO},"ref":"dot/phase4-event-base","sha":base},merge_commit_sha=merge)
            if path=="/actions/artifacts/110":
                return dict(id=110,name="ci-request-100-1",expired=False,digest=data["artifact_digest"],
                    workflow_run=dict(id=100,head_sha=head,repository_id=n.REPO,head_repository_id=n.REPO))
            self.fail(path)
        return n.make(wire,key,worker,310,1,get)
    def test_three_event_bindings(self):
        for e in ("push","pull_request","workflow_dispatch"):
            self.assertEqual(self.call(e)["event"],e)
    def test_wrong_branch_refused(self):
        with self.assertRaises(ValueError):self.call(bad=True)
