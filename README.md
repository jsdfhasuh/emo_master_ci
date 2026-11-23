# emo_master_ci

Public Actions pilot using an independent synthetic Python project. It does not
fetch or run product code, contact the product repository, or require secrets.
The Linux/Windows matrix tests only this repository. It is not an EmoMaster
release or product check; it cannot authorize a merge or a release.

Run locally with Python 3.10:
`python -m unittest discover -s tests -v`.

The hosted runner smoke workflow runs on pushes to the pilot branch; the manual dispatch entry
is available only after the workflow exists on the default branch. It publishes only the synthetic result; no artifact or
dependency cache is uploaded.
