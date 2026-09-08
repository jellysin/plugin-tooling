"""Produce reproducible flat plugin archives and SPDX file inventories."""

import io
import zipfile
from pathlib import Path

from .common import MAX_ASSET, SHA, atomic_write, digest, json_bytes, metadata, require, semver, timestamp


def package_files(publish_directory, info):
    root = Path(publish_directory).resolve(strict=True)
    files = {}
    total = 0
    for name in sorted([info["assemblyFile"], *info.get("packageFiles", [])]):
        source = root / name
        require(not source.is_symlink(), "Symbolic links must not be packaged")
        require(source.resolve(strict=True).parent == root and source.is_file(), "Unsafe package path")
        with source.open("rb") as stream:
            contents = stream.read(MAX_ASSET + 1)
        total += len(contents)
        require(0 < len(contents) and total <= MAX_ASSET, "Empty or oversized plugin package")
        files[name] = contents
    return files


def archive_bytes(files):
    buffer = io.BytesIO()
    # Stored entries eliminate zlib/runtime differences. DLLs are small; reproducibility wins.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, contents in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, contents)
    require(len(buffer.getvalue()) <= MAX_ASSET, "ZIP exceeds asset limit")
    return buffer.getvalue()


def sbom(info, version, commit, created, files):
    package_id = "SPDXRef-Plugin"
    entries = [
        {
            "SPDXID": f"SPDXRef-File-{index}",
            "fileName": name,
            "checksums": [{"algorithm": "SHA256", "checksumValue": digest(data)}],
            "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
        for index, (name, data) in enumerate(sorted(files.items()))
    ]
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{info['name']} {version}",
        "documentNamespace": f"https://github.com/{info['repository']}/sbom/{version}/{commit}",
        "creationInfo": {"created": created, "creators": ["Tool: jellysin-plugin-tooling-1"]},
        "packages": [
            {
                "SPDXID": package_id,
                "name": info["name"],
                "versionInfo": version,
                "downloadLocation": f"https://github.com/{info['repository']}/releases/tag/v{version}",
                "filesAnalyzed": False,
                "licenseDeclared": "EUPL-1.2",
            }
        ],
        "files": entries,
        "relationships": [
            {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": package_id},
            *[
                {"spdxElementId": package_id, "relationshipType": "CONTAINS", "relatedSpdxElement": item["SPDXID"]}
                for item in entries
            ],
        ],
    }


def build(publish_directory, info, version, commit, created, output_directory):
    info = metadata(info)
    version = semver(version)
    require(isinstance(commit, str) and SHA.fullmatch(commit), "Expected full lowercase commit SHA")
    created = timestamp(created)
    files = package_files(publish_directory, info)
    archive = archive_bytes(files)
    name = f"{info['repository'].split('/')[1]}-{version}.zip"
    release = {
        "schemaVersion": 1,
        "plugin": info,
        "semver": version,
        "version": version + ".0",
        "tag": "v" + version,
        "commit": commit,
        "timestamp": created,
        "archive": {
            "name": name,
            "size": len(archive),
            "sha256": digest(archive),
            "md5": digest(archive, "md5"),
            "url": f"https://github.com/{info['repository']}/releases/download/v{version}/{name}",
        },
    }
    artifacts = {
        name: archive,
        "release.json": json_bytes(release),
        "sbom.spdx.json": json_bytes(sbom(info, version, commit, created, files)),
    }
    artifacts["checksums.txt"] = "".join(
        f"{digest(data)}  {filename}\n" for filename, data in sorted(artifacts.items())
    ).encode()
    for filename, contents in artifacts.items():
        target = Path(output_directory) / filename
        if target.exists():
            require(target.read_bytes() == contents, "Refusing to replace different release bytes")
        else:
            atomic_write(target, contents)
    return release
