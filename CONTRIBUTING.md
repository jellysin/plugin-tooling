# Contributing

Develop on a feature branch from main and submit a pull request with a Conventional
Commit title. Squash merging keeps release notes attributable to reviewed changes.
Required checks use `strict: false`; merging does not require an up-to-date branch.

## Validate locally

Use Python 3.14.7, pinned in `.python-version`. Production code supports Python 3.13
and newer and needs no pip installation. Development dependencies are pinned and
hash checked:

```sh
python -m pip install --require-hashes -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m coverage run -m unittest discover -s tests
python -m coverage report
python tools.py check-policy
actionlint
```

Coverage must reach 85%, including branches. Tests use two plugin identities and
temporary directories; they do not publish releases. Record unavailable validation.

## Release contract

Release-please owns versions, tags and changelogs. Tags use stable three-part SemVer.
Consumers pin Actions or reusable workflows to a full commit SHA and annotate the
release version for Renovate.

Plugin release-please creates a draft and forces tag creation, then explicitly
dispatches `release.yml` **on the tag ref**. Checking out a tag from a main-triggered
workflow does not change the OIDC source identity. Publication validates the exact
tag commit, attests every artifact, verifies existing bytes, uploads missing draft
assets, rechecks the complete draft, then publishes. Retry on the same tag. A
mismatch needs a new version; an incomplete published release is never repaired.

Use only the calling repository's GITHUB_TOKEN. Catalog publication runs in the
catalog repository and opens its own PR. No cross-repository write token, release
App, runtime package, or installed plugin dependency is required.

Workflow defaults are read-only. Writes belong to the narrow jobs that need them.
Bot CI explicitly dispatches the PR branch. No workflow assumes a token-created
event will recursively trigger another workflow.
