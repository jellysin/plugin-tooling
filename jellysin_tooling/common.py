"""Bounded input validation shared by packaging and publication."""

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

MAX_JSON = 4 * 1024 * 1024
MAX_ASSET = 64 * 1024 * 1024
MAX_FILES = 32
MAX_RELEASES = 1000
REPOSITORY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}")
SHA = re.compile(r"[0-9a-f]{40}")
SEMVER = re.compile(r"(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})")
HOST_PREFIXES = ("system.", "microsoft.", "jellyfin.", "emby.", "mediabrowser.")


class ValidationError(ValueError):
    """Input is invalid or violates release policy."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def text(value, name, limit=4096):
    require(isinstance(value, str) and 0 < len(value) <= limit, f"Invalid {name}")
    require(not any(ord(char) < 32 for char in value), f"Control character in {name}")
    return value


def repository(value):
    require(isinstance(value, str) and REPOSITORY.fullmatch(value), "Invalid repository")
    return value


def semver(value):
    require(isinstance(value, str) and SEMVER.fullmatch(value), "Expected stable x.y.z version")
    require(all(int(part) <= 65534 for part in value.split(".")), "Version exceeds assembly limit")
    return value


def filename(value):
    text(value, "filename", 160)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value), "Unsafe filename")
    require(".." not in value and value[-1] != ".", "Unsafe filename")
    return value


def timestamp(value):
    text(value, "timestamp", 40)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("Invalid timestamp") from exc
    require(parsed.tzinfo is not None, "Timestamp must include timezone")
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def decode_json(data, limit=MAX_JSON):
    require(len(data) <= limit, "JSON exceeds size limit")
    try:
        return json.loads(data, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Invalid JSON") from exc


def reject_constant(_value):
    raise ValidationError("Non-finite JSON number")


def read_json(path):
    with Path(path).open("rb") as stream:
        return decode_json(stream.read(MAX_JSON + 1))


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def digest(data, algorithm="sha256"):
    return hashlib.new(algorithm, data, usedforsecurity=algorithm not in ("md5", "sha1")).hexdigest()


def metadata(value):
    require(isinstance(value, dict), "Plugin metadata must be an object")
    required = {
        "guid",
        "name",
        "description",
        "overview",
        "owner",
        "category",
        "targetAbi",
        "assemblyFile",
        "repository",
    }
    require(required <= value.keys() <= required | {"packageFiles"}, "Unexpected metadata fields")
    for key in ("name", "description", "overview", "owner", "category"):
        text(value[key], key)
    try:
        require(str(UUID(value["guid"])) == value["guid"], "GUID must be canonical lowercase UUID")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Invalid GUID") from exc
    repository(value["repository"])
    require(
        re.fullmatch(r"12\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.0", value["targetAbi"] or ""),
        "Only Jellyfin 12 ABI supported",
    )
    require(all(int(part) <= 65534 for part in value["targetAbi"].split(".")), "ABI exceeds assembly limit")
    assembly = filename(value["assemblyFile"])
    require(assembly.endswith(".dll"), "Main assembly must be a DLL")
    files = value.get("packageFiles", [])
    require(isinstance(files, list) and len(files) < MAX_FILES, "Too many package files")
    names = [assembly, *files]
    for name in names:
        filename(name)
        require(not name.lower().startswith(HOST_PREFIXES), "Host-provided files must not be packaged")
    require(len({name.casefold() for name in names}) == len(names), "Duplicate package filename")
    return value
