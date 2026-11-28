from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys

from load_product_web_workflow import PRODUCT_SHA, load_recipe
from run_product_web_recipe import select


class ProductWebRecipeTests(unittest.TestCase):
    def test_reviewed_product_four_profiles(self):
        raw = Path(sys.argv[1]).read_bytes()
        with patch("load_product_web_workflow.subprocess.run", side_effect=[
            SimpleNamespace(returncode=0, stdout=(PRODUCT_SHA + "\n").encode()),
            SimpleNamespace(returncode=0, stdout=raw),
        ]):
            recipe = load_recipe(Path("product"))
        for job, platform, event, number in [
            ("web-panel", "ubuntu-latest", "push", 22),
            ("web-panel", "windows-latest", "push", 19),
            ("web-panel", "windows-latest", "workflow_dispatch", 22),
            ("product-runtime", "windows-latest", "push", 7),
        ]:
            with self.subTest(job=job, platform=platform, event=event):
                _, steps = select(recipe, job, platform, event)
                self.assertEqual(number, len(steps))

    def test_different_product_ref_rejected(self):
        with patch("load_product_web_workflow.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=b"0" * 40)):
            with self.assertRaisesRegex(ValueError, "unexpected product SHA"):
                load_recipe(Path("product"))

    def test_workflow_drift_rejected(self):
        with patch("load_product_web_workflow.subprocess.run", side_effect=[
            SimpleNamespace(returncode=0, stdout=PRODUCT_SHA.encode()),
            SimpleNamespace(returncode=0, stdout=b"changed file"),
        ]):
            with self.assertRaisesRegex(ValueError, "unreviewed product Web workflow"):
                load_recipe(Path("product"))


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
