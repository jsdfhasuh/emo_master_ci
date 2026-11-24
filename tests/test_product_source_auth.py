import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlparse

from scripts.product_source_auth import ORIGIN, PRODUCT, PRODUCT_ID, SourceAuthError, verify_authenticated_source, verify_checkout

PIN = "e" * 40
FAKE = "synthetic_credential"


class AuthTests(unittest.TestCase):
    def test_authenticated_only_identity_plus_exact_repo_commit(self):
        read_paths = []
        def read(request):
            self.assertEqual(request.get_header("Authorization"), "Bearer " + FAKE)
            path = urlparse(request.full_url).path
            read_paths.append(path)
            replies = {
                "/user": {"id": 17},
                "/repos/" + PRODUCT: {"id": PRODUCT_ID, "full_name": PRODUCT, "private": False, "visibility": "public"},
                "/repos/" + PRODUCT + "/git/commits/" + PIN: {"sha": PIN},
            }
            return 200, json.dumps(replies[path]).encode()
        verify_authenticated_source(PIN, FAKE, read, require_public=True)
        self.assertEqual(read_paths, ["/user", "/repos/" + PRODUCT, "/repos/" + PRODUCT + "/git/commits/" + PIN])

    def test_empty_token_and_invalid_identity_fail_before_product_read(self):
        with self.assertRaises(SourceAuthError):
            verify_authenticated_source(PIN, "", lambda _: self.fail("anonymous attempt"))
        observed = []
        def unauthorized(request):
            observed.append(urlparse(request.full_url).path)
            return 401, b"{}"
        with self.assertRaises(SourceAuthError):
            verify_authenticated_source(PIN, FAKE, unauthorized)
        self.assertEqual(observed, ["/user"])

    def test_probe_refuses_a_private_product(self):
        def read(request):
            if request.full_url.endswith("/user"):
                return 200, b'{"id":17}'
            if request.full_url.endswith(PRODUCT):
                return 200, json.dumps({"id": PRODUCT_ID, "full_name": PRODUCT,
                                        "private": True, "visibility": "private"}).encode()
            self.fail("must not read commit in the still-Public-only probe")
        with self.assertRaisesRegex(SourceAuthError, "still-Public"):
            verify_authenticated_source(PIN, FAKE, read, require_public=True)

    def test_exact_detached_checkout_rejects_local_credential_binding(self):
        with TemporaryDirectory() as root:
            def git(*args):
                return subprocess.check_output(["git", "-C", root, *args],
                                               text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-q")
            git("-c", "user.name=Test", "-c", "user.email=test@test.invalid",
                "commit", "--quiet", "--allow-empty", "-m", "test")
            git("remote", "add", "origin", ORIGIN)
            pin = git("rev-parse", "HEAD")
            git("checkout", "--quiet", "--detach", pin)
            verify_checkout(Path(root), pin, env={})
            with self.assertRaises(SourceAuthError):
                verify_checkout(Path(root), pin, env={"EMO_CI_TOKEN": FAKE})
            git("config", "http.https://github.com/.extraheader", "Authorization: test-only")
            with self.assertRaises(SourceAuthError):
                verify_checkout(Path(root), pin, env={})

    def test_workflow_only_explicitly_propagates_source_token(self):
        import yaml
        def read(name):
            return yaml.load(Path(".github/workflows", name + ".yml").read_text(), Loader=yaml.BaseLoader)
        dispatch = read("product-ci-dispatch")
        source = read("product-ci-source")
        probe = read("product-ci-source-auth-probe")
        self.assertEqual(dispatch["jobs"]["source"]["secrets"], {"EMO_CI_TOKEN": "${{ secrets.EMO_CI_TOKEN }}"})
        self.assertEqual(source["on"]["workflow_call"]["secrets"], {"EMO_CI_TOKEN": {"required": "true"}})
        for job in (source["jobs"]["source-shards"], probe["jobs"]["authenticate-public-source"]):
            steps = job["steps"]
            names = [item["name"] for item in steps if "EMO_CI_TOKEN" in json.dumps(item)]
            self.assertEqual(len(names), 2)  # identity proof and pinned checkout only
            checkout = next(item["with"] for item in steps if item.get("with", {}).get("repository") == PRODUCT)
            self.assertEqual(checkout["token"], "${{ secrets.EMO_CI_TOKEN }}")
            self.assertEqual(checkout["persist-credentials"], "false")
        self.assertNotIn("Run original source checks", json.dumps(probe))
        self.assertIn("--require-public", json.dumps(probe))
