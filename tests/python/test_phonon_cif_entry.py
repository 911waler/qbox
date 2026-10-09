"""Exercise CIF startup through the public launcher and main-menu task 2."""
import os
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCF = """&CONTROL calculation='scf', prefix='silicon', outdir='./scratch' /
&SYSTEM ibrav=0, nat=2, ntyp=1, ecutwfc=40, occupations='fixed' /
&ELECTRONS conv_thr=1d-10 /
ATOMIC_SPECIES
Si 28.085 Si.upf
CELL_PARAMETERS angstrom
0 2.7 2.7
2.7 0 2.7
2.7 2.7 0
ATOMIC_POSITIONS crystal
Si 0 0 0
Si 0.25 0.25 0.25
K_POINTS automatic
4 4 4 0 0 0
"""
CIF = """data_silicon
_cell_length_a 3.8183766184
_cell_length_b 3.8183766184
_cell_length_c 3.8183766184
_cell_angle_alpha 60
_cell_angle_beta 60
_cell_angle_gamma 60
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0 0 0
Si2 Si 0.25 0.25 0.25
"""


class PhononCifEntrypointTests(unittest.TestCase):
    def launch(self, directory, answers, extra_env=None):
        env = os.environ.copy()
        for key in ('BASH_FUNC_module%%', 'BASH_FUNC_ml%%', 'QBOX_TASK_ID',
                    'QBOX_TEST_MODE', 'QE_DIRECT_ACTION'):
            env.pop(key, None)
        env.update(QBOX_PYTHON=sys.executable, PYTHONPATH=str(ROOT / 'src'))
        env.update(extra_env or {})
        return subprocess.run([str(ROOT / 'qbox'), 'relax.cif'], cwd=directory,
                              env=env, input=answers, text=True,
                              capture_output=True, timeout=30)

    def wizard_environment(self, root, *, fail=False):
        """Keep the real qbox/pwin flow; replace only external executables."""
        tools = root / 'tools'
        tools.mkdir()
        fixture = tools / 'silicon_QE.tmp'
        fixture.write_text('''&SYSTEM
 nat 2
 ntyp 1
/
CELL_PARAMETERS angstrom
0 2.7 2.7
2.7 0 2.7
2.7 2.7 0
ATOMIC_POSITIONS angstrom
Si 0 0 0
Si 1.35 1.35 1.35
''')
        converter = tools / 'Multiwfn'
        converter.write_text('#!/usr/bin/env python3\n'
                             'import os, shutil, sys\n'
                             'lines = sys.stdin.read().splitlines()\n'
                             'if os.environ.get("PHONON_CONVERTER_FAIL") == "1": sys.exit(7)\n'
                             'shutil.copyfile(os.environ["PHONON_STRUCTURE_FIXTURE"], lines[3])\n')
        converter.chmod(0o755)
        for name in ('pw.x', 'ph.x', 'q2r.x', 'matdyn.x', 'dynmat.x'):
            binary = tools / name
            binary.write_text('#!/bin/sh\nprintf executed > "$PHONON_FORBIDDEN_EXECUTION"\nexit 9\n')
            binary.chmod(0o755)
        pseudos = root / 'pseudos' / 'QE' / 'SSSP'
        pseudos.mkdir(parents=True)
        (pseudos / 'Si.UPF').write_text('test pseudo')
        return {
            'QBOX_MULTIWFN_HOME': str(tools), 'QBOX_PSEUDO_ROOT': str(root / 'pseudos'),
            'PATH': str(tools) + os.pathsep + os.environ['PATH'],
            'PHONON_STRUCTURE_FIXTURE': str(fixture),
            'PHONON_FORBIDDEN_EXECUTION': str(root / 'ran-calculation'),
            'PHONON_CONVERTER_FAIL': '1' if fail else '0',
            # The embedded wizard must stay interactive and force the SCF task.
            'PRESET_RTASK': 'bands', 'NONINTERACTIVE_PWIN': '1',
            'QBOX_INPUT_MENU_TIMEOUT': '1',
        }

    def test_cif_startup_selects_scf_and_generates_gamma_inputs(self):
        with tempfile.TemporaryDirectory(prefix='qbox phonon cif ') as directory:
            root = Path(directory)
            (root / 'relax.cif').write_text(CIF)
            (root / 'relax.scf.in').write_text(SCF)
            result = self.launch(directory, '2\n\n3\n1\n\n')
            transcript = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, transcript)
            self.assertEqual(result.stdout.count('请输入功能编号。'), 1, transcript)
            self.assertTrue((root / 'silicon.ph.in').exists(), transcript)
            self.assertTrue((root / 'silicon.dynmat.in').exists(), transcript)
            readme = root / 'silicon.README.txt'
            self.assertTrue(readme.is_file(), transcript)
            self.assertNotIn('pw.x -in', transcript)
            self.assertNotIn('dynmat.x -in', transcript)
            self.assertIn('pw.x -in relax.scf.in > scf.out', readme.read_text().splitlines())
            self.assertIn('mpirun -np 32 ph.x -in silicon.ph.in > ph.out', readme.read_text().splitlines())
            self.assertIn('dynmat.x -in silicon.dynmat.in > dynmat.out', readme.read_text().splitlines())
            self.assertIn("prefix='silicon'", (root / 'silicon.ph.in').read_text().replace(' ', ''))
            self.assertNotIn('SCF 输入必须包含', transcript)
            self.assertNotIn('Traceback', transcript)

    def test_cif_without_scf_opens_wizard_and_continues_to_gamma(self):
        with tempfile.TemporaryDirectory(prefix='qbox phonon cif ') as directory:
            root = Path(directory)
            source = root / 'relax.cif'
            source.write_text(CIF)
            environment = self.wizard_environment(root)
            result = self.launch(directory, '2\n0\n3\n1\n\n', environment)
            transcript = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, transcript)
            self.assertEqual(result.stdout.count('请输入功能编号。'), 1, transcript)
            self.assertTrue((root / 'relax.scf.in').is_file(), transcript)
            self.assertTrue((root / 'relax.ph.in').is_file(), transcript)
            self.assertTrue((root / 'relax.dynmat.in').is_file(), transcript)
            self.assertNotIn('请选择需要生成的 pw.x 输入文件类型', transcript)
            self.assertNotIn('请输入 pw.x SCF 输入文件路径', transcript)
            self.assertNotIn('选择 SCF 编号', transcript)
            from qbox.io.phonon_inputs import load_scf
            scf = load_scf(root / 'relax.scf.in')
            self.assertEqual(scf.prefix, 'relax')
            self.assertEqual(scf.outdir, str(root / 'tmp'))
            self.assertIn(str(root / 'tmp'), (root / 'relax.ph.in').read_text())
            self.assertEqual(source.read_text(), CIF)
            self.assertFalse(list(root.glob('.qbox-*-scf-*')))
            self.assertFalse((root / 'ran-calculation').exists())

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in
                             ('numpy', 'seekpath', 'pymatgen', 'ase')),
                         'CIF dispersion requires optional structure/path dependencies')
    def test_cif_without_scf_continues_to_dispersion_with_original_structure(self):
        with tempfile.TemporaryDirectory(prefix='qbox phonon cif ') as directory:
            root = Path(directory)
            (root / 'relax.cif').write_text(CIF)
            environment = self.wizard_environment(root)
            result = self.launch(directory, '2\n0\n3\n2\n\n', environment)
            transcript = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, transcript)
            self.assertEqual(result.stdout.count('请输入功能编号。'), 1, transcript)
            for suffix in ('scf.in', 'ph.in', 'q2r.in', 'matdyn.in', 'path.json', 'README.txt'):
                self.assertTrue((root / ('relax.' + suffix)).is_file(), transcript)
            self.assertNotIn('q2r.x -in', transcript)
            self.assertNotIn('qbox.postprocess.phonon_plot', transcript)
            readme = (root / 'relax.README.txt').read_text()
            commands = ['pw.x -in relax.scf.in > scf.out',
                        'mpirun -np 32 ph.x -in relax.ph.in > ph.out',
                        'q2r.x -in relax.q2r.in > q2r.out',
                        'matdyn.x -in relax.matdyn.in > matdyn.out']
            offsets = [readme.index(command) for command in commands]
            self.assertEqual(offsets, sorted(offsets))
            self.assertNotIn('cd ', readme)
            self.assertNotIn('qbox.postprocess.phonon_plot', readme)
            self.assertIn(str(root / 'relax.cif'), transcript)
            self.assertFalse((root / 'ran-calculation').exists())
            self.assertFalse(list(root.glob('.qbox-*-scf-*')))

    def test_explicit_phonon_back_returns_to_main_menu(self):
        with tempfile.TemporaryDirectory(prefix='qbox phonon cif ') as directory:
            root = Path(directory)
            (root / 'relax.cif').write_text(CIF)
            (root / 'relax.scf.in').write_text(SCF)
            result = self.launch(directory, '2\n\n5\n')
            transcript = result.stdout + result.stderr
            self.assertEqual(result.stdout.count('请输入功能编号。'), 2, transcript)
            self.assertFalse((root / 'silicon.ph.in').exists())

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in
                             ('numpy', 'seekpath', 'pymatgen', 'ase')),
                         'CIF dispersion requires optional structure/path dependencies')
    def test_multiwfn_cif_generates_without_parser_noise_and_keeps_commands_in_readme(self):
        fixture = (ROOT / 'tests/fixtures/structures/phonon_sic.cif').read_text()
        atoms = '\n'.join(line for line in fixture.splitlines()
                          if line.split() and line.split()[0] in ('Si', 'C'))
        with tempfile.TemporaryDirectory(prefix='qbox compact phonon ') as directory:
            root = Path(directory)
            source = root / 'relax.cif'
            source.write_text(fixture)
            (root / 'relax.scf.in').write_text(
                "&CONTROL calculation='scf', prefix='sic', outdir='./tmp' /\n"
                "&SYSTEM ibrav=0, nat=8, ntyp=2, ecutwfc=40, occupations='fixed' /\n"
                "&ELECTRONS conv_thr=1d-10 /\nATOMIC_SPECIES\nSi 28.085 Si.upf\nC 12.011 C.upf\n"
                "CELL_PARAMETERS angstrom\n3.094936 0 0\n-1.547468 2.6802932 0\n0 0 10.132228\n"
                'ATOMIC_POSITIONS crystal\n' + atoms + '\nK_POINTS automatic\n4 4 4 0 0 0\n')
            result = self.launch(directory, '2\n\n3\n2\n\n')
            transcript = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, transcript)
            self.assertNotIn('UserWarning', transcript)
            self.assertNotIn('Cannot determine chemical composition', transcript)
            self.assertNotIn('fractional coordinates rounded', transcript)
            self.assertNotIn('pw.x -in', transcript)
            self.assertNotIn('qbox.postprocess.phonon_plot', transcript)
            self.assertTrue((root / 'sic.README.txt').is_file(), transcript)
            self.assertTrue((root / 'sic.matdyn.in').is_file(), transcript)
            self.assertEqual(source.read_text(), fixture)

    def test_thermo_generation_exits_after_writing_shermo_input(self):
        with tempfile.TemporaryDirectory(prefix='qbox phonon cif ') as directory:
            root = Path(directory)
            (root / 'relax.cif').write_text(CIF)
            (root / 'relax.scf.in').write_text(SCF)
            (root / 'silicon.molden').write_text('[FREQ]\n123.5\n[FR-COORD]\n')
            result = self.launch(directory, '2\n\n2\n2\n\n\n')
            transcript = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, transcript)
            self.assertEqual(result.stdout.count('请输入功能编号。'), 1, transcript)
            self.assertTrue((root / 'silicon.shm').is_file(), transcript)
            self.assertTrue((root / 'silicon.README.txt').is_file(), transcript)
            self.assertNotIn('Shermo silicon.shm', transcript)
            self.assertIn('Shermo silicon.shm -T 298.15 -P 1 -imode 0',
                          (root / 'silicon.README.txt').read_text().splitlines())

    def test_cif_without_scf_can_cancel_wizard_and_return_to_main_menu(self):
        with tempfile.TemporaryDirectory(prefix='qbox phonon cif ') as directory:
            root = Path(directory)
            (root / 'relax.cif').write_text(CIF)
            environment = self.wizard_environment(root)
            result = self.launch(directory, '2\n14\n', environment)
            transcript = result.stdout + result.stderr
            self.assertNotIn('SCF 输入必须包含', transcript)
            self.assertNotIn('Traceback', transcript)
            self.assertIn('已取消 SCF 输入生成', transcript)
            self.assertGreaterEqual(result.stdout.count('请输入功能编号。'), 2, transcript)
            self.assertEqual(sorted(path.name for path in root.iterdir()),
                             ['pseudos', 'relax.cif', 'tools'])

    def test_cif_without_scf_stops_on_wizard_eof_or_failure(self):
        for fail in (False, True):
            with self.subTest(converter_failure=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'relax.cif').write_text(CIF)
                environment = self.wizard_environment(root, fail=fail)
                result = self.launch(directory, '2\n', environment)
                transcript = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, transcript)
                self.assertIn('SCF 输入生成失败', transcript)
                self.assertNotIn('选择体系：', transcript)
                self.assertEqual(sorted(path.name for path in root.iterdir()),
                                 ['pseudos', 'relax.cif', 'tools'])


if __name__ == '__main__':
    unittest.main()
