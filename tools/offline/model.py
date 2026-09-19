"""Data contracts shared by the qbox offline release tools."""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


_PAYLOAD_PART = re.compile(r"[A-Za-z0-9._+@=-]+")
_VERSION = re.compile(r"[0-9][A-Za-z0-9.+-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_PACKAGE_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_LICENSE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\[(?P<extras>[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*)\])?"
    r"==(?P<version>[0-9][A-Za-z0-9.+!-]*)"
)

_PLATFORM = {
    "os": "linux",
    "arch": "x86_64",
    "glibc_min": "2.28",
    "python_series": "3.12",
    "cpu_baseline": "x86_64",
}
_EXTRAS = ["analysis", "structure"]
_MANIFEST_FIELDS = {
    "schema_version",
    "product",
    "qbox_version",
    "platform",
    "extras",
    "source",
    "runtime",
    "wheels",
    "bootstrap_packages",
    "licenses",
    "files",
    "identity",
    "release_id",
}
_IDENTITY_FIELDS = {
    "qbox_version",
    "source_commit",
    "qbox_wheel_sha256",
    "runtime_sha256",
    "dependencies_lock_sha256",
    "build_requirements_lock_sha256",
    "installer_template_sha256",
    "launcher_template_sha256",
    "checks",
    "licenses",
}
_PAYLOAD_FIELDS = {"path", "size", "sha256", "source", "license_ids"}


