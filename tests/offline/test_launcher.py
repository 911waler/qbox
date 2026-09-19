"""Process contracts for the public offline qbox launcher."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "packaging/offline/qbox-launcher.sh"


class OfflineLauncherTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="qbox launcher ")
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.release = self.base / "release with spaces"
        self.record = self.base / "record"
        (self.release / "bin").mkdir(parents=True)
        (self.release / "python/bin").mkdir(parents=True)
        (self.release / "metadata").mkdir(parents=True)
        self.record.mkdir()
        shutil.copy2(LAUNCHER, self.release / "bin/qbox")
        (self.release / "metadata/installed.json").write_text(
            json.dumps({"state": "verified"}), encoding="utf-8"
        )
        self.python = self.release / "python/bin/python3"
        self.python.write_text(
            "#!/bin/sh\n"
            "printf '%s\\0' \"$@\" > \"$QBOX_RECORD/argv\"\n"
            "pwd -P > \"$QBOX_RECORD/cwd\"\n"
            "printf '%s\\n' \"$$\" > \"$QBOX_RECORD/pid\"\n"
            "printf '%s\\n' \"$PPID\" > \"$QBOX_RECORD/ppid\"\n"
            "printf '%s\\n' \"$_QBOX_OFFLINE_ROOT\" > \"$QBOX_RECORD/root\"\n"
            "printf '%s\\n' \"$QBOX_PYTHON\" > \"$QBOX_RECORD/python\"\n"
            "printf '%s\\n' \"$PYTHONPATH\" > \"$QBOX_RECORD/pythonpath\"\n"
            "cat > \"$QBOX_RECORD/stdin\"\n"
            "exit 17\n",
            encoding="utf-8",
        )
        self.python.chmod(0o755)
        self.link = self.base / "public qbox"
        self.link.symlink_to(self.release / "bin/qbox")

    def environment(self):
        environment = os.environ.copy()
        for key in ("BASH_FUNC_module%%", "BASH_FUNC_ml%%", "QBOX_PYTHON"):
            environment.pop(key, None)
        environment["QBOX_RECORD"] = str(self.record)
        environment["PYTHONPATH"] = "/external/python-libs"
        environment["QBOX_SHARED_ROOT"] = "/obsolete/shared/root"
        return environment

    def test_symlinked_launcher_execs_bundled_python_without_wrapper_process(self):
        alias = self.release / "python/bin/python-alias"
        alias.symlink_to(self.python)
        environment = self.environment()
        environment["QBOX_PYTHON"] = str(alias)
        process = subprocess.Popen(
            [str(self.link), "input with spaces.in", "23", ""],
            cwd=self.base,
            env=environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate("complete stdin\nsecond line\n", timeout=10)
        self.assertEqual(process.returncode, 17, stdout + stderr)
        self.assertEqual((stdout, stderr), ("", ""))
        argv = (self.record / "argv").read_bytes().split(b"\0")[:-1]
        self.assertEqual(
            argv,
            [b"-I", b"-B", b"-m", b"qbox", b"input with spaces.in", b"23", b""],
        )
        self.assertEqual(int((self.record / "pid").read_text()), process.pid)
        self.assertEqual(int((self.record / "ppid").read_text()), os.getpid())
        self.assertEqual((self.record / "cwd").read_text().strip(), str(self.base.resolve()))
        self.assertEqual((self.record / "stdin").read_text(), "complete stdin\nsecond line\n")
        self.assertEqual((self.record / "root").read_text().strip(), str(self.release.resolve()))
        self.assertEqual((self.record / "python").read_text().strip(), str(self.python))
        self.assertEqual((self.record / "pythonpath").read_text().strip(), "/external/python-libs")

    def test_external_qbox_python_is_rejected_with_actionable_error(self):
        environment = self.environment()
        environment["QBOX_PYTHON"] = "/usr/bin/python3"
        result = subprocess.run(
            [str(self.link), "--version"], env=environment, text=True,
            capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unset QBOX_PYTHON", result.stderr)
        self.assertFalse((self.record / "argv").exists())

    def test_incomplete_release_is_rejected_before_python_runs(self):
        (self.release / "metadata/installed.json").unlink()
        result = subprocess.run(
            [str(self.link)], env=self.environment(), text=True,
            capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("安装不完整", result.stderr)
        self.assertFalse((self.record / "argv").exists())


if __name__ == "__main__":
    unittest.main()
