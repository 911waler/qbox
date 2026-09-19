"""Behavior contracts for Python algorithms extracted from the shell frontend."""

import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "io.kpath", "io.upf_valence", "io.electron_count", "io.ldos_reference",
    "io.convert_pymatgen", "io.convert_ase", "io.convert_basic",
    "io.effective_mass_inputs", "io.unfold_patch_bands", "io.unfold_validate_pair",
    "io.unfold_validate_pseudos", "io.unfold_write_input",
    "postprocess.band_plot", "postprocess.band_edges", "postprocess.band_edges_reference",
    "postprocess.band_edges_plot", "postprocess.pdos_plot", "postprocess.effective_mass_vasp",
    "postprocess.effective_mass_qe", "postprocess.unfold_effective_mass_inputs",
    "postprocess.ldos_plot", "postprocess.optics_plot", "postprocess.convergence_plot",
    "postprocess.unfold_discover", "postprocess.unfold_geometry", "postprocess.unfold_plot",
    "postprocess.unfold_edges", "postprocess.dopant_pdos",
)


class ExtractedPythonTests(unittest.TestCase):
    def environment(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["MPLBACKEND"] = "Agg"
        return env

    def run_module(self, name, *args, cwd):
        return subprocess.run(
            [sys.executable, "-m", "qbox." + name, *map(str, args)],
            cwd=cwd, env=self.environment(), text=True, capture_output=True,
        )

    def test_imports_do_not_run_tools_or_create_working_files(self):
        # Parsing sys.argv or running a scientific workflow at import would fail
        # against this deliberately nonexistent argument and empty directory.
        code = (
            "import importlib, pathlib, sys, matplotlib; matplotlib.use('svg'); "
            "sys.argv = ['caller', '/nonexistent/qbox-import-fixture']; "
            "[importlib.import_module('qbox.' + name) for name in " + repr(MODULES) + "]; "
            "assert not list(pathlib.Path('.').iterdir()); "
            "assert matplotlib.get_backend() == 'svg'"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=directory,
                env=self.environment(), text=True, capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_upf_valence_preserves_fortran_exponent_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Si.upf"
            path.write_text('<PP_HEADER z_valence="4.0D+0"/>\n')
            result = self.run_module("io.upf_valence", path, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "4\n")
            path.write_text('<PP_HEADER z_valence="0"/>\n')
            result = self.run_module("io.upf_valence", path, cwd=directory)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")

    def test_band_edges_preserve_missing_conduction_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bands.dat.gnu"
            source.write_text("0 -2\n1 -1\n\n0 1\n1 3\n")
            result = self.run_module(
                "postprocess.band_edges", source, 1, 2,
                root / "VBM.dat", root / "CBM.dat", cwd=directory,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "2\n")
            self.assertEqual((root / "VBM.dat").read_text(), "    0.000000    -2.00000000\n    1.000000    -1.00000000\n")
            self.assertEqual((root / "CBM.dat").read_text(), "    0.000000     1.00000000\n    1.000000     3.00000000\n")
            result = self.run_module(
                "postprocess.band_edges", source, 2, 3,
                root / "VBM.dat", root / "CBM.dat", cwd=directory,
            )
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_ldos_reference_can_be_called_without_changing_process_argv(self):
        sys.path.insert(0, str(ROOT / "src"))
        try:
            module = importlib.import_module("qbox.io.ldos_reference")
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "scf.out"
                source.write_text(
                    "./tmp/silicon.save\n"
                    "the Fermi energy is 4.2500 ev\n"
                    "FFT dimensions: ( 20, 24, 28)\n"
                )
                from contextlib import redirect_stdout
                original_argv = sys.argv[:]
                output = io.StringIO()
                with redirect_stdout(output):
                    module.main([str(source)])
                self.assertEqual(output.getvalue(), "silicon 4.2500 20 24 28\n")
                self.assertEqual(sys.argv, original_argv)
        finally:
            sys.path.remove(str(ROOT / "src"))

    def test_argparse_entrypoints_use_explicit_arguments(self):
        # Ignoring argv would parse unittest's own options or try reading files.
        from contextlib import redirect_stdout, redirect_stderr
        sys.path.insert(0, str(ROOT / "src"))
        try:
            for name in (
                "io.kpath", "postprocess.band_plot", "postprocess.pdos_plot",
                "postprocess.effective_mass_vasp", "postprocess.effective_mass_qe",
                "postprocess.ldos_plot", "postprocess.optics_plot", "postprocess.dopant_pdos",
            ):
                with self.subTest(module=name):
                    module = importlib.import_module("qbox." + name)
                    output, errors = io.StringIO(), io.StringIO()
                    with redirect_stdout(output), redirect_stderr(errors):
                        with self.assertRaises(SystemExit) as exit_context:
                            module.main(["--help"])
                    self.assertEqual(exit_context.exception.code, 0, errors.getvalue())
                    self.assertIn("usage:", output.getvalue())
        finally:
            sys.path.remove(str(ROOT / "src"))

    def test_kpath_call_does_not_silence_other_library_warnings(self):
        from contextlib import redirect_stdout
        import warnings
        sys.path.insert(0, str(ROOT / "src"))
        try:
            module = importlib.import_module("qbox.io.kpath")
            filters = warnings.filters[:]
            showwarning = warnings.showwarning
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    module.main(["--help"])
            self.assertEqual(warnings.filters, filters)
            self.assertIs(warnings.showwarning, showwarning)
        finally:
            sys.path.remove(str(ROOT / "src"))

    def test_electron_count_accounts_for_charge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "C.upf").write_text('<PP_HEADER z_valence="4"/>\n')
            source = root / "scf.in"
            source.write_text(
                "&SYSTEM\n tot_charge = 1.0D+0,\n/\n"
                "ATOMIC_SPECIES\nC 12.0 C.upf\n"
                "ATOMIC_POSITIONS crystal\nC 0 0 0\nC .5 .5 .5\n"
                "K_POINTS gamma\n"
            )
            result = self.run_module("io.electron_count", source, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "7\n")

    def test_builtin_structure_conversion_preserves_cell_and_atoms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cif, poscar, converted = root / "cell.cif", root / "cell.vasp", root / "converted.cif"
            cif.write_text(
                "data_cell\n_cell_length_a 4\n_cell_length_b 4\n_cell_length_c 4\n"
                "_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n"
                "loop_\n_atom_site_label\n_atom_site_type_symbol\n"
                "_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"
                "C1 C 0 0 0\nC2 C .5 .5 .5\n"
            )
            result = self.run_module("io.convert_basic", "cif2vasp", cif, poscar, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = poscar.read_text().splitlines()
            self.assertEqual(lines[5].split(), ["C"])
            self.assertEqual(lines[6].split(), ["2"])
            self.assertEqual([float(item) for item in lines[2].split()], [4.0, 0.0, 0.0])
            self.assertEqual([float(item) for item in lines[9].split()], [0.5, 0.5, 0.5])
            result = self.run_module("io.convert_basic", "vasp2cif", poscar, converted, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("_cell_length_a 4.0000000000", converted.read_text())
            self.assertIn("C2 C 0.500000000000 0.500000000000 0.500000000000", converted.read_text())


if __name__ == "__main__":
    unittest.main()
