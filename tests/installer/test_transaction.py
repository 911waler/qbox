"""Real wheel/venv transaction tests; dependency sources come from pip's environment."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from installer.paths import InstallOptions
from installer import transaction


ROOT = Path(__file__).resolve().parents[2]


class TransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="qbox-transaction-tests-")
        cls.base = Path(cls.workspace.name)
        cls.python = Path(os.environ.get("QBOX_TEST_PYTHON", sys.executable)).absolute()
        builder = os.environ.get("QBOX_TEST_BUILD_PYTHON", str(cls.python))
        subprocess.run([builder, "-m", "build", "--wheel", "--no-isolation", "--outdir",
                        str(cls.base / "wheel"), str(ROOT)], check=True,
                       stdout=subprocess.DEVNULL)
        cls.wheel = next((cls.base / "wheel").glob("*.whl"))
        cls.sha = hashlib.sha256(cls.wheel.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.options = InstallOptions("user", self.root / "中文 app's space",
                                      self.root / "commands", self.python)
        self.unrelated = self.root / "keep"
        self.unrelated.write_bytes(b"unrelated\x00data")

    def install(self, options=None):
        return transaction.install(options or self.options, wheel=self.wheel,
                                   wheel_sha256=self.sha)

    def assert_preserved(self):
        self.assertEqual(self.unrelated.read_bytes(), b"unrelated\x00data")

    def test_foreign_entries_are_never_overwritten(self):
        self.options.bin_dir.mkdir()
        entry = self.options.bin_dir / "qbox"
        for kind in ("file", "symlink", "directory"):
            with self.subTest(kind=kind):
                if kind == "file":
                    entry.write_bytes(b"foreign command")
                elif kind == "symlink":
                    entry.symlink_to(self.root / "absent")
                else:
                    entry.mkdir()
                    (entry / "keep").write_text("directory content")
                with self.assertRaises((ValueError, OSError)):
                    self.install()
                if kind == "file":
                    self.assertEqual(entry.read_bytes(), b"foreign command")
                    entry.unlink()
                elif kind == "symlink":
                    self.assertEqual(os.readlink(entry), str(self.root / "absent"))
                    entry.unlink()
                else:
                    self.assertEqual((entry / "keep").read_text(), "directory content")
                self.assertFalse(self.options.prefix.exists())
                self.assert_preserved()

    def test_unmarked_prefix_and_foreign_lock_are_preserved(self):
        prefix = self.options.prefix
        prefix.mkdir()
        (prefix / "keep").write_text("old installation")
        with self.assertRaises((ValueError, OSError)):
            self.install()
        self.assertEqual((prefix / "keep").read_text(), "old installation")
        (prefix / "keep").unlink()
        lock = prefix / ".install-lock"
        lock.mkdir()
        (lock / "token").write_text("another transaction")
        with self.assertRaises((ValueError, OSError)):
            self.install()
        self.assertEqual((lock / "token").read_text(), "another transaction")
        self.assert_preserved()

    def test_wheel_digest_mismatch_creates_nothing(self):
        with self.assertRaisesRegex(ValueError, "SHA|digest"):
            transaction.install(self.options, wheel=self.wheel, wheel_sha256="0" * 64)
        self.assertFalse(self.options.prefix.exists())

    def test_unusable_python_has_actionable_preflight_without_mutations(self):
        options = InstallOptions("user", self.options.prefix, self.options.bin_dir, Path("/usr/bin/false"))
        with self.assertRaisesRegex(ValueError, "Python 3.10.*venv"):
            self.install(options)
        self.assertFalse(options.prefix.exists())
        self.assert_preserved()

    def test_ready_reuse_configuration_integrity_and_competing_prefix(self):
        polluted = {"QBOX_PYTHON": "/missing/old/python", "PYTHONPATH": "/missing",
                    "PIP_TARGET": str(self.root / "wrong-target"), "PIP_USER": "1"}
        with patch.dict(os.environ, polluted):
            entry = self.install()
        original = entry.read_bytes()
        record_path = self.options.prefix / ".qbox-install.json"
        record = json.loads(record_path.read_text())
        self.assertEqual(record["state"], "ready")
        self.assertEqual(record["wheel_sha256"], self.sha)
        self.assertIn("numpy", record["distributions"])
        self.assertFalse((self.root / "wrong-target").exists())
        env = dict(os.environ, QBOX_PYTHON="/missing/old/python")
        result = subprocess.run([str(entry), "--list"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cif-to-vasp", result.stdout)
        with patch.dict(os.environ, {"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": "/missing"}):
            self.assertEqual(self.install(), entry)
        other = InstallOptions("user", self.root / "second", entry.parent, self.python)
        with self.assertRaises((ValueError, OSError)):
            self.install(other)
        self.assertFalse(other.prefix.exists())
        alternate = InstallOptions("user", self.options.prefix, self.root / "other-bin", self.python)
        with self.assertRaises((ValueError, OSError)):
            self.install(alternate)
        with self.assertRaises((ValueError, OSError)):
            transaction.verify_install(self.options, wheel_sha256="1" * 64)
        self.assertEqual(entry.read_bytes(), original)
        entry.write_bytes(original + b"# altered\n")
        with self.assertRaises((ValueError, OSError)):
            self.install()
        self.assertEqual(entry.read_bytes(), original + b"# altered\n")
        entry.write_bytes(original)
        record_path.write_text("{broken")
        with self.assertRaises((ValueError, OSError)):
            self.install()
        self.assertEqual(record_path.read_text(), "{broken")
        self.assertEqual(entry.read_bytes(), original)
        self.assert_preserved()

    def test_real_pip_failure_leaves_diagnosed_preparing_environment(self):
        empty = self.root / "empty-index"
        empty.mkdir()
        with patch.dict(os.environ, {"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(empty)}):
            with self.assertRaisesRegex(Exception, "retained|manual") as caught:
                self.install()
        self.assertIsInstance(caught.exception.__cause__, subprocess.CalledProcessError)
        self.assertNotEqual(caught.exception.__cause__.returncode, 0)
        self.assertFalse((self.options.bin_dir / "qbox").exists())
        self.assertFalse((self.options.prefix / ".install-lock").exists())
        record = json.loads((self.options.prefix / ".qbox-install.json").read_text())
        self.assertEqual(record["state"], "preparing")
        with self.assertRaisesRegex((ValueError, OSError), "preparing|manual"):
            self.install()
        self.assert_preserved()

    def test_pip_configuration_cannot_redirect_install_outside_venv(self):
        outside = self.root / "outside destination"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_bytes(b"outside sentinel")
        config = self.root / "pip.conf"
        find_links = os.environ.get("PIP_FIND_LINKS", "")
        transport = (f"no-index = true\nfind-links = {find_links}\n"
                     if find_links else "")
        config.write_text(f"[global]\n{transport}[install]\ntarget = {outside}\n")
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("PIP_")}
        env["PIP_CONFIG_FILE"] = str(config)
        try:
            with patch.dict(os.environ, env, clear=True):
                entry = self.install()
                transaction.verify_install(self.options, wheel_sha256=self.sha)
            self.assertTrue(entry.is_file())
        finally:
            self.assertEqual(sorted(item.name for item in outside.iterdir()), ["keep"])
            self.assertEqual(sentinel.read_bytes(), b"outside sentinel")
            self.assert_preserved()

    def test_pip_transport_precedence_is_preserved_without_write_options(self):
        home = self.root / "home"
        config = home / ".config/pip/pip.conf"
        config.parent.mkdir(parents=True)
        outside = self.root / "must-not-be-created"
        config.write_text(
            "[global]\nindex-url = https://global.invalid/simple\n"
            "cert = /configured/ca.pem\nclient-cert = /configured/client.pem\n"
            "proxy = http://configured.invalid:1234\n"
            f"log = {outside}\nroot = {outside}\n"
            "[install]\nindex-url = https://install.invalid/simple\n"
            "extra-index-url = https://extra.invalid/simple\n"
            f"prefix = {outside}\ntarget = {outside}\nuser = true\n")
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("PIP_")}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   PIP_LOG=str(outside), PIP_ROOT=str(outside))
        for explicit in (False, True):
            with self.subTest(explicit_file=explicit):
                source = dict(env)
                if explicit:
                    source["PIP_CONFIG_FILE"] = str(config)
                    source["PIP_INDEX_URL"] = "https://environment.invalid/simple"
                result = transaction._pip_environment(self.python, source)
                expected_index = ("https://environment.invalid/simple" if explicit
                                  else "https://install.invalid/simple")
                self.assertEqual(result["PIP_INDEX_URL"], expected_index)
                self.assertEqual(result["PIP_EXTRA_INDEX_URL"], "https://extra.invalid/simple")
                self.assertEqual(result["PIP_PROXY"], "http://configured.invalid:1234")
                self.assertEqual(result["PIP_CERT"], "/configured/ca.pem")
                self.assertEqual(result["PIP_CLIENT_CERT"], "/configured/client.pem")
                self.assertEqual(result["PIP_CONFIG_FILE"], os.devnull)
                for name in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT", "PIP_USER", "PIP_LOG"):
                    self.assertNotIn(name, result)
                self.assertFalse(outside.exists())
                self.assert_preserved()

    def test_int_and_term_keep_recoverable_record_and_release_own_lock(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                options = InstallOptions("user", self.root / str(sig), self.root / (str(sig) + "bin"), self.python)
                code = ("import sys; from pathlib import Path; from installer.paths import InstallOptions; "
                        "from installer.transaction import install; "
                        "install(InstallOptions('user',Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3])),"
                        "wheel=Path(sys.argv[4]),wheel_sha256=sys.argv[5])")
                env = dict(os.environ, PYTHONPATH=str(ROOT / "packaging/lightweight"))
                process = subprocess.Popen([str(self.python), "-c", code, str(options.prefix),
                    str(options.bin_dir), str(self.python), str(self.wheel), self.sha],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 20
                    while not (options.prefix / "venv/pyvenv.cfg").exists():
                        if process.poll() is not None or time.monotonic() > deadline:
                            self.fail("installer did not reach real venv creation")
                        time.sleep(0.02)
                    process.send_signal(sig)
                    _, stderr = process.communicate(timeout=15)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertIn("retained", stderr)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
                self.assertFalse((options.prefix / ".install-lock").exists())
                self.assertEqual(json.loads((options.prefix / ".qbox-install.json").read_text())["state"], "preparing")
                self.assertFalse((options.bin_dir / "qbox").exists())
                self.assert_preserved()

    def test_changed_lock_is_not_removed(self):
        real_run = transaction._run
        saved_lock = self.root / "saved-lock"
        lock = self.options.prefix / ".install-lock"
        def replace_lock(args, **kwargs):
            if "venv" in args:
                lock.rename(saved_lock)
                lock.mkdir()
                (lock / "token").write_text("foreign transaction")
                raise OSError("injected failure after lock replacement")
            return real_run(args, **kwargs)
        with patch.object(transaction, "_run", side_effect=replace_lock):
            with self.assertRaisesRegex(OSError, "lock retained"):
                self.install()
        self.assertEqual((lock / "token").read_text(), "foreign transaction")
        self.assertTrue((saved_lock / "token").exists())
        self.assertFalse((self.options.bin_dir / "qbox").exists())
        self.assert_preserved()

    def test_two_prefixes_race_for_one_entry_without_replacement(self):
        options = [self.options, InstallOptions("user", self.root / "second",
                                                self.options.bin_dir, self.python)]
        barrier = threading.Barrier(2, timeout=120)
        real_run = transaction._run
        def simultaneous_publication(args, **kwargs):
            if "qbox.install" in args:
                barrier.wait()
            return real_run(args, **kwargs)
        with patch.object(transaction, "_run", side_effect=simultaneous_publication):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.install, item) for item in options]
                results = []
                for future in futures:
                    try:
                        results.append(future.result())
                    except OSError as error:
                        results.append(error)
        self.assertEqual(sum(isinstance(result, Path) for result in results), 1)
        self.assertEqual(sum(isinstance(result, OSError) for result in results), 1)
        states = [json.loads((item.prefix / ".qbox-install.json").read_text())["state"] for item in options]
        self.assertEqual(sorted(states), ["preparing", "ready"])
        entry = self.options.bin_dir / "qbox"
        original = entry.read_bytes()
        winner = options[states.index("ready")]
        transaction.verify_install(winner, wheel_sha256=self.sha)
        self.assertEqual(entry.read_bytes(), original)
        self.assert_preserved()

    def test_ready_write_failure_does_not_remove_published_entry(self):
        real_write = transaction._write_record
        def fail_ready(path, record, **kwargs):
            if record["state"] == "ready":
                raise OSError("simulated full disk")
            return real_write(path, record, **kwargs)
        with patch.object(transaction, "_write_record", side_effect=fail_ready):
            with self.assertRaisesRegex(Exception, "retained|manual"):
                self.install()
        entry = self.options.bin_dir / "qbox"
        original = entry.read_bytes()
        self.assertEqual(subprocess.run([str(entry), "--help"], stdout=subprocess.DEVNULL).returncode, 0)
        with self.assertRaisesRegex((ValueError, OSError), "preparing|manual"):
            self.install()
        self.assertEqual(entry.read_bytes(), original)
        self.assert_preserved()


if __name__ == "__main__":
    unittest.main()
