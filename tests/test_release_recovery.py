"""Opt-in recovery preserves original tag provenance and truthful workflow identity."""

import os
from unittest.mock import Mock, call, patch

from jellysin_tooling.common import ValidationError
from jellysin_tooling.release import publication_context, publish
from tests.fixtures import COMMIT, FIRST, FakeGitHub, Workspace

REPO = FIRST["repository"]
TAG = "v1.0.0"
MAIN = "b" * 40
WORKFLOW = ".github/workflows/release.yml"
CONTEXT = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_REPOSITORY": REPO,
    "GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/recover-release.yml@refs/heads/main",
    "GITHUB_SHA": MAIN,
    "GITHUB_WORKFLOW_SHA": MAIN,
}


class VerifiedRecoveryTests(Workspace):
    def test_recovery_uses_original_four_attestations_before_mutation_and_retries_idempotently(self):
        release, output = self.plugin()
        client = FakeGitHub()
        remote = client.add(FIRST, release, output, draft=True)
        verifier = Mock()
        writes = []

        def runner(arguments):
            self.assertEqual(4, verifier.call_count)
            writes.append(arguments)
            remote.update(draft=False, immutable=True)

        with (
            patch.dict(os.environ, CONTEXT),
            patch("jellysin_tooling.release.exact_tag", return_value=COMMIT),
            patch("jellysin_tooling.release.command") as ancestry,
        ):
            for _ in range(2):
                self.assertEqual(
                    release,
                    publish(client, output, REPO, TAG, WORKFLOW, verifier, runner, verified_tag_recovery=True),
                )
        self.assertEqual(1, len(writes))
        self.assertEqual(8, verifier.call_count)
        self.assertEqual(
            [
                call(output / name, REPO, WORKFLOW, COMMIT, TAG)
                for name in sorted(path.name for path in output.iterdir())
            ]
            * 2,
            verifier.call_args_list,
        )
        self.assertEqual(
            [
                call(["git", "merge-base", "--is-ancestor", COMMIT, MAIN]),
                call(["git", "merge-base", "--is-ancestor", COMMIT, "refs/remotes/origin/main"]),
            ]
            * 2,
            ancestry.call_args_list,
        )

    def test_recovery_rejects_each_missing_or_forged_context_before_reads_or_writes(self):
        release, output = self.plugin()
        wrong = {
            "GITHUB_ACTIONS": "false",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/unreviewed",
            "GITHUB_REPOSITORY": "other/repository",
            "GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/release.yml@refs/heads/main",
            "GITHUB_SHA": "not-a-commit",
            "GITHUB_WORKFLOW_SHA": "c" * 40,
        }
        for key, value in wrong.items():
            for invalid in (value, ""):
                with self.subTest(key=key, value=invalid):
                    client, verifier, runner = Mock(), Mock(), Mock()
                    with (
                        patch.dict(os.environ, {**CONTEXT, key: invalid}),
                        patch("jellysin_tooling.release.exact_tag", return_value=COMMIT),
                        patch("jellysin_tooling.release.command") as ancestry,
                        self.assertRaises(ValidationError),
                    ):
                        publish(
                            client, output, REPO, release["tag"], WORKFLOW, verifier, runner, verified_tag_recovery=True
                        )
                    ancestry.assert_not_called()
                    client.api.assert_not_called()
                    verifier.assert_not_called()
                    runner.assert_not_called()

    def test_nonancestor_tag_fails_against_both_workflow_commit_and_remote_main(self):
        for successful_checks in (0, 1):
            with (
                self.subTest(successful_checks=successful_checks),
                patch.dict(os.environ, CONTEXT),
                patch(
                    "jellysin_tooling.release.command",
                    side_effect=[""] * successful_checks + [ValidationError("nonancestor")],
                ),
                self.assertRaisesRegex(ValidationError, "nonancestor"),
            ):
                publication_context(REPO, TAG, COMMIT, True)

    def test_any_original_artifact_provenance_failure_blocks_all_mutations(self):
        release, output = self.plugin()
        for successful_verifications in range(4):
            with self.subTest(successful_verifications=successful_verifications):
                client = FakeGitHub()
                client.add(FIRST, release, output, draft=True)
                verifier = Mock(side_effect=[None] * successful_verifications + [ValidationError("forged provenance")])
                runner = Mock()
                with (
                    patch.dict(os.environ, CONTEXT),
                    patch("jellysin_tooling.release.exact_tag", return_value=COMMIT),
                    patch("jellysin_tooling.release.command"),
                    self.assertRaisesRegex(ValidationError, "forged provenance"),
                ):
                    publish(client, output, REPO, TAG, WORKFLOW, verifier, runner, verified_tag_recovery=True)
                runner.assert_not_called()
                self.assertFalse(any("/releases" in path for path in client.calls))

    def test_recovery_still_rejects_different_local_remote_or_metadata_commit(self):
        _, output = self.plugin()
        for local, remote in (("c" * 40, COMMIT), (COMMIT, "c" * 40)):
            verifier, runner = Mock(), Mock()
            with (
                self.subTest(local=local, remote=remote),
                patch.dict(os.environ, CONTEXT),
                patch("jellysin_tooling.release.exact_tag", return_value=local),
                patch("jellysin_tooling.release.command"),
                patch("jellysin_tooling.release.remote_tag", return_value=remote),
                self.assertRaisesRegex(ValidationError, "commits differ"),
            ):
                publish(Mock(), output, REPO, TAG, WORKFLOW, verifier, runner, verified_tag_recovery=True)
            verifier.assert_not_called()
            runner.assert_not_called()

    def test_normal_publication_keeps_tag_context_and_does_not_accept_recovery_main(self):
        with patch.dict(os.environ, CONTEXT), self.assertRaisesRegex(ValidationError, "tag ref"):
            publication_context(REPO, TAG, COMMIT, False)
        with (
            patch.dict(os.environ, {**CONTEXT, "GITHUB_REF": f"refs/tags/{TAG}", "GITHUB_SHA": COMMIT}),
            patch("jellysin_tooling.release.command") as ancestry,
        ):
            publication_context(REPO, TAG, COMMIT, False)
        ancestry.assert_not_called()
