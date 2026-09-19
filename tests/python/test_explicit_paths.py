"""Explicit task selection never consumes numeric filenames as legacy IDs."""

import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
PW_FIXTURE = ROOT / "tests/fixtures/expected/pw/water.scf.in"
CIF_FIXTURE = ROOT / "tests/fixtures/structures/water.cif"
VASP_FIXTURE = """water
1.0
10 0 0
0 10 0
0 0 10
O H
1 2
Direct
0.5 0.5 0.5
0.557 0.5 0.5
0.481 0.554 0.5
"""


class ExplicitPathTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="qbox explicit paths ")
        self.addCleanup(self.sandbox.cleanup)
        self.directory = Path(self.sandbox.name)
        self.env = os.environ.copy()
        for key in ("BASH_FUNC_module%%", "BASH_FUNC_ml%%", "QBOX_TASK_ID", "QBOX_TEST_MODE"):
            self.env.pop(key, None)
        self.env["QBOX_PYTHON"] = sys.executable
        self.env["PYTHONPATH"] = str(ROOT / "src")

    def run_cli(self, *args, input="/definitely/nonexistent-review-input\n"):
        return subprocess.run(
            [str(ROOT / "qbox"), *args], cwd=self.directory, env=self.env,
            text=True, capture_output=True, input=input, timeout=20,
        )

    def run_adapter(self, body, *args, input=""):
        return subprocess.run(
            ["bash", "-c", 'QBOX_TEST_MODE=1 source "$1" || exit; shift; ' + body,
             "explicit-path-test", str(ROOT / "qbox"), *args],
            cwd=self.directory, env=self.env, text=True, capture_output=True,
            input=input, timeout=20,
        )

    def test_explicit_scf_to_nscf_keeps_file_named_29(self):
        source = self.directory / "29"
        shutil.copyfile(PW_FIXTURE, source)
        original = source.read_bytes()
        result = self.run_cli("--task", "scf-to-nscf", "29")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = (self.directory / "29.nscf.in").read_text()
        self.assertIn("calculation     = 'nscf'", output)
        self.assertIn("6 6 6 0 0 0", output)
        self.assertEqual(source.read_bytes(), original)

    def test_legacy_scf_selector_still_prompts_for_input(self):
        shutil.copyfile(PW_FIXTURE, self.directory / "source.scf.in")
        result = self.run_cli("29", input="source.scf.in\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("calculation     = 'nscf'", (self.directory / "source.nscf.in").read_text())

    def test_explicit_cif_to_vasp_keeps_file_named_36(self):
        shutil.copyfile(CIF_FIXTURE, self.directory / "36")
        result = self.run_cli("--task", "cif-to-vasp", "36")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = (self.directory / "36.vasp").read_text()
        self.assertIn("Direct", output)
        self.assertIn("H", output)
        self.assertIn("O", output)

    def test_explicit_vasp_to_cif_keeps_file_named_37(self):
        (self.directory / "37").write_text(VASP_FIXTURE)
        result = self.run_cli("--task", "vasp-to-cif", "37")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = (self.directory / "37.cif").read_text()
        self.assertIn("_cell_length_a", output)
        self.assertIn("_atom_site_fract_x", output)

    def test_explicit_plot_inputs_are_not_replaced_by_numeric_selectors(self):
        for filename, second in (("19", ""), ("provided.cif", "19")):
            with self.subTest(filename=filename, second=second):
                (self.directory / filename).write_text("0 -1\n1 1\n")
                (self.directory / "bands.dat.gnu").write_text("0 100\n1 200\n")
                result = self.run_adapter(
                    'qe_embedded_plot_band() { printf "%s\\n" "$@" > selected.args; }; '
                    'QBOX_TASK_ID=19; qe_prepare_invocation "$@" || exit; plot_qe_band',
                    filename, second, input="1\n\n\n\n4\n",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                selected = (self.directory / "selected.args").read_text().splitlines()
                self.assertEqual(selected[:2], ["-i", filename])

    def test_legacy_plot_selectors_still_use_default_band_data(self):
        for filename, second in (("19", ""), ("provided.cif", "19")):
            with self.subTest(filename=filename, second=second):
                (self.directory / filename).write_text("0 -1\n1 1\n")
                (self.directory / "bands.dat.gnu").write_text("0 100\n1 200\n")
                result = self.run_adapter(
                    'qe_embedded_plot_band() { printf "%s\\n" "$@" > selected.args; }; '
                    'fname1="$1"; fname2="$2"; plot_qe_band',
                    filename, second, input="1\n\n\n\n4\n",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                selected = (self.directory / "selected.args").read_text().splitlines()
                self.assertEqual(selected[:2], ["-i", "bands.dat.gnu"])

    def test_explicit_dopant_pdos_keeps_file_named_28(self):
        shutil.copyfile(PW_FIXTURE, self.directory / "28")
        # The legacy fallback can find this alternative, making a wrong branch
        # terminate normally rather than hanging on a missing-input prompt.
        shutil.copyfile(CIF_FIXTURE, self.directory / "28.cif")
        (self.directory / "water.pdos_atm#1").write_text("0 1\n")
        result = self.run_adapter(
            'qbox_python() { printf "%s\\n" "$@" > selected.args; }; '
            'QBOX_TASK_ID=28; fname1=28; analyze_qe_dopant_pdos',
            input="\n\n\n\n\n\n",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        selected = (self.directory / "selected.args").read_text().splitlines()
        self.assertEqual(selected[selected.index("--structure") + 1], "28")

    def test_explicit_secondary_numeric_path_does_not_disable_vasp_conversion(self):
        (self.directory / "water.vasp").write_text(VASP_FIXTURE)
        for second in ("36", "37"):
            with self.subTest(second=second):
                result = self.run_adapter(
                    'run_qe_scf_calculation() { printf "%s\\n" "$fname1" "$fname2" > selected.args; }; '
                    'QBOX_TASK_ID=11 qe_main "$@"', "water.vasp", second,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                selected = (self.directory / "selected.args").read_text().splitlines()
                self.assertEqual(selected, ["water.cif", second])
                self.assertIn("_cell_length_a", (self.directory / "water.cif").read_text())

    def effective_mass_command(self, offline):
        from qbox.postprocess import effective_mass_qe

        (self.directory / "CBM.dat").write_text("0.0 1.0\n1.0 2.0\n")
        (self.directory / "bands.in").write_text(
            "K_POINTS crystal_b\n2\n0 0 0 20 ! G\n0.5 0 0 20 ! X\n"
        )
        (self.directory / "bands.out").write_text(
            "x coordinate 0.0\nx coordinate 1.0\n"
        )
        script = self.directory / "fit script.py"
        original_cwd = Path.cwd()
        environment = {"_QBOX_OFFLINE_ROOT": "/offline/release"} if offline else {}
        try:
            os.chdir(self.directory)
            with contextlib.redirect_stdout(io.StringIO()), \
                    patch.dict(os.environ, environment, clear=True), \
                    patch("qbox.postprocess.effective_mass_qe.subprocess.call", return_value=0) as call:
                with self.assertRaisesRegex(SystemExit, "0"):
                    effective_mass_qe.main([
                        "--band", "CBM.dat", "--band-input", "bands.in",
                        "--bands-output", "bands.out", "--alat-angstrom", "2.0",
                        "--vasp-script", str(script), "--window", "0.12",
                    ])
        finally:
            os.chdir(original_cwd)
        return call.call_args.args[0]

    def test_effective_mass_secondary_python_is_isolated_offline(self):
        command = self.effective_mass_command(offline=True)
        self.assertEqual(command[:4], [sys.executable, "-I", "-B", str(self.directory / "fit script.py")])
        self.assertEqual(command[-2:], ["--window", "0.12"])

    def test_effective_mass_secondary_python_keeps_ordinary_install_contract(self):
        command = self.effective_mass_command(offline=False)
        self.assertEqual(command[:2], [sys.executable, str(self.directory / "fit script.py")])
        self.assertNotIn("-I", command)
        self.assertNotIn("-B", command)


if __name__ == "__main__":
    unittest.main()
