"""Offline release model contracts."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.offline.model import (
    canonical_json,
    release_id,
    safe_payload_path,
    sha256_file,
    validate_manifest,
    validate_payload_files,
)


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
COMMIT = "d" * 40
ROOT = Path(__file__).resolve().parents[2]


def payload(path, digest, *, license_ids, source=None, size=1):
    return {
        "path": path,
        "size": size,
        "sha256": digest,
        "source": source or {"commit": COMMIT},
        "license_ids": license_ids,
    }


def complete_manifest():
    runtime = payload(
        "runtime/python.tar.gz",
        HEX_A,
        size=101,
        source={
            "url": "https://example.org/python/cpython.tar.zst",
            "filename": "cpython.tar.zst",
            "sha256": HEX_B,
        },
        license_ids=["Python-2.0"],
    )
    runtime.update(implementation="cpython", version="3.12.12")
    qbox_wheel = payload(
        "packages/qbox-0.1.0-py3-none-any.whl",
        HEX_B,
        size=202,
        license_ids=["MIT"],
    )
    qbox_wheel.update(
        name="qbox",
        version="0.1.0",
        requirement="qbox[analysis,structure]==0.1.0",
    )
    dependency_wheel = payload(
        "wheelhouse/demo-1.2.3-py3-none-any.whl",
        HEX_C,
        size=303,
        source={
            "url": "https://files.pythonhosted.org/demo-1.2.3.whl",
            "filename": "demo-1.2.3-py3-none-any.whl",
            "sha256": HEX_C,
        },
        license_ids=["BSD-3-Clause"],
    )
    dependency_wheel.update(
        name="demo", version="1.2.3", requirement="demo==1.2.3"
    )
    project_files = [
        payload("install.sh", hashlib.sha256(b"install").hexdigest(), license_ids=["MIT"]),
        payload(
            "checks/qbox-launcher.sh",
            hashlib.sha256(b"launcher").hexdigest(),
            license_ids=["MIT"],
        ),
        payload(
            "checks/smoke.py",
            hashlib.sha256(b"smoke").hexdigest(),
            license_ids=["MIT"],
        ),
        payload(
            "requirements.lock",
            hashlib.sha256(b"requirements").hexdigest(),
            license_ids=["MIT"],
        ),
        payload(
            "checks/build-requirements.lock",
            hashlib.sha256(b"build requirements").hexdigest(),
            license_ids=["MIT"],
        ),
        payload(
            "README.zh-CN.md",
            hashlib.sha256(b"readme").hexdigest(),
            license_ids=["MIT"],
        ),
        payload("LICENSE", hashlib.sha256(b"mit").hexdigest(), license_ids=["MIT"]),
        payload(
            "THIRD_PARTY_LICENSES/cpython/LICENSE.txt",
            hashlib.sha256(b"python").hexdigest(),
            license_ids=["Python-2.0"],
            source={
                "url": "https://python.org/ftp/python/3.12.12/LICENSE",
                "filename": "LICENSE",
                "sha256": hashlib.sha256(b"python").hexdigest(),
            },
        ),
        payload(
            "THIRD_PARTY_LICENSES/demo/LICENSE.txt",
            hashlib.sha256(b"demo").hexdigest(),
            license_ids=["BSD-3-Clause"],
            source={
                "url": "https://example.org/demo/LICENSE.txt",
                "filename": "LICENSE.txt",
                "sha256": hashlib.sha256(b"demo").hexdigest(),
            },
        ),
    ]
    identity = {
        "qbox_version": "0.1.0",
        "source_commit": COMMIT,
        "qbox_wheel_sha256": HEX_B,
        "runtime_sha256": HEX_A,
        "dependencies_lock_sha256": next(
            item["sha256"]
            for item in project_files
            if item["path"] == "requirements.lock"
        ),
        "build_requirements_lock_sha256": next(
            item["sha256"]
            for item in project_files
            if item["path"] == "checks/build-requirements.lock"
        ),
        "installer_template_sha256": project_files[0]["sha256"],
        "launcher_template_sha256": project_files[1]["sha256"],
        "checks": {
            item["path"]: item["sha256"]
            for item in project_files
            if item["path"].startswith("checks/")
            and item["path"] != "checks/qbox-launcher.sh"
        },
        "licenses": {
            item["path"]: item["sha256"]
            for item in project_files
            if item["path"] == "LICENSE"
            or item["path"].startswith("THIRD_PARTY_LICENSES/")
        },
    }
    manifest = {
        "schema_version": 1,
        "product": "qbox",
        "qbox_version": "0.1.0",
        "platform": {
            "os": "linux",
            "arch": "x86_64",
            "glibc_min": "2.28",
            "python_series": "3.12",
            "cpu_baseline": "x86_64",
        },
        "extras": ["analysis", "structure"],
        "source": {"commit": COMMIT, "dirty": False},
        "runtime": runtime,
        "wheels": [qbox_wheel, dependency_wheel],
        "bootstrap_packages": [
            {
                "name": "pip",
                "version": "25.2",
                "source": {
                    "url": "https://files.pythonhosted.org/pip-25.2.whl",
                    "filename": "pip-25.2-py3-none-any.whl",
                    "sha256": hashlib.sha256(b"pip").hexdigest(),
                },
                "license_ids": ["MIT"],
            }
        ],
        "licenses": {
            "MIT": ["LICENSE"],
            "Python-2.0": ["THIRD_PARTY_LICENSES/cpython/LICENSE.txt"],
            "BSD-3-Clause": ["THIRD_PARTY_LICENSES/demo/LICENSE.txt"],
        },
        "files": [
            {
                field: item[field]
                for field in ("path", "size", "sha256", "source", "license_ids")
            }
            for item in (runtime, qbox_wheel, dependency_wheel, *project_files)
        ],
        "identity": identity,
    }
    manifest["release_id"] = release_id(manifest["qbox_version"], identity)
    return manifest


class ModelTests(unittest.TestCase):
    def test_identity_is_stable_and_payload_sensitive(self):
        left = {"qbox_version": "0.1.0", "runtime_sha256": "a" * 64}
        self.assertEqual(
            canonical_json(left),
            b'{"qbox_version":"0.1.0","runtime_sha256":"' + b"a" * 64 + b'"}\n',
        )
        self.assertEqual(
            canonical_json(left),
            canonical_json(dict(reversed(list(left.items())))),
        )
        self.assertEqual(release_id("0.1.0", left), release_id("0.1.0", left))
        self.assertNotEqual(
            release_id("0.1.0", left),
            release_id("0.1.0", dict(left, runtime_sha256="b" * 64)),
        )

    def test_archive_paths_are_not_install_prefixes(self):
        self.assertEqual(
            safe_payload_path("runtime/python.tar.gz"),
            "runtime/python.tar.gz",
        )
        for bad in ("/x", "../x", "a/../x", "a//x", "a\\b", "x\ny", "./x", ""):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                safe_payload_path(bad)

    def test_sha256_file_hashes_bytes_without_loading_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(b"qbox offline\x00payload")
            self.assertEqual(
                sha256_file(path),
                "b2040abbafe048d456e7ee73d2175758ec7ee06a54d6f1c0b08acdc8e83adb41",
            )

    def test_payload_inventory_rejects_duplicate_and_malformed_entries(self):
        entry = {
            "path": "checks/probe.txt",
            "size": 1,
            "sha256": hashlib.sha256(b"x").hexdigest(),
        }
        validate_payload_files([entry])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_payload_files([entry, dict(entry)])
        for field, value in (("path", "../x"), ("size", -1), ("size", True), ("sha256", "A" * 64)):
            invalid = dict(entry, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_payload_files([invalid])

    def test_complete_manifest_is_valid(self):
        validate_manifest(complete_manifest())

    def test_manifest_rejects_missing_contract_sections(self):
        for field in ("platform", "extras", "runtime", "licenses"):
            manifest = complete_manifest()
            del manifest[field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                validate_manifest(manifest)

    def test_manifest_rejects_malformed_license_collections_with_value_error(self):
        manifest = complete_manifest()
        manifest["files"][0]["license_ids"] = [{"not": "an ID"}]
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

        manifest = complete_manifest()
        manifest["licenses"]["MIT"] = [{"not": "a path"}]
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_manifest_rejects_unknown_schema_and_duplicate_payload(self):
        manifest = complete_manifest()
        manifest["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "schema_version"):
            validate_manifest(manifest)

        manifest = complete_manifest()
        manifest["files"].append(copy.deepcopy(manifest["files"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_manifest(manifest)

    def test_manifest_requires_exact_platform_extras_and_clean_source(self):
        mutations = (
            ("platform", "glibc_min", "2.29"),
            ("platform", "python_series", "3.13"),
            ("platform", "cpu_baseline", "x86_64_v3"),
            ("source", "dirty", True),
        )
        for section, field, value in mutations:
            manifest = complete_manifest()
            manifest[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                validate_manifest(manifest)

        manifest = complete_manifest()
        manifest["extras"] = ["analysis"]
        with self.assertRaisesRegex(ValueError, "extras"):
            validate_manifest(manifest)

    def test_manifest_rejects_url_requirements_and_local_source_leaks(self):
        manifest = complete_manifest()
        manifest["wheels"][1]["requirement"] = "demo @ https://example.org/demo.whl"
        with self.assertRaisesRegex(ValueError, "requirement"):
            validate_manifest(manifest)

        for source in (
            {"url": "file:///home/alice/demo.whl", "filename": "demo.whl", "sha256": HEX_A},
            {"url": "https://alice@example.org/demo.whl", "filename": "demo.whl", "sha256": HEX_A},
            {"path": "/home/alice/demo.whl"},
        ):
            manifest = complete_manifest()
            manifest["wheels"][1]["source"] = source
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "source"):
                validate_manifest(manifest)

    def test_runtime_records_upstream_and_normalized_artifacts_separately(self):
        manifest = complete_manifest()
        runtime = manifest["runtime"]
        self.assertEqual(runtime["path"], "runtime/python.tar.gz")
        self.assertEqual(runtime["sha256"], HEX_A)
        self.assertEqual(runtime["source"]["filename"], "cpython.tar.zst")
        self.assertEqual(runtime["source"]["sha256"], HEX_B)
        validate_manifest(manifest)

    def test_identity_has_no_generated_hash_self_reference(self):
        manifest = complete_manifest()
        identity = manifest["identity"]
        self.assertNotIn("manifest_sha256", identity)
        self.assertNotIn("checksums_sha256", identity)
        self.assertNotIn("archive_sha256", identity)
        self.assertNotIn("manifest.json", {item["path"] for item in manifest["files"]})
        self.assertNotIn("SHA256SUMS", {item["path"] for item in manifest["files"]})
        validate_manifest(manifest)

        for forbidden in ("manifest_sha256", "checksums_sha256", "archive_sha256"):
            invalid = complete_manifest()
            invalid["identity"][forbidden] = HEX_A
            invalid["release_id"] = release_id(invalid["qbox_version"], invalid["identity"])
            with self.subTest(field=forbidden), self.assertRaisesRegex(ValueError, "identity"):
                validate_manifest(invalid)

    def test_manifest_release_id_and_identity_hashes_match_payloads(self):
        manifest = complete_manifest()
        manifest["release_id"] = "0.1.0-" + "0" * 64
        with self.assertRaisesRegex(ValueError, "release_id"):
            validate_manifest(manifest)

        manifest = complete_manifest()
        manifest["identity"]["runtime_sha256"] = HEX_C
        manifest["release_id"] = release_id(manifest["qbox_version"], manifest["identity"])
        with self.assertRaisesRegex(ValueError, "runtime_sha256"):
            validate_manifest(manifest)

    def test_manifest_rejects_lock_hash_mismatches_and_missing_build_lock(self):
        mutations = (
            ("dependencies_lock_sha256", HEX_C),
            ("build_requirements_lock_sha256", HEX_C),
        )
        for field, digest in mutations:
            manifest = complete_manifest()
            manifest["identity"][field] = digest
            manifest["release_id"] = release_id(
                manifest["qbox_version"], manifest["identity"]
            )
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                validate_manifest(manifest)

        manifest = complete_manifest()
        manifest["files"] = [
            item
            for item in manifest["files"]
            if item["path"] != "checks/build-requirements.lock"
        ]
        with self.assertRaisesRegex(ValueError, "checks/build-requirements.lock"):
            validate_manifest(manifest)

    def test_manifest_rejects_qbox_wheel_version_mismatch(self):
        manifest = complete_manifest()
        manifest["wheels"][0]["version"] = "9.9.9"
        manifest["wheels"][0]["requirement"] = "qbox[analysis,structure]==9.9.9"
        with self.assertRaisesRegex(ValueError, "qbox_version"):
            validate_manifest(manifest)

    def test_manifest_requires_bundle_layout_payloads(self):
        manifest = complete_manifest()
        manifest["files"] = [
            item for item in manifest["files"] if item["path"] != "requirements.lock"
        ]
        with self.assertRaisesRegex(ValueError, "requirements.lock"):
            validate_manifest(manifest)

        manifest = complete_manifest()
        manifest["runtime"]["path"] = "runtime/renamed.tar.gz"
        manifest["files"][0]["path"] = "runtime/renamed.tar.gz"
        with self.assertRaisesRegex(ValueError, "runtime/python.tar.gz"):
            validate_manifest(manifest)

        manifest = complete_manifest()
        manifest["wheels"][0]["path"] = "wheelhouse/qbox-0.1.0-py3-none-any.whl"
        manifest["files"][1]["path"] = "wheelhouse/qbox-0.1.0-py3-none-any.whl"
        with self.assertRaisesRegex(ValueError, "packages"):
            validate_manifest(manifest)

    def test_identity_covers_every_check_payload(self):
        manifest = complete_manifest()
        manifest["files"].append(
            payload(
                "checks/verify.py",
                hashlib.sha256(b"verify").hexdigest(),
                license_ids=["MIT"],
            )
        )
        with self.assertRaisesRegex(ValueError, "identity.checks"):
            validate_manifest(manifest)

    def test_policy_records_the_approved_platform_and_bundle_layout(self):
        policy_path = ROOT / "packaging/offline/policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema_version"], 1)
        self.assertEqual(policy["product"], "qbox")
        self.assertEqual(
            policy["platform"],
            {
                "os": "linux",
                "arch": "x86_64",
                "glibc_min": "2.28",
                "python_series": "3.12",
                "cpu_baseline": "x86_64",
            },
        )
        self.assertEqual(policy["extras"], ["analysis", "structure"])
        self.assertEqual(policy["runtime"]["target_triple"], "x86_64-unknown-linux-gnu")
        self.assertEqual(policy["runtime"]["flavor"], "install_only")
        self.assertEqual(policy["bundle"]["runtime_path"], "runtime/python.tar.gz")
        self.assertEqual(policy["bundle"]["manifest_path"], "manifest.json")
        self.assertEqual(policy["bundle"]["checksums_path"], "SHA256SUMS")

    def test_offline_support_runs_stdlib_commands_with_controlled_inputs(self):
        from support import run

        with tempfile.TemporaryDirectory() as directory:
            result = run(
                [
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os, pathlib, sys; "
                        "print(pathlib.Path.cwd().name, os.environ['OFFLINE_TEST'], "
                        "sys.stdin.read(), sep='|')"
                    ),
                ],
                cwd=directory,
                env={"OFFLINE_TEST": "yes"},
                input="fixture",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{Path(directory).name}|yes|fixture\n")

    def test_offline_support_writes_nested_files_with_requested_mode(self):
        from support import write_file

        with tempfile.TemporaryDirectory() as directory:
            path = write_file(Path(directory), "nested/probe.sh", "#!/bin/sh\n", 0o750)
            self.assertEqual(path, Path(directory) / "nested/probe.sh")
            self.assertEqual(path.read_text(encoding="utf-8"), "#!/bin/sh\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o750)

    def test_maintainer_cli_validates_a_manifest(self):
        from support import run, write_file

        manifest = complete_manifest()
        with tempfile.TemporaryDirectory() as directory:
            path = write_file(
                Path(directory),
                "manifest.json",
                canonical_json(manifest).decode("utf-8"),
            )
            result = run(
                ["/usr/bin/python3", "-m", "tools.offline", "validate-manifest", str(path)],
                cwd=ROOT,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, manifest["release_id"] + "\n")

    def test_maintainer_cli_reports_invalid_manifest_without_a_traceback(self):
        from support import run, write_file

        manifest = complete_manifest()
        manifest["schema_version"] = 99
        with tempfile.TemporaryDirectory() as directory:
            path = write_file(
                Path(directory),
                "manifest.json",
                canonical_json(manifest).decode("utf-8"),
            )
            result = run(
                ["/usr/bin/python3", "-m", "tools.offline", "validate-manifest", str(path)],
                cwd=ROOT,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("schema_version", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
