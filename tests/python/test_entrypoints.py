"""Public-entry and legacy-adapter contracts for the modular distribution."""

import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "qbox"


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.env = os.environ.copy()
        for key in ("BASH_FUNC_module%%", "BASH_FUNC_ml%%", "QBOX_TASK_ID", "QBOX_TEST_MODE"):
            self.env.pop(key, None)
        self.env["QBOX_PYTHON"] = sys.executable
        self.env["PYTHONPATH"] = str(ROOT / "src")

    def run_shell(self, body, *args):
        return subprocess.run(
            ["bash", "-c", 'QBOX_TEST_MODE=1 source "$1" || exit; shift; ' + body,
             "adapter-test", str(ROOT / "qbox"), *args],
            env=self.env, text=True, capture_output=True, input="", timeout=10,
        )

    def test_symlinked_launcher_from_directory_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="qbox entry ") as directory:
            link = Path(directory) / "tool link"
            link.symlink_to(ROOT / "qbox")
            result = subprocess.run([str(link), "--help"], cwd=directory,
                                    env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--task", result.stdout)

    def test_module_help_without_site_packages(self):
        result = subprocess.run([sys.executable, "-S", "-m", "qbox", "--help"],
                                cwd="/tmp", env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("QBOX_PYTHON", result.stdout)

    def test_packaged_recursive_launcher(self):
        result = subprocess.run(["bash", str(PACKAGE / "bin" / "qbox"), "--version"],
                                cwd="/tmp", env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "qbox 0.1.0")

    def make_offline_python(self, directory):
        release = Path(directory) / "release"
        python = release / "python/bin/python3"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/bin/sh\nprintf '<%s>\\n' \"$@\"\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        self.env["_QBOX_OFFLINE_ROOT"] = str(release.resolve())
        self.env["QBOX_PYTHON"] = str(python)
        return release, python

    def test_offline_internal_python_uses_isolated_no_bytecode_flags(self):
        with tempfile.TemporaryDirectory(prefix="qbox internal python ") as directory:
            self.make_offline_python(directory)
            self.env["PYTHONPATH"] = "/external/python-libs"
            result = self.run_shell(
                'qbox_python -m qbox.registry "argument with spaces"'
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["<-I>", "<-B>", "<-m>", "<qbox.registry>", "<argument with spaces>"],
        )

    def test_offline_load_keeps_pythonpath_and_does_not_export_empty_shared_root(self):
        with tempfile.TemporaryDirectory(prefix="qbox offline load ") as directory:
            self.make_offline_python(directory)
            self.env["PYTHONPATH"] = "/external/python-libs"
            self.env.pop("QBOX_SHARED_ROOT", None)
            result = self.run_shell(
                'printf "%s|%s" "$PYTHONPATH" "${QBOX_SHARED_ROOT+set}"; '
                'case ":$PATH:" in *":$QBOX_PACKAGE_DIR/bin:"*) exit 91;; esac'
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "/external/python-libs|")

    def test_offline_internal_python_rejects_package_external_interpreter(self):
        with tempfile.TemporaryDirectory(prefix="qbox wrong python ") as directory:
            release = Path(directory) / "release"
            (release / "python/bin").mkdir(parents=True)
            self.env["_QBOX_OFFLINE_ROOT"] = str(release.resolve())
            self.env["QBOX_PYTHON"] = sys.executable
            result = self.run_shell("qbox_python --version")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("QBOX_PYTHON", result.stderr)

    def test_offline_shared_root_only_supplies_external_multiwfn_default(self):
        with tempfile.TemporaryDirectory(prefix="qbox shared root ") as directory:
            release, python = self.make_offline_python(directory)
            shared = Path(directory) / "shared root"
            multiwfn = shared / "multiwfn"
            multiwfn.mkdir(parents=True)
            self.env["QBOX_SHARED_ROOT"] = str(shared)
            result = self.run_shell(
                'printf "%s|%s|%s" "$QBOX_PYTHON" "$QBOX_MULTIWFN_HOME" "$PATH"'
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        configured_python, configured_multiwfn, path = result.stdout.split("|", 2)
        self.assertEqual(configured_python, str(python))
        self.assertEqual(configured_multiwfn, str(multiwfn))
        self.assertEqual(path.split(os.pathsep)[0], str(multiwfn))
        self.assertNotIn(str(PACKAGE / "bin"), path.split(os.pathsep))
        self.assertEqual(self.env["_QBOX_OFFLINE_ROOT"], str(release.resolve()))

    def test_offline_recursive_launcher_reuses_isolated_bundled_python(self):
        with tempfile.TemporaryDirectory(prefix="qbox recursive ") as directory:
            _, python = self.make_offline_python(directory)
            self.env["PYTHONPATH"] = "/external/python-libs"
            result = subprocess.run(
                ["bash", str(PACKAGE / "bin/qbox"), "argument with spaces"],
                env=self.env, text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["<-I>", "<-B>", "<-m>", "<qbox>", "<argument with spaces>"],
        )
        self.assertEqual(self.env["QBOX_PYTHON"], str(python))

    def test_offline_mpl_cache_uses_writable_xdg_location(self):
        with tempfile.TemporaryDirectory(prefix="qbox mpl cache ") as directory:
            self.make_offline_python(directory)
            cache = Path(directory) / "cache root"
            self.env.pop("MPLCONFIGDIR", None)
            self.env["XDG_CACHE_HOME"] = str(cache)
            result = self.run_shell(
                'test -d "$MPLCONFIGDIR" && test -w "$MPLCONFIGDIR" && printf "%s" "$MPLCONFIGDIR"'
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(cache / "qbox/matplotlib"))

    def test_offline_invalid_mpl_cache_falls_back_to_writable_xdg(self):
        with tempfile.TemporaryDirectory(prefix="qbox bad mpl ") as directory:
            self.make_offline_python(directory)
            occupied = Path(directory) / "not a directory"
            occupied.write_text("occupied")
            fallback = Path(directory) / "xdg cache"
            self.env["MPLCONFIGDIR"] = str(occupied)
            self.env["XDG_CACHE_HOME"] = str(fallback)
            result = self.run_shell('printf "%s" "$MPLCONFIGDIR"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(fallback / "qbox/matplotlib"))

    def test_offline_unsearchable_mpl_cache_falls_back_to_writable_xdg(self):
        with tempfile.TemporaryDirectory(prefix="qbox unsearchable mpl ") as directory:
            self.make_offline_python(directory)
            unsearchable = Path(directory) / "write only cache"
            unsearchable.mkdir()
            unsearchable.chmod(0o200)
            fallback = Path(directory) / "xdg cache"
            self.env["MPLCONFIGDIR"] = str(unsearchable)
            self.env["XDG_CACHE_HOME"] = str(fallback)
            try:
                result = self.run_shell('printf "%s" "$MPLCONFIGDIR"')
            finally:
                unsearchable.chmod(0o700)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(fallback / "qbox/matplotlib"))

    def test_forced_task_keeps_numeric_filename_and_handler_status(self):
        result = self.run_shell('run_qe_scf_calculation() { return 91; }; '
                                'ppin() { printf "input=%s" "$fname1"; return 17; }; '
                                'QBOX_TASK_ID=6 qe_main 11')
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(result.stdout, "input=11")

    def test_forced_relax_to_nscf_keeps_both_paths(self):
        result = self.run_shell('qbox_nscf_menu() { printf "%s|%s" "$fname1" "$fname2"; }; '
                                'QBOX_TASK_ID=27 qe_main "relax output.out" "nscf output.in"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "relax output.out|nscf output.in")

    def test_explicit_conversion_does_not_preconvert_input(self):
        result = self.run_shell('qe_is_vasp_structure_file() { return 0; }; '
                                'qe_auto_convert_vasp_to_cif() { echo UNEXPECTED; return 90; }; '
                                'qe_action_vasp_to_cif() { printf "%s" "$fname1"; }; '
                                'QBOX_TASK_ID=37 qe_main cell.vasp')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "cell.vasp")

    def test_legacy_band_plot_keeps_heredoc_noninteractive_stdin(self):
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                ["bash", "-c", 'QBOX_TEST_MODE=1 source "$1" || exit; '
                 'qbox_python() { test ! -t 0; }; qe_embedded_plot_band',
                 "band-stdin-test", str(ROOT / "qbox")],
                env=self.env, stdin=slave, text=True, capture_output=True, timeout=10,
            )
        finally:
            os.close(master)
            os.close(slave)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
