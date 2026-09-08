"""Command line interface shared by local checks and composite Actions."""

import argparse
import os
import sys
from pathlib import Path

from . import catalog, package, policy, release
from .common import ValidationError, read_json, require
from .github import GitHub, command


def parser():
    root = argparse.ArgumentParser(description="JellySin deterministic releases and verified catalog updates")
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("package")
    build.add_argument("--publish-directory", required=True)
    build.add_argument("--metadata-path", default="plugin.json")
    build.add_argument("--version-path", default="version.txt")
    build.add_argument("--output-directory", default="dist")
    build.add_argument("--tag")
    publish = commands.add_parser("publish")
    publish.add_argument("--directory", default="dist")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--tag", required=True)
    publish.add_argument("--workflow", default=".github/workflows/release.yml")
    update = commands.add_parser("catalog")
    update.add_argument("--manifest", default="manifest.json")
    update.add_argument("--allowlist", default="plugins.json")
    validate = commands.add_parser("validate-catalog")
    validate.add_argument("--manifest", default="manifest.json")
    validate.add_argument("--allowlist", default="plugins.json")
    check = commands.add_parser("check-policy")
    check.add_argument("--directory", default=".")
    return root


def run(arguments):
    if arguments.command == "check-policy":
        policy.check_repository(arguments.directory)
        return
    if arguments.command == "package":
        commit = release.exact_tag(arguments.tag) if arguments.tag else command(["git", "rev-parse", "HEAD"])
        created = command(["git", "show", "-s", "--format=%cI", commit])
        version = Path(arguments.version_path).read_text(encoding="utf-8").strip()
        require(not arguments.tag or arguments.tag == "v" + version, "Tag does not match version.txt")
        result = package.build(
            arguments.publish_directory,
            read_json(arguments.metadata_path),
            version,
            commit,
            created,
            arguments.output_directory,
        )
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with Path(output).open("a", encoding="utf-8") as stream:
                stream.write(f"archive={Path(arguments.output_directory).resolve() / result['archive']['name']}\n")
                stream.write(f"directory={Path(arguments.output_directory).resolve()}\n")
        return
    if arguments.command == "publish":
        release.publish(GitHub(), arguments.directory, arguments.repo, arguments.tag, arguments.workflow)
        return
    current = catalog.validate_manifest(read_json(arguments.manifest))
    approved = catalog.allowlist(read_json(arguments.allowlist))
    require(
        {plugin["guid"] for plugin in current} <= {plugin["guid"] for plugin in approved},
        "Manifest contains an unapproved plugin",
    )
    repositories = {plugin["guid"]: plugin["repository"] for plugin in approved}
    for plugin in current:
        prefix = f"https://github.com/{repositories[plugin['guid']]}/releases/download/"
        require(
            all(version["sourceUrl"].startswith(prefix) for version in plugin["versions"]),
            "Catalog source differs from approved repository",
        )
    if arguments.command == "catalog":
        merged = catalog.collect(GitHub(), approved, current)
        catalog.update(arguments.manifest, current, merged)


def main():
    try:
        run(parser().parse_args())
    except ValidationError as exc:
        print(f"jellysin-tooling: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Validations contain controlled labels, never raw remote values or credential data.
        print(f"jellysin-tooling: {type(exc).__name__}: operation failed validation or I/O", file=sys.stderr)
        raise SystemExit(1) from None
