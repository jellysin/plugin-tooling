"""Exact-tag, resumable publication: upload missing bytes, never replace assets."""

import os
from pathlib import Path

from .catalog import release_assets, validate_archive, validate_release
from .common import MAX_ASSET, SHA, digest, read_json, repository, require, semver
from .github import command, verify_attestation


def exact_tag(tag, cwd=None):
    require(isinstance(tag, str) and tag.startswith("v"), "Release tag must start with v")
    semver(tag[1:])
    head = command(["git", "rev-parse", "HEAD"], cwd)
    require(SHA.fullmatch(head), "Invalid checkout commit")
    tagged = command(["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"], cwd)
    require(head == tagged, "Checkout does not match exact release tag")
    command(["git", "diff", "--exit-code", "HEAD", "--"], cwd)
    return head


def remote_tag(client, repo, tag):
    obj = client.api(f"repos/{repo}/git/ref/tags/{tag}").get("object", {})
    for _depth in range(5):
        require(isinstance(obj.get("sha"), str) and SHA.fullmatch(obj["sha"]), "Invalid remote tag object")
        if obj.get("type") == "commit":
            return obj["sha"]
        require(obj.get("type") == "tag", "Remote tag does not identify a commit")
        obj = client.api(f"repos/{repo}/git/tags/{obj['sha']}").get("object", {})
    raise ValueError("Annotated tag nesting exceeds limit")


def local_artifacts(directory, release):
    root = Path(directory).resolve(strict=True)
    names = {release["archive"]["name"], "release.json", "sbom.spdx.json", "checksums.txt"}
    files = {}
    for name in names:
        path = root / name
        require(
            path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_ASSET,
            "Missing or unsafe release artifact",
        )
        files[name] = path.read_bytes()
    validate_archive(files[release["archive"]["name"]], release)
    checksums = "".join(
        f"{digest(data)}  {name}\n" for name, data in sorted(files.items()) if name != "checksums.txt"
    ).encode()
    require(files["checksums.txt"] == checksums, "Local release checksum manifest mismatch")
    return files


def reconcile_assets(client, remote, files, repo, tag):
    assets = release_assets(remote, repo, tag)
    require(assets.keys() <= files.keys(), "Unexpected assets on release")
    missing = []
    for name, data in sorted(files.items()):
        if name not in assets:
            require(remote.get("draft") is True, "Published release is incomplete; do not mutate it")
            missing.append(name)
            continue
        require(assets[name]["size"] == len(data), "Existing asset differs; use a new release version")
        remote_bytes = client.download_asset(repo, assets[name]["id"])
        require(remote_bytes == data, "Existing asset differs; use a new release version")
    return missing


def publish(client, directory, repo, tag, workflow, verifier=verify_attestation, runner=command):
    repository(repo)
    require(workflow == ".github/workflows/release.yml", "Unapproved publisher workflow")
    commit = exact_tag(tag)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        require(os.environ.get("GITHUB_REF") == "refs/tags/" + tag, "Publication must run on the tag ref")
        require(
            os.environ.get("GITHUB_REPOSITORY") == repo and os.environ.get("GITHUB_SHA") == commit,
            "Workflow source differs from release",
        )
    release = read_json(Path(directory) / "release.json")
    approved = {"repository": repo, "guid": release.get("plugin", {}).get("guid")}
    validate_release(release, approved, tag)
    require(release["commit"] == commit == remote_tag(client, repo, tag), "Local, remote and metadata commits differ")
    files = local_artifacts(directory, release)
    for name in sorted(files):
        verifier(Path(directory) / name, repo, workflow, commit, tag)
    remote = client.api(f"repos/{repo}/releases/tags/{tag}")
    require(remote.get("tag_name") == tag and not remote.get("prerelease"), "Unexpected release state")
    missing = reconcile_assets(client, remote, files, repo, tag)
    for name in missing:
        runner(["gh", "release", "upload", tag, str(Path(directory) / name), "--repo", repo])
    refreshed = client.api(f"repos/{repo}/releases/tags/{tag}")
    require(not reconcile_assets(client, refreshed, files, repo, tag), "Release upload is incomplete")
    if refreshed.get("draft") is True:
        runner(["gh", "release", "edit", tag, "--repo", repo, "--draft=false", "--latest=true"])
    published = client.api(f"repos/{repo}/releases/tags/{tag}")
    require(
        published.get("draft") is False and published.get("immutable") is True,
        "Published release must be immutable; enable repository immutable releases before publishing",
    )
    return release
