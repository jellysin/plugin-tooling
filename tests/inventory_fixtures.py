"""Small independently declared package/restore graphs for inventory boundary tests."""

import base64

from jellysin_tooling.common import json_bytes


def restore_files(root):
    hash_a = base64.b64encode(b"a" * 64).decode()
    hash_b = base64.b64encode(b"b" * 64).decode()
    lock = {
        "version": 1,
        "dependencies": {
            "net10.0": {
                "Host.API": {
                    "type": "Direct",
                    "resolved": "12.0.0",
                    "contentHash": hash_a,
                    "dependencies": {"Host.Data": "12.0.0"},
                },
                "Host.Data": {"type": "Transitive", "resolved": "12.0.0", "contentHash": hash_b},
            }
        },
    }
    assets = {
        "version": 4,
        "targets": {
            "net10.0": {
                "Host.API/12.0.0": {"type": "package", "dependencies": {"Host.Data": "12.0.0"}},
                "Host.Data/12.0.0": {"type": "package"},
            }
        },
        "libraries": {
            "Host.API/12.0.0": {"type": "package", "sha512": hash_a},
            "Host.Data/12.0.0": {"type": "package", "sha512": hash_b},
        },
        "packageFolders": {"/first/checkout/cache/": {}},
    }
    runtime = {
        "schemaVersion": 1,
        "targetFramework": "net10.0",
        "runtimeDependencies": [{"id": "Host.API", "version": "12.0.0", "providedBy": "jellyfin"}],
    }
    documents = [lock, assets, runtime, {"sdk": {"version": "10.0.400"}}]
    paths = [
        root / name
        for name in ("packages.lock.json", "project.assets.json", "runtime-dependencies.json", "global.json")
    ]
    for path, document in zip(paths, documents, strict=True):
        path.write_bytes(json_bytes(document))
    return paths, documents
