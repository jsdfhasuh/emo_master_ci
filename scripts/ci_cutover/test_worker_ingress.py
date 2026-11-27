import unittest
from worker_ingress import check,REPO_ID

H,E="1"*40,"3"*40
D="sha256:"+"2"*64
P=".github/workflows/product-ci-request.yml"
class Worker(unittest.TestCase):
    def setUp(self):
        self.policy=dict(origin_workflow_id=7,origin_path=P,trusted_push_branches=["main"],
                         trusted_manual_branches=["main"],trusted_pr_heads=[],trusted_pr_bases=["main"],approved_emitter_blob=E)
        self.msg=dict(schema=1,source_run=1,source_attempt=2,artifact_id=4,artifact_digest=D,head=H,base=None,execution=H,pr=None,route="source")
        repo={"id":REPO_ID}
        self.http={
          "":{"id":REPO_ID,"private":False},
          "/actions/runs/1":dict(id=1,run_attempt=2,workflow_id=7,path=P,head_sha=H,status="completed",
                    conclusion="success",event="push",head_branch="main",repository=repo,head_repository=repo.copy()),
          "/actions/artifacts/4":dict(id=4,expired=False,digest=D,name="ci-request-1-2",size_in_bytes=1024,
                    workflow_run=dict(id=1,head_sha=H,repository_id=REPO_ID,head_repository_id=REPO_ID)),
          "/git/ref/heads/main":{"object":{"sha":H}},
          f"/contents/{P}?ref={H}":{"type":"file","sha":E}}
    def c(self):
        return check(self.policy,self.msg,self.http.__getitem__)
    def test_exact(self):
        self.assertEqual(self.c(),H)
    def test_attempt_rejected(self):
        self.msg["source_attempt"]=3
        with self.assertRaises(ValueError):self.c()
    def test_pin_rejected(self):
        self.policy["approved_emitter_blob"]="4"*40
        with self.assertRaises(ValueError):self.c()
    def test_private_closed_without_relay(self):
        self.http[""]["private"]=True
        with self.assertRaises(ValueError):self.c()
    def test_changed_tip_rejected(self):
        self.http["/git/ref/heads/main"]["object"]["sha"]="4"*40
        with self.assertRaises(ValueError):self.c()
    def test_missing_artifact_not_green(self):
        self.http["/actions/artifacts/4"]["expired"]=True
        with self.assertRaises(ValueError):self.c()
    def test_wrong_worker_route(self):
        self.msg["route"]="shell"
        with self.assertRaises(ValueError):self.c()
    def as_pr(self):
        B,M="4"*40,"5"*40
        self.msg.update(pr=12,base=B,execution=M)
        self.policy["trusted_pr_heads"]=["trusted/topic"]
        run=self.http["/actions/runs/1"]
        run.update(event="pull_request",head_branch="trusted/topic",
                   pull_requests=[{"number":12,"head":{"sha":H},"base":{"sha":B}}])
        self.http.update({"/pulls/12":{"number":12,"state":"open","mergeable":True,"merge_commit_sha":M,
                           "head":{"sha":H,"ref":"trusted/topic","repo":{"id":REPO_ID}},
                           "base":{"sha":B,"ref":"main","repo":{"id":REPO_ID}}},
                           "/git/ref/heads/trusted/topic":{"object":{"sha":H}},
                           "/git/ref/heads/main":{"object":{"sha":B}},
                           "/git/ref/pull/12/merge":{"object":{"sha":M}},
                           f"/git/commits/{M}":{"sha":M,"parents":[{"sha":B},{"sha":H}]},
                           f"/contents/{P}?ref={M}":{"type":"file","sha":E}})
        return M
    def test_pr_exact_merge(self):
        self.assertEqual(self.as_pr(),self.c())
    def test_pr_fork_rejected(self):
        self.as_pr()
        self.http["/pulls/12"]["head"]["repo"]["id"]=17
        with self.assertRaises(ValueError):self.c()
