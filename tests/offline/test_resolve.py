"""Resolver contracts: portable wheels, complete extras, verified provenance, safe tar."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from tools.offline import resolve as resolver
from tools.offline.archive import normalize_runtime


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
