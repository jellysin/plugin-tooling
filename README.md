# JellySin plugin tooling

Shared, versioned build and release tools for independent Jellyfin 12 plugins.
Python's standard library handles packaging and catalog validation; GitHub CLI
verifies signed provenance and performs repository-scoped publication. None of
this tooling is loaded by an installed plugin.

## Plugin descriptor

Each plugin supplies `plugin.json`, a three-part `version.txt`, and a directory of
build outputs. The descriptor records `guid`, `name`, `description`, `overview`,
`owner`, `category`, `targetAbi`, `assemblyFile`, and `repository`. Optional
`packageFiles` names additional plugin-owned files explicitly. Paths are flat,
unique and bounded; host-provided assembly names are rejected.

```sh
python tools.py package --publish-directory artifacts/plugin --tag v1.0.0
```

Output: plugin ZIP, `release.json`, `checksums.txt` (SHA-256), and SPDX 2.3 file
inventory. MD5 is included solely for Jellyfin's catalog format. The SBOM inventories
shipped files and leaves unverified file licenses as `NOASSERTION`; it does not
invent transitive dependency licenses.

ZIP order, permissions, timestamp and storage are deterministic. Stored compression
avoids deflate runtime differences. The plugin DLL must itself be built
deterministically. Limits: 32 files, 64 MiB per package, 4 MiB JSON, 90-second downloads.

## GitHub Actions

Consume `actions/package`, `actions/publish`, or `actions/catalog` at a reviewed
full commit SHA. Actions use their own downloaded directory; callers do not copy
scripts or check out a mutable tooling branch.

The package action accepts `publish-directory`, `metadata-path`, `version-path`,
`output-directory` and optional exact `tag`; it outputs `archive` and `directory`.
Attest **all four artifacts** using `actions/attest` in the plugin's tag-dispatched
`.github/workflows/release.yml`, then call `actions/publish` with `directory`, `tag`
and the built-in `token`. Shared release automation explicitly dispatches bot PR CI
and exact-tag publication.

## Catalog trust and recovery

Only allowlisted public releases are accepted. Every new artifact needs valid
signatures bound to the repository, approved workflow, source SHA, exact tag and
GitHub-hosted runner. Metadata, checksums, ZIP entries and SBOM format are validated
before the catalog changes. Existing catalog versions are preserved.

Scans are bounded to 32 repositories, 1,000 releases per repository, and 20 new
versions per batch; remaining releases follow after that catalog PR merges.
Drafts and prereleases are skipped. Failed or over-limit scans
leave the catalog unchanged; resolve the source problem and rerun. Already listed
versions are not re-downloaded each poll; source repositories must enable immutable
releases. Catalog changes go through PRs.

EUPL-1.2 covers this source. License text comes from the SPDX license list;
third-party Actions retain their own licenses. See CONTRIBUTING.md for validation.
