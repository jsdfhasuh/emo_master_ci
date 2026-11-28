import unittest
import test_windows_ingress as fixture
H=fixture.H
from runtime_windows_ingress import verify, BUILDER

class Runtime(unittest.TestCase):
    def setUp(self):
        w=fixture.Worker();w.setUp()
        self.policy,self.msg,self.http=w.policy,w.msg,w.http
        self.policy['route']=self.msg['route']='runtime-windows'
        self.policy['approved_inputs']=dict(source_ref=H,packager_ref=BUILDER,source_sha=H,builder_sha=BUILDER)
        self.msg.update(source_ref=H,packager_ref=BUILDER)
        self.http['/git/commits/'+H]={'sha':H}
    def evaluate(self):
        return verify(self.policy,self.msg,self.http.__getitem__)
    def test_exact_current_commit(self):
        self.assertEqual(self.evaluate(),H)
    def test_different_approved_source_sha(self):
        execution="6"*40
        self.msg.update(execution=execution, source_ref=execution)
        self.policy['approved_inputs'].update(source_ref=execution,source_sha=execution)
        self.http['/git/commits/'+execution]={'sha':execution}
        self.assertEqual(self.evaluate(),execution)
    def test_different_approved_named_ref_must_still_match(self):
        execution="6"*40
        source="refs/heads/runtime-accepted"
        self.msg.update(execution=execution,source_ref=source)
        self.policy['approved_inputs'].update(source_ref=source,source_sha=execution)
        self.http['/git/commits/'+execution]={'sha':execution}
        self.http['/git/ref/heads/runtime-accepted']={'object':{'type':'commit','sha':execution}}
        self.assertEqual(self.evaluate(),execution)
        self.http['/git/ref/heads/runtime-accepted']['object']['sha']=H
        with self.assertRaises(ValueError):self.evaluate()
    def test_invalid_packager_does_not_use_caller_payload(self):
        self.msg['packager_ref']='f'*40
        with self.assertRaises(ValueError):self.evaluate()
