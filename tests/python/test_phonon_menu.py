"""Task 2 navigation exercises generated inputs without launching QE."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

SCF = """&CONTROL calculation='scf', prefix='silicon', outdir='./tmp' /
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
{species}1 {species} 0 0 0
{species}2 {species} 0.25 0.25 0.25
"""
HAS_PATH_DEPS = all(importlib.util.find_spec(name) is not None
                    for name in ('numpy', 'seekpath'))
HAS_CIF_PATH_DEPS = HAS_PATH_DEPS and all(importlib.util.find_spec(name) is not None
                                        for name in ('pymatgen', 'ase'))
SCF_WIZARD = 'qbox.io.wannier_cif.generate_scf_from_cif'


class PhononMenuTests(unittest.TestCase):
    def menu(self):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.phonon_menu'),
                             'task 2 needs a validated interactive entry point')
        from qbox.io import phonon_menu
        return phonon_menu

    def session(self, directory, answers, text=SCF, source=True, **options):
        menu = self.menu()
        path = Path(directory) / 'silicon.scf.in'
        path.write_text(text)
        entries = iter(answers)
        output = []
        def read(prompt):
            output.append(prompt)
            try:
                return next(entries)
            except StopIteration:
                raise EOFError
        status = menu.run_interactive(path if source else None, output_dir=directory,
                                      input_fn=read, output=output.append, **options)
        return status, '\n'.join(output)

    def source_session(self, source, directory, answers, cwd, **options):
        entries = iter(answers)
        output = []
        def read(prompt):
            output.append(prompt)
            return next(entries)
        previous = Path.cwd()
        try:
            os.chdir(cwd)
            status = self.menu().run_interactive(source, output_dir=directory,
                                                 input_fn=read, output=output.append, **options)
        finally:
            os.chdir(previous)
        return status, '\n'.join(output)

    def write_cif(self, path, species='Si'):
        path.write_text(CIF.format(species=species))

    def test_cif_entry_accepts_single_scf_default_and_uses_scf_prefix_and_outdir(self):
        with tempfile.TemporaryDirectory(prefix='phonon CIF ') as directory:
            root = Path(directory)
            calculation, workspace = root / 'calculation', root / 'workspace'
            calculation.mkdir()
            workspace.mkdir()
            cif = calculation / 'Relax structure.CIF'
            self.write_cif(cif)
            scf = calculation / 'Relax structure.scf.in'
            scf.write_text(SCF)
            before = {p.name: p.read_bytes() for p in calculation.iterdir()}
            with patch(SCF_WIZARD, side_effect=AssertionError('An existing SCF needs no wizard')) as wizard:
                status, output = self.source_session(cif, workspace, ['', '3', '1', ''], workspace)
            wizard.assert_not_called()
            self.assertEqual(status, 0, output)
            ph = (workspace / 'silicon.ph.in').read_text()
            self.assertIn("prefix = 'silicon'", ph)
            self.assertIn(str(calculation / 'tmp'), ph)
            self.assertIn(str(scf), output)
            self.assertEqual(before, {p.name: p.read_bytes() for p in calculation.iterdir()})

    @unittest.skipUnless(HAS_CIF_PATH_DEPS, 'CIF paths require numpy, seekpath, pymatgen and ASE')
    def test_cif_entry_dispersion_preserves_explicit_cif_in_other_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calculation, workspace = root / 'calculation', root / 'workspace'
            calculation.mkdir()
            workspace.mkdir()
            cif = calculation / 'Relax structure.CIF'
            self.write_cif(cif)
            (workspace / 'chosen.scf.in').write_text(SCF)
            self.write_cif(workspace / 'chosen.cif', species='C')
            status, output = self.source_session(cif, workspace, ['', '3', '2', ''], workspace)
            self.assertEqual(status, 0, output)
            metadata = json.loads((workspace / 'silicon.path.json').read_text())
            self.assertEqual(metadata['cell_angstrom'], [[0, 2.7, 2.7], [2.7, 0, 2.7], [2.7, 2.7, 0]])
            self.assertGreater(len(metadata['qpoints']), 1)
            self.assertIn(str(cif), output)

    def test_cif_entry_candidate_selection_can_return_or_reach_eof_without_writing(self):
        for count in (1, 2):
            for answers, expected in ((['b'], 0), ([], 1)):
                with self.subTest(count=count, answers=answers), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    cif = root / 'relax.cif'
                    self.write_cif(cif)
                    for index in range(count):
                        (root / f'candidate{index}.scf.in').write_text(SCF)
                    before = {p.name: p.read_bytes() for p in root.iterdir()}
                    with patch(SCF_WIZARD, side_effect=AssertionError('An existing SCF needs no wizard')) as wizard:
                        status, output = self.source_session(cif, root, answers, root)
                    wizard.assert_not_called()
                    self.assertEqual(status, expected, output)
                    self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_cif_without_scf_runs_wizard_then_uses_its_result_and_original_cif(self):
        with tempfile.TemporaryDirectory(prefix='phonon wizard ') as directory:
            root = Path(directory)
            source_dir, workspace = root / 'source', root / 'output'
            source_dir.mkdir()
            workspace.mkdir()
            cif = source_dir / 'original structure.CIF'
            self.write_cif(cif)
            generated = workspace / 'published.scf.in'
            def generate(source, *, output_dir, input_fn, output):
                self.assertEqual(source, cif.resolve())
                self.assertEqual(Path(output_dir), workspace)
                self.assertTrue(callable(input_fn))
                self.assertTrue(callable(output))
                generated.write_text(SCF.replace("prefix='silicon'", "prefix='from_wizard'"))
                self.write_cif(workspace / 'published.cif', species='C')
                return generated
            with patch(SCF_WIZARD, side_effect=generate) as wizard:
                # Inspect the dispersion source, then generate Gamma inputs without scientific dependencies.
                status, output = self.source_session(cif, workspace, ['3', '2', '2', '1', ''], workspace)
            self.assertEqual(status, 0, output)
            wizard.assert_called_once()
            self.assertIn(f'高对称路径的结构来源：\n    {cif}', output)
            self.assertNotIn('选择 SCF 编号', output)
            self.assertNotIn('请输入 pw.x SCF 输入文件路径', output)
            ph = (workspace / 'from_wizard.ph.in').read_text()
            self.assertIn("prefix = 'from_wizard'", ph)
            self.assertIn(str(workspace / 'tmp'), ph)
            self.assertEqual([p.name for p in source_dir.iterdir()], [cif.name])

    def test_cif_scf_wizard_cancel_or_failure_does_not_enter_phonon_menu(self):
        outcomes = (None, ValueError('SCF wizard failed'), OSError('SCF publish failed'),
                    EOFError('SCF wizard input ended'))
        for outcome in outcomes:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cif = root / 'relax.cif'
                self.write_cif(cif)
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with patch(SCF_WIZARD, return_value=None, side_effect=outcome) as wizard:
                    status, output = self.source_session(cif, root, [], root)
                wizard.assert_called_once()
                self.assertEqual(status, 0 if outcome is None else 1, output)
                self.assertNotIn('选择体系', output)
                self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_cif_scf_wizard_creates_requested_output_directory_before_handoff(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cif = root / 'relax.cif'
                self.write_cif(cif)
                requested = Path('new directory') / 'phonon'
                def generate(source, *, output_dir, input_fn, output):
                    self.assertEqual(output_dir, requested)
                    self.assertTrue(Path(output_dir).is_dir())
                    if cancel:
                        return None
                    generated = Path(output_dir).resolve() / 'new.scf.in'
                    generated.write_text(SCF)
                    return generated
                with patch(SCF_WIZARD, side_effect=generate) as wizard:
                    status, output = self.source_session(cif, requested,
                        [] if cancel else ['3', '1', ''], root)
                wizard.assert_called_once()
                self.assertEqual(status, 0, output)
                self.assertTrue((root / requested).is_dir())
                if cancel:
                    self.assertEqual(list((root / requested).iterdir()), [])
                else:
                    self.assertTrue((root / requested / 'silicon.ph.in').is_file())

    def test_cif_scf_wizard_consumed_eof_still_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cif = root / 'relax.cif'
            self.write_cif(cif)
            def generate(source, *, output_dir, input_fn, output):
                try:
                    input_fn('SCF wizard prompt:')
                except EOFError:
                    return None
                self.fail('The empty input stream should produce EOF')
            with patch(SCF_WIZARD, side_effect=generate) as wizard:
                status, output = self.source_session(cif, root, [], root)
            wizard.assert_called_once()
            self.assertEqual(status, 1, output)
            self.assertNotIn('选择体系', output)
            self.assertEqual([p.name for p in root.iterdir()], [cif.name])

    def test_cif_entry_multiple_scf_candidates_require_selection_and_prefer_matching_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calculation, workspace = root / 'calculation', root / 'workspace'
            calculation.mkdir()
            workspace.mkdir()
            cif = calculation / 'relax.cif'
            self.write_cif(cif)
            preferred = calculation / 'relax.scf.in'
            preferred.write_text(SCF.replace("prefix='silicon'", "prefix='preferred'"))
            other = workspace / 'another.scf.in'
            other.write_text(SCF.replace("prefix='silicon'", "prefix='selected'"))
            status, output = self.source_session(cif, workspace, ['', '0', '3', '2', '3', '1', ''], workspace)
            self.assertEqual(status, 0, output)
            self.assertIn(f'1) {preferred}', output)
            self.assertIn(f'2) {other}', output)
            self.assertEqual(output.count('SCF 编号无效'), 2)
            self.assertTrue((workspace / 'selected.ph.in').exists())
            self.assertFalse((workspace / 'preferred.ph.in').exists())

    def test_cif_entry_reprompts_for_cif_missing_and_non_scf_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cif = root / 'relax.cif'
            self.write_cif(cif)
            invalid = root / 'not-scf.in'
            invalid.write_text('not a Quantum ESPRESSO input')
            (root / 'candidate.scf.in').write_text(SCF)
            scf = root / 'existing SCF.txt'
            scf.write_text(SCF)
            answers = [str(cif), str(root / 'missing.in'), str(invalid), str(scf), '3', '1', '']
            status, output = self.source_session(cif, root, answers, root)
            self.assertEqual(status, 0, output)
            self.assertIn('CIF', output)
            self.assertIn('不存在', output)
            self.assertIn('&CONTROL', output)
            self.assertTrue((root / 'silicon.ph.in').exists())

    def test_frequency_defaults_generate_after_only_system_target_and_enter(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(SCF_WIZARD, side_effect=AssertionError('A direct SCF needs no wizard')) as wizard:
                status, output = self.session(directory, ['3', '1', ''])
            wizard.assert_not_called()
            self.assertEqual(status, 0, output)
            ph = (Path(directory) / 'silicon.ph.in').read_text()
            self.assertIn('1d-12', ph.lower())
            self.assertIn('设置摘要', output)
            self.assertIn('0) 生成', output)
            self.assertNotIn('请输入 epsil', output)
            self.assertTrue((Path(directory) / 'silicon.dynmat.in').exists())

    def test_gamma_ir_and_raman_commands_are_saved_in_bilingual_readme_only(self):
        for target in ('1', '3', '4'):
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix='phonon readme ') as directory:
                root = Path(directory)
                (root / 'Si.upf').write_text('<UPF><PP_HEADER pseudo_type="NC" functional="LDA"/></UPF>')
                text = SCF.replace("outdir='./tmp'", "outdir='./tmp', pseudo_dir='.'")
                text = text.replace('ecutwfc=40', "ecutwfc=40, input_dft='LDA'")
                status, output = self.session(directory, ['3', target, ''], text)
                self.assertEqual(status, 0, output)
                readme = root / 'silicon.README.txt'
                self.assertTrue(readme.is_file(), output)
                instructions = readme.read_text()
                self.assertIn('运行顺序 / Run order', instructions)
                commands = [line.strip() for line in instructions.splitlines()
                            if line.strip().startswith(('pw.x ', 'mpirun ', 'dynmat.x '))]
                self.assertEqual(commands, ['pw.x -in silicon.scf.in > scf.out',
                    'mpirun -np 32 ph.x -in silicon.ph.in > ph.out',
                    'dynmat.x -in silicon.dynmat.in > dynmat.out'])
                for executable in ('pw.x', 'ph.x', 'dynmat.x'):
                    self.assertNotIn(f'{executable} -in', output)
                self.assertNotIn('cd ', instructions)
                self.assertNotIn('仅生成', instructions)
                self.assertNotIn('generates input files only', instructions)
                self.assertIn(str(readme), output)
                self.assertEqual(output.count(str(readme)), 1)
                self.assertNotIn('手动运行示例', output)
                self.assertNotIn('qbox.postprocess.phonon_plot', output)

    def test_existing_readme_alone_requires_confirmation_and_cancellation_writes_no_bundle(self):
        for thermo in (False, True):
            with self.subTest(thermo=thermo), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                readme = root / 'silicon.README.txt'
                readme.write_text('Keep my original instructions')
                if thermo:
                    mold = root / 'silicon.molden'
                    mold.write_text('[FREQ]\n123.5\n[FR-COORD]\n')
                    answers = ['2', '2', str(mold), '', '', '3', '5']
                else:
                    answers = ['3', '1', '', '', '2', '5', '5']
                status, output = self.session(directory, answers)
                self.assertEqual(status, 0, output)
                self.assertIn('覆盖', output)
                self.assertEqual(readme.read_text(), 'Keep my original instructions')
                for suffix in ('ph.in', 'dynmat.in', 'shm'):
                    self.assertFalse((root / ('silicon.' + suffix)).exists())
                if not thermo:
                    status, output = self.session(directory, ['3', '1', '', '1'])
                    self.assertEqual(status, 0, output)
                    self.assertIn('运行顺序 / Run order', readme.read_text())
                    self.assertTrue((root / 'silicon.ph.in').exists())

    def test_readme_publication_failure_rolls_back_the_entire_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme = root / 'silicon.README.txt'
            readme.write_text('Original README')
            real_replace = os.replace
            def replace(source, target):
                if Path(target) == readme:
                    raise OSError('README publication failed')
                return real_replace(source, target)
            with patch('qbox.io.phonon_inputs.os.replace', side_effect=replace):
                status, output = self.session(directory, ['3', '1', '', '1', '2', '5', '5'])
            self.assertEqual(status, 0, output)
            self.assertIn('README publication failed', output)
            self.assertEqual(readme.read_text(), 'Original README')
            self.assertFalse((root / 'silicon.ph.in').exists())
            self.assertFalse((root / 'silicon.dynmat.in').exists())

    def test_invalid_threshold_preserves_old_value_until_valid_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, ['3', '1', '1', '2',
                                                       'zero', '0', '2d-14', '0', ''])
            self.assertEqual(status, 0, output)
            self.assertIn('2d-14', (Path(directory) / 'silicon.ph.in').read_text().lower())
            self.assertIn('保留', output)

    def test_missing_nat_returns_clean_diagnostic_without_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, [], SCF.replace('nat=2, ', ''))
            self.assertNotEqual(status, 0)
            self.assertIn('nat', output.lower())
            self.assertNotIn('i<=', output)
            self.assertFalse((Path(directory) / 'silicon.ph.in').exists())

    def test_eof_at_each_level_returns_nonzero_without_outputs(self):
        for answers in ([], ['3'], ['3', '1'], ['3', '1', '1'],
                        ['3', '1', '1', '2']):
            with self.subTest(answers=answers), tempfile.TemporaryDirectory() as directory:
                status, output = self.session(directory, answers)
                self.assertNotEqual(status, 0, output)
                self.assertFalse((Path(directory) / 'silicon.ph.in').exists())

    def test_back_from_target_and_summary_does_not_generate(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, ['3', '5', '2', '1', '2', '3', '5'])
            self.assertEqual(status, 0, output)
            self.assertFalse((Path(directory) / 'silicon.ph.in').exists())

    def test_main_menu_back_and_wizard_cancel_have_distinct_return_status(self):
        for from_main_menu in (False, True):
            for action in ('back', 'wizard_cancel'):
                with self.subTest(from_main_menu=from_main_menu, action=action), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / ('source.scf.in' if action == 'back' else 'relax.cif')
                    source.write_text(SCF if action == 'back' else CIF.format(species='Si'))
                    with patch(SCF_WIZARD, return_value=None):
                        status, output = self.source_session(source, root,
                            ['5'] if action == 'back' else [], root, from_main_menu=from_main_menu)
                    self.assertEqual(status, 10 if from_main_menu else 0, output)
                    self.assertFalse((root / 'silicon.ph.in').exists())

    def test_adsorbate_atom_range_rejects_injection_and_out_of_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'injected'
            status, output = self.session(directory, ['1', '1', f'1;touch {marker}',
                                                       '1-3', '1-2', ''])
            self.assertEqual(status, 0, output)
            self.assertFalse(marker.exists())
            ph = (Path(directory) / 'silicon.ph.in').read_text()
            self.assertRegex(ph, r'nat_todo\s*=\s*2')
            self.assertIn('1 2', ph)

    def test_adsorbate_atom_selection_can_return_without_generating(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, ['1', '1', 'b', '3', '5'])
            self.assertEqual(status, 0, output)
            self.assertFalse((Path(directory) / 'silicon.ph.in').exists())

    def test_adsorbate_empty_atom_selection_stays_until_an_atom_is_chosen(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, ['1', '1', '', '2', ''])
            self.assertEqual(status, 0, output)
            self.assertIn('至少选择一个原子', output)
            ph = (Path(directory) / 'silicon.ph.in').read_text()
            self.assertRegex(ph, r'nat_todo\s*=\s*1')
            self.assertTrue(ph.rstrip().endswith('2'))

    def test_no_source_prompts_once_and_accepts_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='phonon source ') as directory:
            path = Path(directory) / 'silicon.scf.in'
            status, output = self.session(directory, [str(path), '3', '1', ''], source=False)
            self.assertEqual(status, 0, output)
            self.assertTrue((Path(directory) / 'silicon.ph.in').exists())

    def test_gas_thermo_converts_gamma_modes_to_shermo_only(self):
        with tempfile.TemporaryDirectory() as directory:
            mold = Path(directory) / 'dynmat.mold'
            mold.write_text('[Molden Format]\n[FREQ]\n-1.0\n0.0\n123.5\n[FR-COORD]\n')
            status, output = self.session(directory, ['2', '2', str(mold), ''], from_main_menu=True)
            self.assertEqual(status, 0, output)
            shm = (Path(directory) / 'silicon.shm').read_text()
            self.assertIn('*wavenum\n123.5\n', shm)
            self.assertNotIn('-1.0', shm)
            self.assertFalse((Path(directory) / 'silicon.ph.in').exists())
            self.assertIn('Shermo', output)
            instructions = (Path(directory) / 'silicon.README.txt').read_text()
            self.assertIn('Shermo silicon.shm -T 298.15 -P 1 -imode 0', instructions.splitlines())
            self.assertIn('Hartree', instructions)
            self.assertIn('电子能量', instructions)
            self.assertIn('electronic energy', instructions)
            self.assertIn('silicon.shm 由 Gamma 振动模式生成', instructions)
            self.assertIn('silicon.shm is generated from Gamma vibrational modes', instructions)
            self.assertEqual(output.count(str(Path(directory) / 'silicon.README.txt')), 1)
            self.assertNotIn('Shermo silicon.shm', output)
            self.assertNotIn('手动计算', output)

    def test_adsorbate_thermo_uses_mode_column_and_selected_atom_coordinates(self):
        for filename in ('ph.out', 'silicon.ph.out'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                phonon = Path(directory) / filename
                phonon.write_text('''Compute atoms 2
  1  4 To be done
  2  5 To be done
  3  6 To be done
freq ( 4) = 1.0 [THz] = 101.0 [cm-1]
freq ( 5) = 2.0 [THz] = 202.0 [cm-1]
freq ( 6) = 3.0 [THz] = 303.0 [cm-1]
''')
                if filename == 'ph.out':
                    (Path(directory) / 'silicon.ph.out').write_text('obsolete output must not be selected')
                status, output = self.session(directory, ['1', '2', '', ''])
                self.assertEqual(status, 0, output)
                shm = (Path(directory) / 'silicon.shm').read_text()
                self.assertIn('*wavenum\n101.0\n202.0\n303.0\n', shm)
                self.assertIn('1.350000000    1.350000000    1.350000000', shm)
                self.assertEqual(shm.count('Si\t'), 1)
                instructions = (Path(directory) / 'silicon.README.txt').read_text()
                self.assertIn('Shermo silicon.shm -T 298.15 -P 1 -imode 1', instructions.splitlines())
                self.assertNotIn('Shermo silicon.shm', output)

    def test_legacy_adapter_maps_only_explicit_return_to_main_menu(self):
        # The stand-in observes the CLI boundary; no parser or generator is mocked.
        command = '''source "$1"
qbox_python() { printf '<%s>\\n' "$@"; return "$STUB_STATUS"; }
fname1='source path.scf.in'
QE_RETURN_TO_MAIN=0
phin
status=$?
printf 'main=%s\\n' "$QE_RETURN_TO_MAIN"
exit "$status"
'''
        for child_status, direct, expected_status, expected_main in (
                (0, '', 0, 0), (10, '', 0, 1), (10, 'phonon-input', 0, 0), (3, '', 3, 0)):
            with self.subTest(child_status=child_status, direct=direct):
                result = subprocess.run(['bash', '-c', command, '_', str(ROOT / 'qbox')],
                    env={**os.environ, 'QBOX_TEST_MODE': '1', 'STUB_STATUS': str(child_status),
                         'QE_DIRECT_ACTION': direct}, text=True, capture_output=True)
                self.assertEqual(result.returncode, expected_status, result.stderr)
                self.assertIn('<--source>\n<source path.scf.in>', result.stdout)
                self.assertIn('<--from-main-menu>', result.stdout)
                self.assertIn(f'main={expected_main}', result.stdout)

    def test_existing_bundle_requires_one_explicit_overwrite_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'silicon.ph.in'
            path.write_text('old input')
            status, output = self.session(directory, ['3', '1', '', '', '2', '5', '5'])
            self.assertEqual(status, 0, output)
            self.assertEqual(path.read_text(), 'old input')
            self.assertIn('覆盖', output)
            status, output = self.session(directory, ['3', '1', '', '1'])
            self.assertEqual(status, 0, output)
            self.assertIn('&INPUTPH', path.read_text())
            self.assertTrue((Path(directory) / 'silicon.dynmat.in').exists())

    @unittest.skipUnless(HAS_PATH_DEPS, 'Automatic paths require numpy and seekpath')
    def test_dispersion_generates_path_and_exposes_only_relevant_advanced_options(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, ['4', '2', '1', '1', '0 4 4',
                                                       '3 4 5', '6', '4', '0', ''])
            self.assertEqual(status, 0, output)
            path = Path(directory)
            metadata = json.loads((path / 'silicon.path.json').read_text())
            self.assertGreater(len(metadata['qpoints']), 1)
            self.assertTrue(all(s['end'] - s['start'] == 3 for s in metadata['segments']))
            ph = (path / 'silicon.ph.in').read_text()
            self.assertRegex(ph, r'nq1\s*=\s*3')
            self.assertRegex(ph, r'nq2\s*=\s*4')
            self.assertRegex(ph, r'nq3\s*=\s*5')
            self.assertNotIn('8) 介电', output)
            self.assertNotIn('eth_rps', output)
            self.assertNotIn('qbox.postprocess.phonon_plot', output)
            instructions = (path / 'silicon.README.txt').read_text()
            commands = [line.strip() for line in instructions.splitlines()
                        if line.strip().startswith(('pw.x ', 'mpirun ', 'q2r.x ', 'matdyn.x '))]
            self.assertEqual(commands, ['pw.x -in silicon.scf.in > scf.out',
                'mpirun -np 32 ph.x -in silicon.ph.in > ph.out',
                'q2r.x -in silicon.q2r.in > q2r.out',
                'matdyn.x -in silicon.matdyn.in > matdyn.out'])
            for executable in ('pw.x', 'ph.x', 'q2r.x', 'matdyn.x'):
                self.assertNotIn(f'{executable} -in', output)
            self.assertNotIn('cd ', instructions)
            self.assertNotIn('qbox.postprocess.phonon_plot', instructions)

    def test_dimension_and_axis_are_edited_together_before_geometry_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            slab = SCF.replace('0 2.7 2.7\n2.7 0 2.7\n2.7 2.7 0', '20 0 0\n0 3 0\n0 0 3')
            slab = slab.replace('Si 0.25 0.25 0.25', 'Si 0.05 0.25 0.25')
            status, output = self.session(directory, ['3', '1', '1', '4', '2', '1', '0', ''], slab)
            self.assertEqual(status, 0, output)
            self.assertRegex(output, r'周期维度\s+2D')
            from qbox.io.phonon_inputs import load_scf, PhononSettings, resolve_settings
            scf = load_scf(Path(directory) / 'silicon.scf.in')
            answers = iter(['4', '2', '1', '0'])
            edited = self.menu().edit_advanced(scf, resolve_settings(scf, PhononSettings()),
                {'cif_file': None, 'points_per_segment': 20}, lambda _: next(answers), lambda _: None)
            self.assertEqual(edited.periodic_axis, 1)
            self.assertEqual(edited.q_grid, (1, 4, 4))

    def test_polar_gamma_zero_direction_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, ['4', '1', '1', '11', '0 0 0', '0', ''])
            self.assertEqual(status, 0, output)
            dynmat = (Path(directory) / 'silicon.dynmat.in').read_text()
            self.assertRegex(dynmat, r'q\(1\)\s*=\s*0')

    def test_dimension_change_recomputes_explicit_2d_loto_default(self):
        from qbox.io.phonon_inputs import load_scf, PhononSettings, resolve_settings
        with tempfile.TemporaryDirectory() as directory:
            slab = SCF.replace('0 2.7 2.7\n2.7 0 2.7\n2.7 2.7 0', '3 0 0\n0 3 0\n0 0 20')
            slab = slab.replace('occupations=', "assume_isolated='2D', occupations=")
            path = Path(directory) / 'slab.scf.in'
            path.write_text(slab)
            scf = load_scf(path)
            settings = resolve_settings(scf, PhononSettings(system='polar'))
            self.assertTrue(settings.loto_2d)
            answers = iter(['4', '3', '4', '2', '', '0'])
            edited = self.menu().edit_advanced(scf, settings,
                {'cif_file': None, 'points_per_segment': 20}, lambda _: next(answers), lambda _: None)
            self.assertTrue(edited.loto_2d)

    def test_polar_frequency_disabling_dielectric_response_updates_its_default_born_response(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output = self.session(directory, ['4', '1', '1', '8', 'no', '0', ''])
            self.assertEqual(status, 0, output)
            ph = (Path(directory) / 'silicon.ph.in').read_text()
            self.assertRegex(ph, r'epsil\s*=\s*\.false\.')

    def test_thermo_finds_new_molden_filename_and_safe_source_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'qe_name.molden').write_text('[FREQ]\n123.5\n[FR-COORD]\n')
            status, output = self.session(directory, ['2', '2', '', ''], SCF.replace("prefix='silicon'", "prefix='qe/name'"))
            self.assertEqual(status, 0, output)
            self.assertTrue((Path(directory) / 'qe_name.shm').exists())

if __name__ == '__main__':
    unittest.main()
