from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from scripts import runtime_credit_recipe as recipe
from scripts import runtime_credit_seal as seal

class CreditContracts(unittest.TestCase):
    def test_unknown_recipe_closed(self):
        with self.assertRaises(ValueError): recipe.steps("on: []")
    def test_capability_environment(self):
        env=recipe.child_environment({"GITHUB_RUN_ID":"25","GITHUB_RUN_ATTEMPT":"1","GITHUB_TOKEN":"x",
            "GITHUB_OUTPUT":"x","GITHUB_ENV":"x","GITHUB_STEP_SUMMARY":"x","ACTIONS_RUNTIME_TOKEN":"x",
            "EMO_CI_TOKEN":"x","PYTHONPATH":"/secret","PATH":"tools"},Path("temp"),Path("product"))
        for k in ("GITHUB_TOKEN","GITHUB_OUTPUT","GITHUB_ENV","GITHUB_STEP_SUMMARY","ACTIONS_RUNTIME_TOKEN","EMO_CI_TOKEN","PYTHONPATH"):
            self.assertNotIn(k,env)
        self.assertEqual(env["GITHUB_SHA"],recipe.SOURCE)
        self.assertEqual(env["PATH"],"tools")
    def test_only_regular_evidence(self):
        with TemporaryDirectory() as tmp:
            t=Path(tmp);f=t/"e";f.write_bytes(b"1");self.assertEqual(list(seal.add_tree(t)),[f])
            (t/"other").symlink_to(f)
            with self.assertRaises(ValueError): list(seal.add_tree(t))
    def test_seal_rejects_different_recipient(self):
        with TemporaryDirectory() as t,patch.dict("os.environ",{"RUNNER_TEMP":t,"RECIPIENT":"other"}):
            with self.assertRaises(ValueError):seal.main()
    def test_missing_journal_does_not_encrypt_empty_receipt(self):
        import hashlib
        with TemporaryDirectory() as t,patch.dict("os.environ",{"RUNNER_TEMP":t,"RECIPIENT":"fake"}),patch.object(seal,"RECIPIENT_HASH",hashlib.sha256(b"fake").hexdigest()):
            with self.assertRaises(ValueError):seal.main()
