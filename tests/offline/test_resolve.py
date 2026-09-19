"""Resolver contracts: portable wheels, complete extras, verified provenance, safe tar."""

import io
import hashlib
import shutil
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

from tools.offline import resolve as resolver
from tools.offline.archive import normalize_runtime
from tools.offline import archive as archive_tools


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def wheel(self, name, version="1.0", requires=()):
        path = self.root / f"{name}-{version}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                f"{name}-{version}.dist-info/METADATA",
                f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n"
                + "".join(f"Requires-Dist: {r}\n" for r in requires),
            )
        return path

    def test_wheel_policy_rejects_newer_or_unknown_linux(self):
        tags = resolver.target_tags()
        for name in (
            "demo-1.0-cp312-cp312-manylinux_2_28_x86_64.whl",
            "demo-1.0-py3-none-any.whl",
            "demo-1.0-cp39-abi3-manylinux2014_x86_64.whl",
        ):
            self.assertTrue(resolver.allowed_wheel(name, tags), name)
        for name in (
            "demo-1.0-cp312-cp312-manylinux_2_34_x86_64.whl",
            "demo-1.0-cp312-cp312-linux_x86_64.whl",
            "demo-1.0-cp312-cp312-musllinux_1_2_x86_64.whl",
            "demo-1.0-cp313-cp313-manylinux_2_28_x86_64.whl",
            "demo-1.0.tar.gz",
        ):
            self.assertFalse(resolver.allowed_wheel(name, tags), name)

    def test_extras_markers_transitive_cycle_and_missing_wheel(self):
        q = self.wheel(
            "qbox",
            requires=[
                'a[feature]; extra == "analysis"',
                'b; extra == "structure"',
                'windows; sys_platform == "win32"',
            ],
        )
        a = self.wheel("a", requires=['b>=1; extra == "feature"'])
        b = self.wheel("b", requires=["a"])
        env = {
            "python_version": "3.12",
            "python_full_version": "3.12.14",
            "sys_platform": "linux",
            "platform_machine": "x86_64",
        }
        result = resolver.wheel_closure(
            [q, a, b], ["qbox[analysis,structure]==1.0"], env
        )
        self.assertEqual([p["name"] for p in result], ["a", "b", "qbox"])
        with self.assertRaisesRegex(ValueError, "missing.*b"):
            resolver.wheel_closure([q, a], ["qbox[analysis,structure]==1.0"], env)
        self.assertEqual(len(resolver.wheel_closure([q, a, b], ["qbox==1.0"], env)), 1)

    def test_duplicate_direct_url_and_metadata_version_fail(self):
        one = self.wheel("Some_Pkg")
        two = self.wheel("some_pkg", "2.0")
        with self.assertRaises(ValueError):
            resolver.wheel_closure([one, two], ["some-pkg"], {})
        q = self.wheel("qbox", requires=["a @ https://example.com/a.whl"])
        with self.assertRaisesRegex(ValueError, "URL"):
            resolver.wheel_closure([q], ["qbox"], {})
        with self.assertRaises(ValueError):
            resolver.wheel_closure([self.root / "source.tar.gz"], ["qbox"], {})

    def test_metadata_name_and_requirement_version_must_match(self):
        wheel = self.wheel("demo")
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            resolver.wheel_closure([wheel], ["demo>=2"], {})
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "demo-1.0.dist-info/METADATA", "Name: imposter\nVersion: 1.0\n"
            )
        with self.assertRaisesRegex(ValueError, "mismatch"):
            resolver.wheel_metadata(wheel)

    def test_vendored_metadata_is_not_the_distribution_metadata(self):
        wheel = self.wheel("setuptools", "84.0.0")
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr(
                "setuptools/_vendor/demo-1.0.dist-info/METADATA",
                "Name: demo\nVersion: 1.0\n",
            )
        self.assertEqual(resolver.wheel_metadata(wheel)["name"], "setuptools")

    def test_hash_cache_rejects_changed_content(self):
        source = self.root / "asset"
        source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA"):
            resolver.cache_asset(
                source.as_uri(), "0" * 64, self.root / "cache", local=source
            )
        self.assertFalse((self.root / "cache" / ("0" * 64)).exists())

    def test_runtime_selection_requires_official_digest_and_baseline(self):
        def asset(
            version,
            suffix="x86_64-unknown-linux-gnu-install_only.tar.gz",
            digest="sha256:" + "a" * 64,
        ):
            return {
                "name": f"cpython-{version}+20260901-{suffix}",
                "digest": digest,
                "browser_download_url": f"https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-{version}+20260901-{suffix}",
            }

        release = {
            "tag_name": "20260901",
            "published_at": "2026-09-01T12:00:00Z",
            "prerelease": False,
            "draft": False,
            "assets": [
                asset("3.12.13"),
                asset("3.12.14"),
                asset("3.12.15", "x86_64_v3-unknown-linux-gnu-install_only.tar.gz"),
            ],
        }
        self.assertEqual(
            resolver.select_runtime([release], "2026-09-19")["version"], "3.12.14"
        )
        release["assets"] = [asset("3.12.14", digest=None)]
        with self.assertRaisesRegex(ValueError, "digest"):
            resolver.select_runtime([release], "2026-09-19")

    def test_pypi_provenance_rejects_hash_mismatch_and_missing_asset(self):
        wheel = self.wheel("demo")
        metadata = resolver.wheel_metadata(wheel)
        doc = {
            "urls": [
                {
                    "filename": wheel.name,
                    "url": "https://files.pythonhosted.org/demo.whl",
                    "digests": {"sha256": "0" * 64},
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "SHA"):
            resolver.pypi_source(metadata, doc)
        with self.assertRaises(ValueError):
            resolver.pypi_source(metadata, {"urls": []})

    def test_container_enforces_digest_and_pip_environment(self):
        with self.assertRaises(ValueError):
            resolver.container_command("rocky:8", self.root, ["python"], network=False)
        command = resolver.container_command(
            "quay.io/rocky@sha256:" + "a" * 64, self.root, ["python"], network=False
        )
        self.assertEqual(command[command.index("--network") + 1], "none")
        env = resolver.pip_environment(
            {"PIP_INDEX_URL": "https://wrong", "HOME": "/tmp"}
        )
        self.assertNotIn("PIP_INDEX_URL", env)
        self.assertEqual(env["PIP_CONFIG_FILE"], "/dev/null")

    def test_bootstrap_inventory_separates_vendored_packages(self):
        items = resolver.bootstrap_records(
            {
                "installed": [{"name": "pip", "version": "26.2"}],
                "pip_vendored": "# dependencies\npackaging==26.0\n# note\n  truststore==0.10.4  # vendor\n",
            }
        )
        self.assertEqual(
            [(p["name"], p["version"]) for p in items],
            [
                ("pip", "26.2"),
                ("pip-vendor-packaging", "26.0"),
                ("pip-vendor-truststore", "0.10.4"),
            ],
        )
        with self.assertRaises(ValueError):
            resolver.bootstrap_records({"installed": [], "pip_vendored": "broken>=1"})

    def discovery_cache(self, api_content=None, *, corrupt_provenance=False):
        metadata = self.root / "metadata"
        metadata.mkdir(exist_ok=True)
        tag = "20260901"
        filename = (
            "cpython-3.12.14+20260901-x86_64-unknown-linux-gnu-install_only.tar.gz"
        )
        assets = (
            f'<a href="/astral-sh/python-build-standalone/releases/download/{tag}/{filename}">runtime</a>sha256:'
            + "a" * 64
        )
        entries = [
            (
                f"github-release-{tag}.html",
                f"https://github.com/astral-sh/python-build-standalone/releases/tag/{tag}",
                '<relative-time datetime="2026-09-01T12:00:00Z">',
            ),
            (
                f"github-assets-{tag}.html",
                f"https://github.com/astral-sh/python-build-standalone/releases/expanded_assets/{tag}",
                assets,
            ),
        ]
        if api_content is not None:
            entries.append(
                (
                    "github-releases.json",
                    "https://api.github.com/repos/astral-sh/python-build-standalone/releases?per_page=100",
                    api_content,
                )
            )
        for name, url, content in entries:
            path = metadata / name
            path.write_text(content)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if name == "github-releases.json" and corrupt_provenance:
                digest = "0" * 64
            (metadata / (name + ".provenance.json")).write_text(
                json.dumps(
                    {
                        "url": url,
                        "sha256": digest,
                        "requested_at": "2026-09-19T00:00:00Z",
                    }
                )
            )
        return metadata

    def test_discovery_does_not_fallback_on_integrity_or_selection_errors(self):
        asset = {
            "name": "cpython-3.12.14+20260901-x86_64-unknown-linux-gnu-install_only.tar.gz",
            "digest": None,
        }
        release = {
            "tag_name": "20260901",
            "published_at": "2026-09-01T12:00:00Z",
            "draft": False,
            "prerelease": False,
            "assets": [asset],
        }
        for text, corrupt, message in [
            (json.dumps([release]), False, "digest"),
            ("not JSON", False, "Expecting value"),
            ("[]", True, "provenance mismatch"),
        ]:
            with self.subTest(message=message):
                metadata = self.discovery_cache(text, corrupt_provenance=corrupt)
                with self.assertRaisesRegex(ValueError, message):
                    resolver.discover_runtime(
                        {"fallback_release_tag": "20260901"}, metadata
                    )

    def test_discovery_only_falls_back_on_rate_limited_http403(self):
        metadata = self.discovery_cache()
        for status, headers, body, allowed in [
            (403, {"X-RateLimit-Remaining": "0"}, b"", True),
            (403, {}, b'{"message":"API rate limit exceeded"}', True),
            (403, {}, b"permission denied", False),
            (404, {}, b"not found", False),
            (500, {}, b"server error", False),
        ]:
            with self.subTest(status=status, body=body):
                error = HTTPError(
                    "https://api.github.com/",
                    status,
                    "failure",
                    headers,
                    io.BytesIO(body),
                )
                with patch.object(resolver, "urlopen", side_effect=error):
                    if allowed:
                        chosen, provenance = resolver.discover_runtime(
                            {"fallback_release_tag": "20260901"}, metadata
                        )
                        self.assertEqual(chosen["version"], "3.12.14")
                        self.assertIn("403", provenance[-1]["fallback_reason"])
                    else:
                        with self.assertRaises(HTTPError):
                            resolver.discover_runtime(
                                {"fallback_release_tag": "20260901"}, metadata
                            )

    def material_source(self, archive):
        return {
            "url": "https://example.org/full.tar.gz",
            "filename": "full.tar.gz",
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }

    def test_preserve_materials_maps_ascii_names_and_exact_bytes_reproducibly(self):
        source = self.archive(
            [
                (
                    "python/PYTHON.json",
                    '{"license_path":"licenses/许可 text.txt"}'.encode(),
                    None,
                ),
                ("python/licenses/许可 text.txt", b"original\r\nlicense\x00", None),
                ("python/install/bin/python3", b"not a license", None),
            ]
        )
        output = self.root / "materials"
        result = archive_tools.preserve_runtime_materials(
            source, output, self.material_source(source)
        )
        index = json.loads((output / "index.json").read_text())
        self.assertEqual(index["source"], self.material_source(source))
        self.assertEqual(len(index["materials"]), 2)
        license_row = next(
            row
            for row in index["materials"]
            if row["source_member"].startswith("python/licenses/")
        )
        self.assertTrue(license_row["path"].isascii())
        self.assertEqual(
            (output / license_row["path"]).read_bytes(), b"original\r\nlicense\x00"
        )
        self.assertEqual(
            result["index_sha256"],
            hashlib.sha256((output / "index.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            archive_tools.preserve_runtime_materials(
                source, output, self.material_source(source)
            ),
            result,
        )

    def test_preserve_materials_rejects_unsafe_or_ambiguous_archive(self):
        fixtures = [
            [
                ("python/PYTHON.json", b"{}", None),
                ("python/licenses/../../escape", b"bad", None),
            ],
            [
                ("python/PYTHON.json", b"{}", None),
                ("python/licenses/A", b"one", None),
                ("python/licenses/A", b"two", None),
            ],
            [
                ("python/PYTHON.json", b"{}", None),
                ("python/licenses/A", b"", "../../escape"),
            ],
            [
                ("python/PYTHON.json", b"{}", None),
                ("python/licenses/a b", b"one", None),
                ("python/licenses/a_b", b"two", None),
            ],
            [("python/licenses/A", b"license", None)],
        ]
        for entries in fixtures:
            with self.subTest(entries=entries):
                source = self.archive(entries)
                with self.assertRaises(ValueError):
                    archive_tools.preserve_runtime_materials(
                        source,
                        self.root / "bad-materials",
                        self.material_source(source),
                    )
                self.assertFalse((self.root / "bad-materials/index.json").exists())

    def test_resolve_preserves_companion_before_runtime_normalization(self):
        cache = self.root / "cache"
        downloads = cache / "downloads"
        downloads.mkdir(parents=True)
        version = "3.12.14"
        build = "20260901"
        upstream_name = (
            f"cpython-{version}+{build}-x86_64-unknown-linux-gnu-install_only.tar.gz"
        )
        companion_name = (
            f"cpython-{version}+{build}-x86_64-unknown-linux-gnu-pgo+lto-full.tar.zst"
        )
        original = self.archive([("python/bin/python3", b"runtime fixture", None)])
        shutil.copyfile(original, downloads / upstream_name)
        companion = self.archive(
            [
                ("python/PYTHON.json", b"{}", None),
                ("python/licenses/LICENSE.txt", b"original license", None),
            ]
        )
        shutil.copyfile(companion, downloads / companion_name)
        digest = hashlib.sha256(companion.read_bytes()).hexdigest()
        html = self.root / "assets.html"
        html.write_text(
            f'aria-label="Copy to clipboard digest for {companion_name}" value="sha256:{digest}"'
        )
        upstream = {
            "version": version,
            "build": build,
            "filename": upstream_name,
            "url": f"https://github.com/astral-sh/python-build-standalone/releases/download/{build}/{upstream_name}",
            "sha256": hashlib.sha256(
                (downloads / upstream_name).read_bytes()
            ).hexdigest(),
        }
        policy = self.root / "packaging/offline/policy.json"
        policy.parent.mkdir(parents=True)
        policy.write_text(
            json.dumps({"resolver": {"build_image": "fixture@sha256:" + "a" * 64}})
        )
        with (
            patch.object(resolver, "discover_runtime", return_value=(upstream, [])),
            patch.object(resolver, "snapshot", return_value=(html, {})),
            patch.object(
                resolver,
                "normalize_runtime",
                side_effect=RuntimeError("stop after preservation"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop after preservation"):
                resolver.resolve(policy, cache)
        materials = cache / "runtime-license-materials"
        index = json.loads((materials / "index.json").read_text())
        self.assertEqual(index["source"]["sha256"], digest)
        self.assertEqual(
            (materials / "python_licenses_LICENSE.txt").read_bytes(),
            b"original license",
        )

    def test_preservation_rejects_source_hash_mismatch_before_publication(self):
        source = self.archive(
            [
                ("python/PYTHON.json", b"{}", None),
                ("python/licenses/A", b"license", None),
            ]
        )
        record = {**self.material_source(source), "sha256": "0" * 64}
        output = self.root / "materials"
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            archive_tools.preserve_runtime_materials(source, output, record)
        self.assertFalse(output.exists())

    def test_normalize_explicitly_rejects_safe_directory_alias(self):
        source = self.root / "directory-link.tar.gz"
        with tarfile.open(source, "w:gz") as archive:
            directory = tarfile.TarInfo("python/lib")
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
            link = tarfile.TarInfo("python/lib-alias")
            link.type = tarfile.SYMTYPE
            link.linkname = "lib"
            archive.addfile(link)
        with self.assertRaisesRegex(ValueError, "directory links are unsupported"):
            normalize_runtime(source, self.root / "normalized.tar.gz")
        self.assertFalse((self.root / "normalized.tar.gz").exists())

    def archive(self, entries):
        path = self.root / "upstream.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            for name, data, link in entries:
                info = tarfile.TarInfo(name)
                info.mode = 0o755
                if link:
                    info.type = tarfile.SYMTYPE
                    info.linkname = link
                    tar.addfile(info)
                else:
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
        return path

    def test_normalize_dereferences_and_is_reproducible(self):
        source = self.archive(
            [
                ("python/bin/python3.12", b"bin", None),
                ("python/bin/python3", b"", "python3.12"),
                ("python/lib/cache.pyc", b"cache", None),
            ]
        )
        output = self.root / "normalized.tar.gz"
        result = normalize_runtime(source, output)
        first = output.read_bytes()
        normalize_runtime(source, output)
        self.assertEqual(first, output.read_bytes())
        with tarfile.open(output) as tar:
            self.assertEqual(tar.extractfile("python/bin/python3").read(), b"bin")
            self.assertTrue(all(m.isfile() or m.isdir() for m in tar))
            self.assertNotIn("python/lib/cache.pyc", tar.getnames())
        self.assertTrue(result["links"])

    def test_normalize_rejects_escape_duplicate_and_cycle(self):
        for entries in (
            [("../escape", b"", None)],
            [("python/a", b"x", None), ("python/a", b"y", None)],
            [("python/a", b"", "../../escape")],
            [("python/a", b"", "b"), ("python/b", b"", "a")],
        ):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                normalize_runtime(self.archive(entries), self.root / "bad.tar.gz")

    def test_candidate_locks_do_not_overwrite_reviewed_locks(self):
        locks = self.root / "locks"
        locks.mkdir()
        (locks / "runtime.lock.json").write_text('{"old":true}\n')
        result = resolver.write_candidates(
            locks, self.root / "candidates", {"runtime.lock.json": b'{"new":true}\n'}
        )
        self.assertEqual((locks / "runtime.lock.json").read_text(), '{"old":true}\n')
        self.assertIn('-{"old":true}', result["runtime.lock.json"]["diff"])


if __name__ == "__main__":
    unittest.main()
