# Repository instructions

Read CONTRIBUTING.md before changing releases, branches, or workflow permissions.
All source here is build-time tooling. Installed Jellyfin plugins never import it.

- Keep production code Python standard-library-only. Pin development tools exactly with hashes.
- Every network response, asset, page count and external process needs a finite bound.
- Allow only reviewed HTTPS hosts. Never forward the API token to download redirects.
- Treat release metadata and ZIP contents as untrusted; validate before writing the plugin repository.
- Preserve published artifact bytes and plugin repository versions. Never add upload replacement flags.
- Verify provenance against the approved repository, workflow, source commit and tag.
- Limit functions to 120 lines, 60 statements and cyclomatic complexity 10.
- Test recovery, failure atomicity, and independent plugin identities.
- No broad exception swallowing, hidden retries, or raw API error logging.
- Fix Ruff and policy findings. Keep branch coverage at least 85% for these security-sensitive tools.
- Pin Actions to full SHAs, use read-only defaults and job-scoped writes, and explicitly dispatch bot CI.
- Conventional Commit PR titles, squash merges, release-please-owned versions, strict: false checks.
- Do not claim a GitHub setting or hosted check succeeded without live evidence.
