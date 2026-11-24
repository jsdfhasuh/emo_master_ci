"""Approved pilot only; both attempts use a single, immutable, non-release ref."""
import os
from pilot_controller import Pilot, PilotError, PUBLIC, WORKFLOW_PATH

MAIN = "6284d57659b840f5b852b33540f524ff8c9c2ff7"
BLOB = "fd8ef49acd96b1f5b2b309cc7a35b1599cd4d6d6"
TAG = "ci-dispatch-pilot-20261124-v1"
PUBLIC_ID = 1468905732


def main():
    pilot = Pilot(os.environ.pop("EMO_CI_TOKEN", None), public_id=PUBLIC_ID,
                  workflow_sha=MAIN, workflow_blob=BLOB, tag=TAG)
    pilot.verify_seed()
    repo = pilot.call(PUBLIC)
    ref = pilot.call(PUBLIC + "/git/ref/heads/main")
    file = pilot.call(PUBLIC + "/contents/" + WORKFLOW_PATH + "?ref=" + MAIN)
    if (repo.get("id") != PUBLIC_ID or repo.get("full_name") != "jsdfhasuh/emo_master_ci"
            or repo.get("default_branch") != "main" or ref.get("object", {}).get("sha") != MAIN
            or file.get("path") != WORKFLOW_PATH or file.get("sha") != BLOB):
        raise PilotError("approved public merge no longer matches")
    # Create only, never move a ref or duplicate a previously triggered exercise.
    created = pilot.call(PUBLIC + "/git/refs", payload={"ref": "refs/tags/" + TAG, "sha": MAIN}, status=201)
    if created.get("ref") != "refs/tags/" + TAG or created.get("object", {}).get("sha") != MAIN:
        raise PilotError("created tag did not match the pilot")
    print("pilot_ref_verified=yes", flush=True)
    pilot.execute(record=lambda line: print(line, flush=True))


if __name__ == "__main__":
    try:
        main()
    except PilotError as exc:
        print("pilot_not_verified: " + str(exc), flush=True)
        raise SystemExit(1) from None
