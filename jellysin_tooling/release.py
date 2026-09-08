"""Exact-tag, resumable publication: upload missing bytes, never replace assets."""

import os
from pathlib import Path

from . import spdx
from .catalog import release_assets, validate_archive, validate_release
from .common import MAX_ASSET, SHA, decode_json, digest, read_json, repository, require, semver
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
    members = validate_archive(files[release["archive"]["name"]], release)
    spdx.validate(decode_json(files["sbom.spdx.json"]), release, members)
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


def draft_starters(remote, files, repo, tag):
    assets = remote.get("assets")
    require(isinstance(assets, list) and len(assets) <= 32, "Invalid release assets")
    pending = []
    uploaded = []
    for asset in assets:
        require(isinstance(asset, dict), "Invalid release asset")
        if asset.get("state") != "starter":
            uploaded.append(asset)
            continue
        require(remote.get("draft") is True, "Never remove a published release asset")
        require(
            asset.get("name") in files and type(asset.get("size")) is int and asset["size"] == 0,
            "Unexpected incomplete draft asset",
        )
        require(type(asset.get("id")) is int and asset["id"] > 0, "Invalid incomplete asset ID")
        release_assets({"assets": [{**asset, "state": "uploaded", "size": 1}]}, repo, tag)
        pending.append(asset)
    require(len({asset["name"] for asset in assets}) == len(assets), "Duplicate release asset")
    return {**remote, "assets": uploaded}, pending


def remove_draft_starters(client, pending, repo, tag, runner):
    for asset in pending:
        current = client.api(f"repos/{repo}/releases/tags/{tag}")
        require(current.get("draft") is True, "Release is no longer a draft")
        matches = [entry for entry in current.get("assets", []) if entry.get("id") == asset["id"]]
        require(len(matches) == 1 and matches[0] == asset, "Incomplete draft asset changed before recovery")
        # GitHub documents zero-byte starter assets after failed uploads as safe to delete.
        runner(["gh", "api", "--method", "DELETE", f"repos/{repo}/releases/assets/{asset['id']}"])


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
    remote, pending = draft_starters(remote, files, repo, tag)
    missing = reconcile_assets(client, remote, files, repo, tag)
    remove_draft_starters(client, pending, repo, tag, runner)
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
