import unittest
import test_worker_ingress as fixture
import verify_web_display_ingress as reader


class WebDisplay(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.Worker()
        self.fixture.setUp()
    def read(self,route):
        return reader.check(self.fixture.policy,self.fixture.msg,self.fixture.http.__getitem__,route)
    def test_web_push_and_manual(self):
        self.fixture.msg["route"]="web"
        self.assertEqual(self.read("web"),(fixture.H,"push"))
        self.fixture.http["/actions/runs/1"]["event"]="workflow_dispatch"
        self.assertEqual(self.read("web"),(fixture.H,"workflow_dispatch"))
    def test_web_pull_request_uses_merge(self):
        expected=self.fixture.as_pr()
        self.fixture.msg["route"]="web"
        self.assertEqual(self.read("web"),(expected,"pull_request"))
    def test_cross_route_rejected(self):
        self.fixture.msg["route"]="display"
        with self.assertRaises(ValueError): self.read("web")
    def test_private_source_is_disabled(self):
        self.fixture.msg["route"]="web"
        self.fixture.http[""]["private"]=True
        with self.assertRaises(ValueError): self.read("web")
