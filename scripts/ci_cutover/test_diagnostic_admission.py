import unittest
from pathlib import Path
import test_worker_ingress as fixture
import verify_web_display_ingress as stage

class Diagnostic(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Worker()
        self.f.setUp()
    def call(self,route):
        self.f.msg["route"]=route
        return stage.check(self.f.policy,self.f.msg,self.f.http.__getitem__,route)
    def test_real_checkout_policy_path(self):
        root=Path("/tmp/review-worker-layout")
        abstract=root/"scripts"/"ci_cutover"/"verify_web_display_ingress.py"
        self.assertEqual(stage.policy_path("stop",abstract),root/".github"/"ci-cutover"/"stop-public-policy.json")
    def test_stop_only_manual(self):
        with self.assertRaises(ValueError): self.call("stop")
        self.f.http["/actions/runs/1"]["event"]="workflow_dispatch"
        self.assertEqual(self.call("stop"),(fixture.H,"workflow_dispatch"))
    def test_all_five_push_routes(self):
        for route in stage.DIAGNOSTICS-{"stop"}:
            self.assertEqual(self.call(route),(fixture.H,"push"))
    def test_pr_denied_for_diagnostics_and_display(self):
        self.f.as_pr()
        for route in stage.DIAGNOSTICS|{"display"}:
            with self.assertRaises(ValueError): self.call(route)
    def test_unknown_route_and_unsafe_path(self):
        with self.assertRaises(ValueError): stage.policy_path("../test")
