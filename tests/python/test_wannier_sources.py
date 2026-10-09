"""CIF discovery reuses only structurally matching, unmodified SCF inputs."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from qbox.io.wannier_inputs import parse_qe


ROOT = Path(__file__).resolve().parents[2]
SCF = """&CONTROL calculation='scf', prefix='iron', outdir='./tmp', pseudo_dir='./pseudo' /
&SYSTEM ibrav=0, nat=2, ntyp=1, nbnd=8 /
CELL_PARAMETERS angstrom
3 0 0
0 4 0
0 0 5
ATOMIC_SPECIES
Fe 55.8 Fe.UPF
ATOMIC_POSITIONS crystal
Fe 0 0 0
Fe .25 .5 .75
K_POINTS automatic
2 2 2 0 0 0
"""


class ExistingScfTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='wannier sources ')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.source = self.directory / 'my cell.cif'
        self.source.write_text('data_original\n')
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.wannier_sources'),
                             'CIF entry needs safe existing-SCF discovery')
        self.api = importlib.import_module('qbox.io.wannier_sources')

    def write(self, name, text=SCF):
        path = self.directory / name
        path.write_text(text)
        return path

    def discover(self, geometry=SCF):
        with patch.object(self.api, '_cif_geometry', return_value=parse_qe(geometry)) as reader:
            found = self.api.find_existing_scf(self.source, self.directory)
        return found, reader

    def test_no_scf_skips_cif_conversion_and_configuration(self):
        self.write('bands.in', SCF.replace("calculation='scf'", "calculation='bands'"))
        self.write('other.in', 'unrelated input')
        found, reader = self.discover()
        self.assertEqual(found, [])
        reader.assert_not_called()

    def test_qe_discovery_reuses_nscf_when_no_matching_scf_exists(self):
        candidate = self.write('my_cell.nscf.in', SCF.replace("calculation='scf'", "calculation='nscf'"))
        before = candidate.read_bytes()
        self.assertTrue(callable(getattr(self.api, 'find_existing_qe', None)))
        with patch.object(self.api, '_cif_geometry', return_value=parse_qe(SCF)):
            self.assertEqual(self.api.find_existing_qe(self.source, self.directory), [candidate])
        self.assertEqual(candidate.read_bytes(), before)

    def test_qe_discovery_prefers_matching_scf_and_rejects_wrong_nscf_structure(self):
        scf = self.write('scf.in')
        self.write('my_cell.nscf.in', SCF.replace("calculation='scf'", "calculation='nscf'"))
        self.assertTrue(callable(getattr(self.api, 'find_existing_qe', None)))
        with patch.object(self.api, '_cif_geometry', return_value=parse_qe(SCF)):
            self.assertEqual(self.api.find_existing_qe(self.source, self.directory), [scf])
            scf.unlink()
            (self.directory / 'my_cell.nscf.in').write_text(
                SCF.replace("calculation='scf'", "calculation='nscf'").replace('3 0 0', '3.1 0 0'))
            with self.assertRaisesRegex(ValueError, 'NSCF.*不匹配'):
                self.api.find_existing_qe(self.source, self.directory)

    def test_matching_original_name_wins_over_other_matching_inputs(self):
        preferred = self.write('my cell.scf.in')
        self.write('scf.in')
        self.write('my_cell.scf.in')
        found, reader = self.discover()
        self.assertEqual(found, [preferred])
        reader.assert_called_once()

    def test_sanitized_name_is_preferred_and_default_calculation_is_scf(self):
        preferred = self.write('my_cell.scf.in', SCF.replace("calculation='scf', ", ''))
        self.write('another.in')
        self.assertEqual(self.discover()[0], [preferred])

    def test_other_matching_candidates_are_all_returned_with_scf_in_first(self):
        second = self.write('a.in')
        first = self.write('scf.in')
        self.write('relax.in', SCF.replace("calculation='scf'", "calculation='relax'"))
        self.write('unreadable.in').unlink()
        (self.directory / 'unreadable.in').symlink_to(self.directory / 'missing')
        found, reader = self.discover()
        self.assertEqual(found, [first, second])
        reader.assert_called_once()

    def test_mismatching_other_structures_are_not_reused(self):
        self.write('wrong-cell.in', SCF.replace('3 0 0', '3.1 0 0'))
        self.write('wrong-atoms.in', SCF.replace('Fe .25 .5 .75', 'Fe .26 .5 .75'))
        self.write('wrong-element.in', SCF.replace('Fe', 'Co'))
        self.assertEqual(self.discover()[0], [])

    def test_preferred_bad_non_scf_and_mismatching_inputs_give_actionable_error(self):
        for text in ('invalid', SCF.replace("calculation='scf'", "calculation='nscf'"),
                     SCF.replace('Fe .25 .5 .75', 'Fe .3 .5 .75'),
                     SCF.replace("pseudo_dir='./pseudo'", "pseudo_dir=''")):
            with self.subTest(text=text):
                self.write('my cell.scf.in', text)
                with self.assertRaisesRegex(ValueError, '菜单 2'):
                    self.discover()

    def test_periodic_reordering_spin_labels_and_small_rounding_are_accepted(self):
        text = SCF.replace('ntyp=1', 'ntyp=2').replace('Fe 55.8 Fe.UPF', 'Fe1 55.8 Fe.UPF\nFe2 55.8 Fe.UPF')
        text = text.replace('Fe 0 0 0\nFe .25 .5 .75', 'Fe2 1.2500001 -.5 .75\nFe1 0 0 1')
        candidate = self.write('scf.in', text)
        self.assertEqual(self.discover()[0], [candidate])
        candidate.write_text(text.replace('Fe1', 'Fe_up').replace('Fe2', 'Fe_down'))
        self.assertEqual(self.discover()[0], [candidate])

    def test_uniform_rotation_is_accepted_but_supercells_are_not(self):
        rotated = SCF.replace('3 0 0\n0 4 0\n0 0 5', '0 3 0\n-4 0 0\n0 0 5')
        candidate = self.write('scf.in', rotated)
        self.assertEqual(self.discover()[0], [candidate])
        candidate.write_text(SCF.replace('3 0 0', '6 0 0'))
        self.assertEqual(self.discover()[0], [])

    def test_matching_needs_one_to_one_atom_correspondence(self):
        self.write('scf.in', SCF.replace('Fe .25 .5 .75', 'Fe 0 0 0'))
        self.assertEqual(self.discover()[0], [])

    def test_long_axis_does_not_relax_tolerance_for_other_lattice_vectors(self):
        geometry = SCF.replace('0 0 5', '0 0 1000')
        self.write('scf.in', geometry.replace('3 0 0', '3.001 0 0'))
        self.assertEqual(self.discover(geometry)[0], [])

    def test_preferred_symlink_keeps_alias_path_and_all_sources_unchanged(self):
        target = self.write('actual.in')
        preferred = self.directory / 'my cell.scf.in'
        preferred.symlink_to(target)
        before = {p: p.read_bytes() for p in (target, self.source)}
        self.assertEqual(self.discover()[0], [preferred])
        self.assertTrue(preferred.is_symlink())
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        preferred.unlink()
        preferred.symlink_to(self.directory / 'missing')
        with self.assertRaisesRegex(ValueError, '菜单 2'):
            self.discover()

    def test_conversion_failure_preserves_files_and_cleans_private_directory(self):
        candidate = self.write('scf.in')
        before = self.source.read_bytes(), candidate.read_bytes()
        failure = subprocess.CompletedProcess([], 7, stdout='', stderr='Multiwfn failed')
        with patch.object(self.api.subprocess, 'run', return_value=failure):
            with self.assertRaisesRegex(ValueError, 'CIF.*退出码 7'):
                self.api.find_existing_scf(self.source, self.directory)
        self.assertEqual((self.source.read_bytes(), candidate.read_bytes()), before)
        self.assertFalse(list(self.directory.glob('.qbox-*')))

    def test_real_legacy_structure_seam_needs_no_pseudos_and_runs_no_calculation(self):
        self.source.write_bytes((ROOT / 'tests/fixtures/structures/water.cif').read_bytes())
        geometry = (ROOT / 'tests/fixtures/qe-inputs/water_QE.tmp').read_text()
        candidate = self.write('scf.in', geometry + '\nATOMIC_SPECIES\nH 1 H.UPF\nO 16 O.UPF\n')
        tools = self.directory / 'tools'; tools.mkdir()
        counter = self.directory / 'multiwfn.calls'
        converter = tools / 'Multiwfn'
        converter.write_text('#!/usr/bin/env python3\nimport os, pathlib, shutil, sys\n'
                             'lines = sys.stdin.read().splitlines()\n'
                             'with open(os.environ["CALLS"], "a") as stream: stream.write("call\\n")\n'
                             'shutil.copyfile(os.environ["GEOMETRY"], lines[3])\n')
        converter.chmod(0o755)
        for name in ('pw.x', 'pw2wannier90.x', 'wannier90.x'):
            binary = tools / name
            binary.write_text('#!/bin/sh\nprintf called > "$FORBIDDEN"\nexit 99\n')
            binary.chmod(0o755)
        env = {**os.environ, 'QBOX_PSEUDO_ROOT': '', 'QBOX_MULTIWFN_HOME': str(tools),
               'QBOX_PYTHON': sys.executable, 'PYTHONPATH': str(ROOT / 'src'),
               'PATH': str(tools) + os.pathsep + os.environ['PATH'], 'CALLS': str(counter),
               'GEOMETRY': str(ROOT / 'tests/fixtures/qe-inputs/water_QE.tmp'),
               'FORBIDDEN': str(self.directory / 'calculation-ran')}
        before = self.source.read_bytes(), candidate.read_bytes()
        script = ('import sys; from qbox.io.wannier_sources import find_existing_scf; '
                  'print(*find_existing_scf(sys.argv[1]), sep="\\n")')
        result = subprocess.run([sys.executable, '-c', script, str(self.source)], cwd=self.directory,
                                env=env, input='', text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(candidate))
        self.assertEqual(counter.read_text(), 'call\n')
        self.assertFalse((self.directory / 'calculation-ran').exists())
        self.assertFalse(list(self.directory.glob('.qbox-*')))
        self.assertEqual((self.source.read_bytes(), candidate.read_bytes()), before)


if __name__ == '__main__':
    unittest.main()
