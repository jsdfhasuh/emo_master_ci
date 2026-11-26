import unittest
from pathlib import Path
from scripts import runtime_a18_recipe as a18, runtime_stop_recipe as stop

class IndependentDiagnostics(unittest.TestCase):
    def test_cross_lane_pin_and_invalid_check_closed(self):
        self.assertNotEqual(a18.DIGEST,stop.DIGEST)
        for runner in (a18,stop):
            with self.assertRaises(ValueError): runner.steps("not a pinned recipe")
    def test_stage_counts_and_independent_post_checks(self):
        self.assertEqual([s[2] for s in a18.SPANS],["pwsh","pwsh","pwsh","python","pwsh"])
        self.assertEqual([s[2] for s in stop.SPANS],["pwsh","python","pwsh","python","python"])
    def test_allowlisted_product_environment(self):
        for runner in (a18,stop):
            env=runner.child_environment(dict(GITHUB_RUN_ID="200",GITHUB_RUN_ATTEMPT="2",
                 EMO_CI_TOKEN="private",GITHUB_OUTPUT="private",ACTIONS_RUNTIME_TOKEN="private"),
                 Path("temp"),Path("product"))
            self.assertEqual(env["QT_QPA_PLATFORM"],"offscreen")
            self.assertEqual(env["GITHUB_SHA"],runner.SOURCE)
            self.assertFalse({"EMO_CI_TOKEN","GITHUB_OUTPUT","ACTIONS_RUNTIME_TOKEN"} & env.keys())
    def test_each_profile_has_own_activation_and_ciphertext_only(self):
        for n in ("a18","stop"):
            w=Path(".github/workflows",f"runtime-{n}-original-v2.yml").read_text()
            self.assertIn(f".github/diagnostic-activation/{n}-original-v2.json",w)
            self.assertIn(f"path: ${{{{ runner.temp }}}}/{n}-evidence.tar.age",w)
            self.assertNotIn("secrets.",w)
