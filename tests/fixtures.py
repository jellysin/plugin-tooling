"""Two independent plugins ensure tooling has no Last.fm-specific assumptions."""

import copy
import tempfile
import unittest
from pathlib import Path

from jellysin_tooling.package import build

FIRST = {
    "guid": "2034650d-a290-4a16-b195-89fb44cfb932",
    "name": "JellySin Last.fm",
    "description": "Music integration",
    "overview": "Scrobbling and discovery",
    "owner": "JellySin",
    "category": "Music",
    "targetAbi": "12.0.0.0",
    "assemblyFile": "JellySin.Plugin.Lastfm.dll",
    "repository": "jellysin/jellyfin-plugin-lastfm",
}
SECOND = {
    **FIRST,
    "guid": "c951d02c-b9c5-4e6a-b39c-f336e5d18891",
    "name": "JellySin Cinema",
    "category": "Movies",
    "assemblyFile": "JellySin.Plugin.Cinema.dll",
    "repository": "jellysin/cinema",
}
COMMIT = "a" * 40
CREATED = "2026-09-08T12:00:00Z"


def approved(info=FIRST):
    return {"guid": info["guid"], "repository": info["repository"], "signerWorkflow": ".github/workflows/release.yml"}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def plugin(self, info=FIRST, version="1.0.0", contents=b"MZplugin fixture"):
        source = self.root / info["name"] / version / "publish"
        source.mkdir(parents=True, exist_ok=True)
        (source / info["assemblyFile"]).write_bytes(contents)
        output = source.parent / "dist"
        release = build(source, copy.deepcopy(info), version, COMMIT, CREATED, output)
        return release, output


class FakeGitHub:
    def __init__(self):
        self.releases = {}
        self.downloads = {}
        self.assets = {}
        self.calls = []

    def add(self, info, release, output, draft=False):
        repo = info["repository"]
        remote = {"tag_name": release["tag"], "draft": draft, "prerelease": False, "immutable": not draft, "assets": []}
        for index, file in enumerate(sorted(output.iterdir()), 1):
            url = f"https://github.com/{repo}/releases/download/{release['tag']}/{file.name}"
            contents = file.read_bytes()
            remote["assets"].append(
                {
                    "id": index,
                    "name": file.name,
                    "state": "uploaded",
                    "size": len(contents),
                    "browser_download_url": url,
                }
            )
            self.downloads[url] = contents
            self.assets[repo, index] = contents
        self.releases.setdefault(repo, []).append(remote)
        return remote

    def api(self, path):
        self.calls.append(path)
        for repo, releases in self.releases.items():
            if path.startswith(f"repos/{repo}/releases?"):
                return releases
            if path.startswith(f"repos/{repo}/releases/tags/"):
                return releases[0]
            if path.startswith(f"repos/{repo}/git/ref/"):
                return {"object": {"type": "commit", "sha": COMMIT}}
        raise AssertionError("Unexpected API call")

    def download(self, url):
        self.calls.append(url)
        return self.downloads[url]

    def download_asset(self, repo, asset_id):
        return self.assets[repo, asset_id]
