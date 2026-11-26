import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_event_pair import *

def fixture(run):
    art,digest,size,head,ex,branch,wid,fn,blob = PAIRS[run]
    path='.github/workflows/'+fn
    ident={'id':PRODUCT}
    row=dict(id=int(run),run_attempt=1,event='pull_request' if run==PR else 'workflow_dispatch',workflow_id=wid,path=path,head_branch=branch,head_sha=head,status='completed',conclusion='success',repository=ident,head_repository=ident,pull_requests=[])
    db={'actions/runs/'+run:row,'actions/artifacts/'+art:dict(id=int(art),expired=False,digest='sha256:'+digest,size_in_bytes=size,name='ci-request-'+run+'-1',workflow_run=dict(id=int(run),repository_id=PRODUCT,head_repository_id=PRODUCT,head_sha=head)),
        'git/ref/heads/'+branch:{'object':{'sha':head}},'contents/'+path+'?ref='+ex:{'sha':blob}}
    if run==PR:
        row['pull_requests']=[dict(number=26,head={'sha':head},base={'sha':BASE})]
        db.update({'pulls/26':dict(number=26,state='open',mergeable=True,head=dict(repo=ident,sha=head,ref=branch),base=dict(repo=ident,sha=BASE,ref='main'),merge_commit_sha=ex),'git/ref/heads/main':{'object':{'sha':BASE}},'git/ref/pull/26/merge':{'object':{'sha':ex}},'git/commits/'+ex:{'parents':[{'sha':BASE},{'sha':head}]}})
    return db
class Test(unittest.TestCase):
    def test_manual(self):
        self.assertEqual(bind(MANUAL,PAIRS[MANUAL][0],fixture(MANUAL).__getitem__),PAIRS[MANUAL][3])
    def test_pr(self):
        self.assertEqual(bind(PR,PAIRS[PR][0],fixture(PR).__getitem__),PAIRS[PR][4])
    def test_cross_event_input(self):
        with self.assertRaises(ValueError): bind(PR,PAIRS[MANUAL][0],None)
    def test_fork(self):
        db=fixture(PR); db['pulls/26']['head']['repo']={'id':1}
        with self.assertRaises(ValueError): bind(PR,PAIRS[PR][0],db.__getitem__)
    def test_stale_merge(self):
        db=fixture(PR); db['git/ref/pull/26/merge']['object']['sha']=PAIRS[PR][3]
        with self.assertRaises(ValueError): bind(PR,PAIRS[PR][0],db.__getitem__)
    def test_wrong_parents(self):
        db=fixture(PR); db['git/commits/'+PAIRS[PR][4]]['parents'].reverse()
        with self.assertRaises(ValueError): bind(PR,PAIRS[PR][0],db.__getitem__)
    def test_wrong_digest(self):
        db=fixture(MANUAL);db['actions/artifacts/'+PAIRS[MANUAL][0]]['digest']='wrong'
        with self.assertRaises(ValueError): bind(MANUAL,PAIRS[MANUAL][0],db.__getitem__)
    def test_moved_manual_branch(self):
        db=fixture(MANUAL);db['git/ref/heads/'+PAIRS[MANUAL][5]]['object']['sha']=BASE
        with self.assertRaises(ValueError): bind(MANUAL,PAIRS[MANUAL][0],db.__getitem__)
