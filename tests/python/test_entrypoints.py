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