def canonical_json(value: dict) -> bytes:
    """Serialize a mapping to the canonical byte form used for release hashes."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_payload_path(value: str) -> str:
    """Return a safe relative POSIX payload path or raise ``ValueError``."""
    if not isinstance(value, str):
        raise ValueError("payload path must be a string")
    parts = value.split("/")
    if not value or any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid relative payload path")
    if any(_PAYLOAD_PART.fullmatch(part) is None for part in parts):
        raise ValueError("unsupported archive member name")
    return value


def release_id(version: str, identity: dict) -> str:
    """Return the versioned digest for a canonical release identity."""
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ValueError("invalid version")
    return version + "-" + hashlib.sha256(canonical_json(identity)).hexdigest()


def _require_fields(value: object, required: set[str], context: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    missing = required - value.keys()
    if missing:
        raise ValueError(f"{context} missing {', '.join(sorted(missing))}")
    return value


def _require_exact_fields(value: object, expected: set[str], context: str) -> dict:
    result = _require_fields(value, expected, context)
    extra = result.keys() - expected
    if extra:
        raise ValueError(f"{context} has unsupported fields: {', '.join(sorted(extra))}")
    return result


def _validate_sha256(value: object, context: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{context} must be a lowercase SHA-256 digest")


def _validate_commit(value: object, context: str) -> None:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise ValueError(f"{context} must be a full lowercase Git commit")


def _validate_source(value: object, context: str) -> None:
    source = _require_fields(value, set(), context)
    if set(source) == {"commit"}:
        _validate_commit(source["commit"], f"{context}.commit")
        return
    if set(source) != {"url", "filename", "sha256"}:
        raise ValueError(f"{context} source must contain a commit or pinned HTTPS asset")
    url = source["url"]
    if not isinstance(url, str):
        raise ValueError(f"{context}.url must be a string")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in url
        or any(ord(character) < 0x20 for character in url)
    ):
        raise ValueError(f"{context} source URL must be public HTTPS without credentials")
    filename = source["filename"]
    if safe_payload_path(filename) != filename or "/" in filename:
        raise ValueError(f"{context}.filename must be a safe basename")
    _validate_sha256(source["sha256"], f"{context}.sha256")


def _validate_license_ids(value: object, context: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a non-empty list")
    if any(
        not isinstance(license_id, str)
        or _LICENSE_ID.fullmatch(license_id) is None
        for license_id in value
    ):
        raise ValueError(f"{context} contains an invalid license ID")
    if len(value) != len(set(value)):
        raise ValueError(f"{context} contains duplicate license IDs")


def validate_payload_files(files: list[dict]) -> None:
    """Validate safe paths, sizes and hashes for a payload inventory."""
    if not isinstance(files, list):
        raise ValueError("files must be a list")
    paths = set()
    for index, entry in enumerate(files):
        item = _require_fields(entry, {"path", "size", "sha256"}, f"files[{index}]")
        path = safe_payload_path(item["path"])
        if path in paths:
            raise ValueError(f"duplicate payload path: {path}")
        paths.add(path)
        size = item["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError(f"files[{index}].size must be a non-negative integer")
        _validate_sha256(item["sha256"], f"files[{index}].sha256")


def _validate_payload(value: object, context: str) -> dict:
    payload = _require_fields(value, _PAYLOAD_FIELDS, context)
    validate_payload_files([payload])
    _validate_source(payload["source"], f"{context}.source")
    _validate_license_ids(payload["license_ids"], f"{context}.license_ids")
    return payload


def _validate_requirement(value: object, name: object, version: object, context: str) -> None:
    if not isinstance(value, str) or _REQUIREMENT.fullmatch(value) is None:
        raise ValueError(f"{context} requirement must be one exact name==version pin")
    match = _REQUIREMENT.fullmatch(value)
    assert match is not None
    if match.group("name").lower().replace("_", "-") != name.lower().replace("_", "-"):
        raise ValueError(f"{context} requirement name does not match the wheel")
    if match.group("version") != version:
        raise ValueError(f"{context} requirement version does not match the wheel")
    extras = match.group("extras")
    if name.lower() == "qbox" and (extras is None or extras.split(",") != _EXTRAS):
        raise ValueError(f"{context} qbox requirement must enable both approved extras")


def _payload_matches_inventory(payload: dict, inventory: dict[str, dict], context: str) -> None:
    path = payload["path"]
    if path not in inventory:
        raise ValueError(f"{context} payload is missing from files: {path}")
    for field in _PAYLOAD_FIELDS:
        if inventory[path].get(field) != payload[field]:
            raise ValueError(f"{context}.{field} does not match files inventory")


def _validate_identity(
    identity_value: object,
    *,
    manifest: dict,
    inventory: dict[str, dict],
) -> None:
    identity = _require_exact_fields(identity_value, _IDENTITY_FIELDS, "identity")
    if identity["qbox_version"] != manifest["qbox_version"]:
        raise ValueError("identity.qbox_version does not match manifest")
    if identity["source_commit"] != manifest["source"]["commit"]:
        raise ValueError("identity.source_commit does not match source.commit")
    for field in _IDENTITY_FIELDS - {"qbox_version", "source_commit", "checks", "licenses"}:
        _validate_sha256(identity[field], f"identity.{field}")

    if identity["runtime_sha256"] != manifest["runtime"]["sha256"]:
        raise ValueError("identity.runtime_sha256 does not match runtime payload")
    qbox_wheels = [wheel for wheel in manifest["wheels"] if wheel["name"].lower() == "qbox"]
    if len(qbox_wheels) != 1:
        raise ValueError("wheels must contain exactly one qbox wheel")
    if qbox_wheels[0]["version"] != manifest["qbox_version"]:
        raise ValueError("qbox wheel version does not match qbox_version")
    if identity["qbox_wheel_sha256"] != qbox_wheels[0]["sha256"]:
        raise ValueError("identity.qbox_wheel_sha256 does not match qbox wheel")

    fixed_files = {
        "dependencies_lock_sha256": "requirements.lock",
        "build_requirements_lock_sha256": "checks/build-requirements.lock",
        "installer_template_sha256": "install.sh",
        "launcher_template_sha256": "checks/qbox-launcher.sh",
    }
    for field, path in fixed_files.items():
        if path not in inventory or identity[field] != inventory[path]["sha256"]:
            raise ValueError(f"identity.{field} does not match {path}")

    checks = _require_fields(identity["checks"], set(), "identity.checks")
    if not checks:
        raise ValueError("identity.checks must not be empty")
    expected_check_paths = {
        path
        for path in inventory
        if path.startswith("checks/") and path != "checks/qbox-launcher.sh"
    }
    if set(checks) != expected_check_paths:
        raise ValueError("identity.checks must cover every self-check payload")
    for path, digest in checks.items():
        safe_payload_path(path)
        if not path.startswith("checks/") or path == "checks/qbox-launcher.sh":
            raise ValueError("identity.checks contains a non-check payload")
        _validate_sha256(digest, f"identity.checks[{path}]")
        if path not in inventory or inventory[path]["sha256"] != digest:
            raise ValueError(f"identity.checks does not match {path}")

    licenses = _require_fields(identity["licenses"], set(), "identity.licenses")
    expected_license_paths = {
        path for paths in manifest["licenses"].values() for path in paths
    }
    if set(licenses) != expected_license_paths:
        raise ValueError("identity.licenses must cover the manifest license mapping")
    for path, digest in licenses.items():
        safe_payload_path(path)
        _validate_sha256(digest, f"identity.licenses[{path}]")
        if path not in inventory or inventory[path]["sha256"] != digest:
            raise ValueError(f"identity.licenses does not match {path}")


def validate_manifest(value: dict) -> None:
    """Validate a complete schema-version-1 offline release manifest."""
    manifest = _require_exact_fields(value, _MANIFEST_FIELDS, "manifest")
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported manifest schema_version")
    if manifest["product"] != "qbox":
        raise ValueError("manifest product must be qbox")
    if (
        not isinstance(manifest["qbox_version"], str)
        or _VERSION.fullmatch(manifest["qbox_version"]) is None
    ):
        raise ValueError("invalid qbox_version")
    if manifest["platform"] != _PLATFORM:
        raise ValueError("platform does not match the approved Linux x86_64 baseline")
    if manifest["extras"] != _EXTRAS:
        raise ValueError("extras must be analysis and structure")

    source = _require_exact_fields(manifest["source"], {"commit", "dirty"}, "source")
    _validate_commit(source["commit"], "source.commit")
    if source["dirty"] is not False:
        raise ValueError("source.dirty must be false")

    validate_payload_files(manifest["files"])
    inventory = {}
    for index, file_value in enumerate(manifest["files"]):
        file_entry = _require_exact_fields(file_value, _PAYLOAD_FIELDS, f"files[{index}]")
        _validate_payload(file_entry, f"files[{index}]")
        if file_entry["path"] in {
            "manifest.json",
            "SHA256SUMS",
        } or file_entry["path"].endswith(".sha256"):
            raise ValueError("files must exclude generated manifest/checksum/archive hashes")
        inventory[file_entry["path"]] = file_entry
    for required_path in (
        "install.sh",
        "requirements.lock",
        "checks/build-requirements.lock",
        "README.zh-CN.md",
        "LICENSE",
        "checks/qbox-launcher.sh",
    ):
        if required_path not in inventory:
            raise ValueError(f"files is missing required payload {required_path}")

    runtime_fields = _PAYLOAD_FIELDS | {"implementation", "version"}
    runtime = _require_exact_fields(manifest["runtime"], runtime_fields, "runtime")
    _validate_payload(runtime, "runtime")
    if runtime["implementation"] != "cpython":
        raise ValueError("runtime.implementation must be cpython")
    if not isinstance(runtime["version"], str) or not runtime["version"].startswith("3.12."):
        raise ValueError("runtime.version must be a CPython 3.12 patch release")
    if runtime["path"] != "runtime/python.tar.gz":
        raise ValueError("runtime.path must be runtime/python.tar.gz")
    _payload_matches_inventory(runtime, inventory, "runtime")

    wheels = manifest["wheels"]
    if not isinstance(wheels, list) or not wheels:
        raise ValueError("wheels must be a non-empty list")
    wheel_names = set()
    wheel_fields = _PAYLOAD_FIELDS | {"name", "version", "requirement"}
    for index, wheel_value in enumerate(wheels):
        context = f"wheels[{index}]"
        wheel = _require_exact_fields(wheel_value, wheel_fields, context)
        _validate_payload(wheel, context)
        if not isinstance(wheel["name"], str) or _PACKAGE_NAME.fullmatch(wheel["name"]) is None:
            raise ValueError(f"{context}.name is invalid")
        normalized_name = wheel["name"].lower().replace("_", "-")
        if normalized_name in wheel_names:
            raise ValueError(f"duplicate wheel name: {normalized_name}")
        wheel_names.add(normalized_name)
        expected_directory = "packages/" if normalized_name == "qbox" else "wheelhouse/"
        if not wheel["path"].startswith(expected_directory):
            raise ValueError(f"{context}.path must be under {expected_directory.rstrip('/')}")
        if not wheel["path"].endswith(".whl"):
            raise ValueError(f"{context}.path must name a wheel")
        if not isinstance(wheel["version"], str) or _VERSION.fullmatch(wheel["version"]) is None:
            raise ValueError(f"{context}.version is invalid")
        _validate_requirement(
            wheel["requirement"], wheel["name"], wheel["version"], context
        )
        _payload_matches_inventory(wheel, inventory, context)

    bootstrap_packages = manifest["bootstrap_packages"]
    if not isinstance(bootstrap_packages, list) or not bootstrap_packages:
        raise ValueError("bootstrap_packages must be a non-empty list")
    bootstrap_names = set()
    for index, package_value in enumerate(bootstrap_packages):
        context = f"bootstrap_packages[{index}]"
        package = _require_exact_fields(
            package_value, {"name", "version", "source", "license_ids"}, context
        )
        if (
            not isinstance(package["name"], str)
            or _PACKAGE_NAME.fullmatch(package["name"]) is None
        ):
            raise ValueError(f"{context}.name is invalid")
        normalized_name = package["name"].lower().replace("_", "-")
        if normalized_name in bootstrap_names:
            raise ValueError(f"duplicate bootstrap package: {normalized_name}")
        bootstrap_names.add(normalized_name)
        if (
            not isinstance(package["version"], str)
            or _VERSION.fullmatch(package["version"]) is None
        ):
            raise ValueError(f"{context}.version is invalid")
        _validate_source(package["source"], f"{context}.source")
        _validate_license_ids(package["license_ids"], f"{context}.license_ids")

    licenses = manifest["licenses"]
    if not isinstance(licenses, dict) or not licenses:
        raise ValueError("licenses must be a non-empty mapping")
    for license_id, paths in licenses.items():
        if not isinstance(license_id, str) or _LICENSE_ID.fullmatch(license_id) is None:
            raise ValueError("licenses contains an invalid license ID")
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(path, str) for path in paths)
            or len(paths) != len(set(paths))
        ):
            raise ValueError(f"licenses[{license_id}] must contain unique payload paths")
        for path in paths:
            safe_payload_path(path)
            if path not in inventory:
                raise ValueError(f"licenses[{license_id}] references missing payload {path}")
            if license_id not in inventory[path]["license_ids"]:
                raise ValueError(f"licenses[{license_id}] does not match payload {path}")

    mapped_license_ids = set(licenses)
    used_license_ids = {
        license_id
        for payload in manifest["files"]
        for license_id in payload["license_ids"]
    }
    used_license_ids.update(
        license_id
        for package in bootstrap_packages
        for license_id in package["license_ids"]
    )
    if not used_license_ids <= mapped_license_ids:
        raise ValueError("licenses mapping is missing payload or bootstrap license IDs")

    _validate_identity(
        manifest["identity"], manifest=manifest, inventory=inventory
    )
    expected_release_id = release_id(manifest["qbox_version"], manifest["identity"])
    if manifest["release_id"] != expected_release_id:
        raise ValueError("release_id does not match the canonical identity")
