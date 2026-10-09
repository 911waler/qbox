"""Wannier input navigation and command boundaries, without scientific runtimes."""
import contextlib
import importlib.util
import io
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
from qbox.io.wannier_workflow import _win_parts


class WannierMenuTests(unittest.TestCase):
    def menu(self):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.wannier_menu'),
                             'the six-direction input menu must be implemented')
        from qbox.io import wannier_menu
        return wannier_menu

    def output_record(self, path='/calculation/scf.out', fermi=4.2, kind='scf'):
        return {'path': path, 'kind': kind, 'fermi_energy': fermi, 'nbnd': 12,
                'eigenvalue_min': -8., 'eigenvalue_max': 15.,
                'homo': 3., 'lumo': 5., 'notes': [], 'sha256': '0' * 64}

    def output_ui(self):
        menu = self.menu()
        self.assertTrue(callable(getattr(menu, '_scan_outputs', None)),
                        'matched QE outputs need an automatic selection flow')
        from qbox.io import wannier_output_defaults
        return menu, wannier_output_defaults

    def test_unique_output_is_imported_once_after_direction_without_extra_prompt(self):
        menu, api = self.output_ui()
        config = {'source': '/calculation/scf.in', 'run_root': '/calculation',
                  'mode': 'new', 'parameters': {}}
        record = self.output_record()
        answers, messages = iter(['1', 'b', '2', 'q']), []
        with patch.object(api, 'candidates', return_value=[record]) as scan:
            self.assertEqual(menu.run_interactive(config, lambda _: next(answers), messages.append), 0)
        self.assertEqual(config['parameters']['fermi_energy'], 4.2)
        self.assertEqual(config['source_output'], record['path'])
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(sum(record['path'] in line for line in messages), 1)

    def test_multiple_outputs_require_selection_and_do_not_default_to_first(self):
        menu, api = self.output_ui()
        records = [self.output_record(), self.output_record('/calculation/nscf.out', 4.5, 'nscf')]
        for answer, expected in [('2', 4.5), ('', None), ('0', None)]:
            with self.subTest(answer=answer):
                config = {'source': '/calculation/scf.in', 'parameters': {}}
                messages = []
                with patch.object(api, 'candidates', return_value=records) as scan:
                    menu._scan_outputs(config, lambda _: answer, messages.append)
                    menu._scan_outputs(config, lambda _: self.fail('same source must not prompt twice'), messages.append)
                self.assertEqual(config['parameters'].get('fermi_energy'), expected)
                self.assertEqual(scan.call_count, 1)
                self.assertIn('NSCF', '\n'.join(messages))
                self.assertIn('4.5', '\n'.join(messages))

    def test_output_without_fermi_retains_band_edges_as_reference_only(self):
        menu, api = self.output_ui()
        config, messages = {'source': '/calculation/scf.in', 'parameters': {}}, []
        with patch.object(api, 'candidates', return_value=[self.output_record(fermi=None)]):
            menu._scan_outputs(config, lambda _: self.fail('unique output needs no selection'), messages.append)
        self.assertNotIn('fermi_energy', config['parameters'])
        self.assertEqual(config['qe_output']['homo'], 3.)
        self.assertEqual(config['qe_output']['lumo'], 5.)

    def test_window_menu_shows_imported_energy_reference_with_default_absolute_windows(self):
        menu, api = self.output_ui()
        config = {'mode': 'new', 'parameters': {}, 'windows': {}}
        api.apply_output(config, self.output_record('/run/iron.nscf.out', kind='nscf'))
        messages = []
        menu._windows(config, lambda _: '0', messages.append)
        shown = '\n'.join(messages)
        for fragment in ('iron.nscf.out', 'NSCF', 'EF', '4.2', 'HOMO', '3.0', 'LUMO', '5.0', 'QE', '本征值', '-8.0', '15.0'):
            self.assertIn(fragment, shown)
        self.assertEqual(config['windows'].get('reference', 'absolute'), 'absolute')
        self.assertFalse(config.get('windows_manual'))

    def test_window_menu_labels_homo_without_substituting_it_for_fermi(self):
        menu, api = self.output_ui()
        config = {'mode': 'new', 'parameters': {}, 'windows': {}}
        api.apply_output(config, self.output_record(fermi=None))
        messages = []
        menu._windows(config, lambda _: '0', messages.append)
        self.assertIn('HOMO', '\n'.join(messages))
        self.assertIn('未报告', '\n'.join(messages))
        self.assertNotIn('fermi_energy', config['parameters'])
        self.assertNotIn('fermi_energy', config['windows'])

    def test_window_menu_distinguishes_window_reference_from_qe_report(self):
        menu, api = self.output_ui()
        config = {'mode': 'new', 'parameters': {'fermi_energy': 7.5},
                  'windows': {'reference': 'fermi', 'fermi_energy': 6.0}}
        api.apply_output(config, self.output_record())
        messages = []
        menu._windows(config, lambda _: '0', messages.append)
        shown = '\n'.join(messages)
        self.assertIn('4.2', shown)
        self.assertEqual(config['parameters']['fermi_energy'], 7.5)
        self.assertTrue(any('能窗' in line and '6.0' in line for line in messages))

    def test_startup_progress_distinguishes_completion_from_saved_data_and_is_not_repeated(self):
        menu = self.menu()
        config = {'mode': 'new', 'source': '/run/scf.in', 'source_output_mode': 'off',
                  'qe_progress': {
                      'scf': {'input': '/run/scf.in', 'output': '/run/scf.out', 'completed': True,
                              'data_present': True, 'run_root': '/run'},
                      'nscf': {'input': '/run/nscf.in', 'output': '/run/nscf.out', 'completed': True,
                               'data_present': False, 'run_root': '/run', 'reusable': False}}}
        answers, messages = iter(['1', 'b', '2', 'q']), []
        menu.run_interactive(config, lambda _: next(answers), messages.append)
        summaries = [line for line in messages if '保存数据' in line]
        self.assertEqual(len(summaries), 1)
        self.assertIn('SCF', summaries[0])
        self.assertIn('NSCF', summaries[0])
        self.assertIn('已完成', summaries[0])
        self.assertIn('缺少', summaries[0])

    def test_protection_includes_all_discovered_qe_stage_inputs(self):
        config = {'mode': 'new', 'source': '/run/scf.in',
                  'qe_progress': {'scf': {'input': '/run/scf.in'},
                                  'nscf': {'input': '/run/already.nscf.in'}}}
        self.assertIn(Path('/run/already.nscf.in'), self.menu()._protected(config))

    def test_startup_progress_reports_verified_output_when_scf_input_is_absent(self):
        config = {'mode': 'new', 'qe_progress': {
            'scf': {'input': None, 'output': '/run/scf.out', 'completed': True, 'data_present': True}}}
        messages = []
        self.menu()._show_qe_progress(config, messages.append)
        shown = '\n'.join(messages)
        self.assertIn('scf.out', shown)
        self.assertIn('已完成', shown)
        self.assertIn('保存数据存在', shown)

    def test_resume_rechecks_completed_nscf_preserving_saved_dimensions_and_output_mode(self):
        from qbox.io.wannier_workflow import initial_config
        from test_wannier_qe_reuse import SCF, NSCF, UPF, nscf_output
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            root = Path(directory)
            (root / 'scf.in').write_text(SCF)
            (root / 'nscf.in').write_text(NSCF)
            (root / 'pseudo').mkdir()
            (root / 'pseudo/Si.UPF').write_text(UPF)
            config = initial_config(root / 'scf.in')
            config.update(tasks=['bands'], grid=[8, 8, 8], nbnd=40)
            menu._show_qe_progress(config, lambda _: None)
            (root / 'nscf.out').write_text(nscf_output())
            for mode in ('auto', 'manual', 'off'):
                with self.subTest(mode=mode):
                    config['source_output_mode'] = mode
                    config['source_output'] = str(root / 'nscf.out')
                    config['_output_scan_key'] = menu._output_context(config)
                    messages = []
                    menu.run_interactive(config, lambda _: 'q', messages.append, resume=True)
                    self.assertTrue(config['qe_progress']['nscf']['completed'])
                    self.assertEqual(config['source_nscf'], str(root / 'nscf.in'))
                    self.assertEqual((config['grid'], config['nbnd']), ([8, 8, 8], 40))
                    self.assertEqual(config['source_output_mode'], mode)
                    if mode == 'auto':
                        self.assertEqual(config['qe_output']['fermi_energy'], 2.5)
                    else:
                        self.assertNotIn('_output_scan_key', config)
                    self.assertEqual(sum('已有 QE 计算' in line for line in messages), 1)

    def test_changed_run_directory_rechecks_nscf_and_preserves_manual_dimensions(self):
        from qbox.io.wannier_workflow import initial_config
        from test_wannier_qe_reuse import SCF, NSCF, POINTS
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, inputs, work = (root / name for name in ('old', 'new', 'inputs', 'work'))
            for path in (old, new, inputs, work):
                path.mkdir()
            source = inputs / 'scf.in'
            source.write_text(SCF)
            (old / 'nscf.in').write_text(NSCF)
            (new / 'nscf.in').write_text(NSCF.replace(POINTS, 'K_POINTS crystal\n1\n0 0 0 1\n').replace('nbnd=4', 'nbnd=6'))
            for manual in (False, True):
                with self.subTest(manual=manual), contextlib.chdir(old):
                    config = initial_config(source)
                    config['source_output_mode'] = 'off'
                    if manual:
                        config.update(grid=[4, 4, 4], nbnd=20)
                    answers = iter(['', '', str(new)])
                    with contextlib.chdir(work):
                        menu._sources(config, lambda _: next(answers), lambda _: None)
                    self.assertEqual(config['qe_progress']['nscf']['input'], str(new / 'nscf.in'))
                    self.assertEqual(config['source_nscf'], str(new / 'nscf.in'))
                    self.assertEqual(config['grid'], [4, 4, 4] if manual else [1, 1, 1])
                    self.assertEqual(config['nbnd'], 20 if manual else 6)

    def test_output_off_survives_navigation_and_explicit_auto_enables_rescan(self):
        menu, api = self.output_ui()
        config = {'source': '/calculation/scf.in', 'parameters': {}}
        api.apply_output(config, self.output_record())
        self.assertEqual(menu._edit_output_source(config, lambda _: '-', lambda _: None), 'off')
        self.assertEqual(config['source_output_mode'], 'off')
        self.assertNotIn('fermi_energy', config['parameters'])
        with patch.object(api, 'candidates', return_value=[self.output_record()]) as scan:
            menu._scan_outputs(config, lambda _: self.fail('disabled scan must not prompt'), lambda _: None)
            scan.assert_not_called()
            self.assertEqual(menu._edit_output_source(config, lambda _: 'a', lambda _: None), 'scan')
            menu._scan_outputs(config, lambda _: self.fail('unique output needs no selection'), lambda _: None, force=True)
        self.assertEqual(config['source_output_mode'], 'auto')
        self.assertEqual(config['parameters']['fermi_energy'], 4.2)

    def test_manual_output_path_is_saved_for_prepare_validation(self):
        menu, api = self.output_ui()
        config = {'source': '/calculation/scf.in', 'parameters': {}}
        api.apply_output(config, self.output_record())
        result = menu._edit_output_source(config, lambda _: 'new output.out', lambda _: None)
        self.assertEqual(result, 'manual')
        self.assertEqual(config['source_output'], 'new output.out')
        self.assertEqual(config['source_output_mode'], 'manual')
        self.assertNotIn('fermi_energy', config['parameters'])
        with patch.object(api, 'candidates') as scan:
            menu._scan_outputs(config, lambda _: self.fail('manual path must be retained'), lambda _: None)
            scan.assert_not_called()

    def test_manual_fermi_edit_or_clear_survives_later_output_import(self):
        menu, api = self.output_ui()
        for entered, expected in [('7.5', 7.5), ('4.2', 4.2), ('-', None)]:
            with self.subTest(entered=entered):
                config = {'source': '/calculation/scf.in', 'tasks': ['fermi_surface'], 'parameters': {}}
                api.apply_output(config, self.output_record())
                answers = iter(['1', entered, '0'])
                menu._parameters(config, lambda _: next(answers), lambda _: None)
                self.assertIn('fermi_energy', config.get('output_manual_fields', []))
                api.apply_output(config, self.output_record('/calculation/later.out', 8.))
                self.assertEqual(config['parameters'].get('fermi_energy'), expected)

    def test_unchanged_fermi_keeps_output_provenance_and_menu_displays_file(self):
        menu, api = self.output_ui()
        config = {'source': '/calculation/scf.in', 'tasks': ['fermi_surface'], 'parameters': {}}
        record = self.output_record()
        api.apply_output(config, record)
        answers, messages = iter(['1', '', '0']), []
        menu._parameters(config, lambda _: next(answers), messages.append)
        self.assertNotIn('fermi_energy', config.get('output_manual_fields', []))
        self.assertIn(record['path'], '\n'.join(messages))
        self.assertEqual(config['output_parameter_values']['fermi_energy'], 4.2)

    def test_changed_run_root_replaces_only_automatic_output_values(self):
        menu, api = self.output_ui()
        for manual, expected in [(False, 5.), (True, 7.)]:
            with self.subTest(manual=manual):
                config = {'source': '/calculation/scf.in', 'run_root': '/old',
                          'mode': 'new', 'tasks': [], 'parameters': {}}
                api.apply_output(config, self.output_record())
                if manual:
                    config['parameters']['fermi_energy'] = 7.
                    api.mark_manual(config, 'fermi_energy')
                answers = iter(['', '', '/new'])
                with patch('qbox.io.wannier_workflow.initialize_basis_defaults'), \
                     patch.object(api, 'candidates', return_value=[self.output_record('/new/scf.out', 5.)]):
                    menu._sources(config, lambda _: next(answers), lambda _: None)
                self.assertEqual(config['source_output'], '/new/scf.out')
                self.assertEqual(config['parameters']['fermi_energy'], expected)

    def test_real_output_discovery_and_existing_reference_preserve_model_fermi(self):
        menu = self.menu()
        from test_wannier_outputs import SCF, UPF, output
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'scf.in'
            source.write_text(SCF)
            (root / 'pseudo').mkdir()
            (root / 'pseudo/Si.UPF').write_text(UPF)
            result = root / 'scf.out'
            result.write_text(output())
            (root / 'seed.win').write_text('''num_wann = 2
num_bands = 4
mp_grid = 1 1 1
begin kpoints
0 0 0
end kpoints
begin unit_cell_cart
bohr
6 0 0
0 6 0
0 0 6
end unit_cell_cart
begin atoms_frac
Si 0 0 0
Si .25 .25 .25
end atoms_frac
''')
            config = {'source': str(source), 'run_root': str(root), 'parameters': {}}
            with contextlib.chdir(root):
                menu._scan_outputs(config, lambda _: self.fail('one verified output needs no choice'), lambda _: None)
                self.assertEqual(config['parameters']['fermi_energy'], 2.5)
                existing = {'source': 'seed.win', 'mode': 'existing', 'run_root': str(root),
                            'tasks': ['ahc'], 'parameters': {'fermi_energy': 4.25}}
                answers = iter(['', '', '', str(source)])
                menu._sources(existing, lambda _: next(answers), lambda _: None)
            self.assertEqual(existing['reference_source'], str(source))
            self.assertEqual(existing['source_output'], str(result))
            self.assertEqual(existing['parameters']['fermi_energy'], 4.25)

    def test_cancel_after_run_root_change_drops_previous_automatic_output(self):
        menu, api = self.output_ui()
        config = {'source': 'seed.win', 'mode': 'existing', 'run_root': '/old',
                  'tasks': ['ahc'], 'parameters': {}}
        api.apply_output(config, self.output_record())
        answers = iter(['', '', '/new', 'b'])
        menu._sources(config, lambda _: next(answers), lambda _: None)
        self.assertNotIn('source_output', config)
        self.assertNotIn('fermi_energy', config['parameters'])

    def test_source_change_discards_previous_material_fermi_choices(self):
        menu, api = self.output_ui()
        from test_wannier_outputs import SCF
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'new.scf.in'
            source.write_text(SCF)
            for value in (7.5, None):
                with self.subTest(value=value):
                    config = {'source': '/old/scf.in', 'parameters': {}, 'tasks': ['ahc']}
                    if value is not None:
                        config['parameters']['fermi_energy'] = value
                    api.mark_manual(config, 'fermi_energy')
                    answers = iter([str(source), '', ''])
                    with patch.object(api, 'candidates', return_value=[self.output_record()]):
                        menu._sources(config, lambda _: next(answers), lambda _: None)
                    self.assertEqual(config['parameters'].get('fermi_energy'), 4.2)
                    self.assertNotIn('fermi_energy', config.get('output_manual_fields', []))

    def test_explicit_window_fermi_edit_releases_automatic_provenance(self):
        menu = self.menu()
        for entered, retained in [('4.2', False), ('', True), ('b', True)]:
            with self.subTest(entered=entered):
                config = {'mode': 'new', 'windows': {'reference': 'fermi', 'fermi_energy': 4.2},
                          'output_window_fermi_value': 4.2}
                answers = iter(['4', '', entered, '0'])
                menu._windows(config, lambda _: next(answers), lambda _: None)
                self.assertEqual('output_window_fermi_value' in config, retained)
                self.assertEqual('windows.fermi_energy' in config.get('output_manual_fields', []), not retained)

    def test_missing_fermi_is_not_satisfied_by_band_edges_or_manual_clear(self):
        menu, api = self.output_ui()
        for record, clear in [(self.output_record(fermi=None), False), (self.output_record(), True)]:
            config = {'source': 'seed.win', 'mode': 'existing', 'tasks': ['optical'], 'parameters': {}}
            api.apply_output(config, record)
            if clear:
                config['parameters'].pop('fermi_energy')
                api.mark_manual(config, 'fermi_energy')
            missing = '\n'.join(menu._missing_settings(config))
            self.assertIn('费米能', missing)
            self.assertNotIn('kubo_freq_max', missing)
            self.assertNotIn('kubo_eigval_max', missing)

    def test_nonzero_photon_lower_bound_requires_explicit_upper_bound(self):
        menu = self.menu()
        config = {'source': 'seed.win', 'mode': 'existing', 'tasks': ['optical'],
                  'parameters': {'fermi_energy': 4.2, 'kubo_freq_min': 1.}}
        field = menu._task_fields(config)['kubo_freq_max']
        self.assertTrue(field.get('required'))
        shown = menu._task_setting(config, 'kubo_freq_max', field)
        self.assertIn('待填写', shown)
        self.assertNotIn('可直接使用', shown)
        self.assertIn('光子能量上限', '\n'.join(menu._missing_settings(config)))
        config['parameters']['kubo_freq_max'] = 3.
        self.assertIn('3', menu._task_setting(config, 'kubo_freq_max', field))
        self.assertNotIn('光子能量上限', '\n'.join(menu._missing_settings(config)))
        config['parameters'].pop('kubo_freq_max')
        config['parameters']['kubo_freq_min'] = 0.
        field = menu._task_fields(config)['kubo_freq_max']
        self.assertFalse(field.get('required'))
        self.assertIn('默认', menu._task_setting(config, 'kubo_freq_max', field))
        config.update(tasks=['shc'], spin_mode='spinor')
        config['parameters']['kubo_freq_min'] = 1.
        self.assertNotIn('kubo_freq_max', menu._task_fields(config))

    def test_shift_current_menu_distinguishes_deferred_response_limits_from_defaults(self):
        menu = self.menu()
        config = {'mode': 'new', 'tasks': ['shift_current'], 'parameters': {}}
        fields = menu._task_fields(config)
        for key in ('kubo_freq_max', 'kubo_eigval_max'):
            with self.subTest(key=key):
                shown = menu._task_setting(config, key, fields[key])
                self.assertIn('待补全', shown)
                self.assertIn('postw90', shown)
                self.assertNotIn('可直接使用', shown)
        config.update(mode='existing')
        self.assertIn('光子能量上限', '\n'.join(menu._missing_settings(config)))
        self.assertIn('初态和末态', '\n'.join(menu._missing_settings(config)))

    def response_window_config(self):
        return {'mode': 'new', 'tasks': ['shift_current'],
                'parameters': {'fermi_energy': 4.2},
                'windows': {'reference': 'absolute', 'dis_win_min': -5., 'dis_win_max': 16.,
                            'dis_froz_min': -.8, 'dis_froz_max': 14.2}}

    def test_parameter_menu_shows_photon_and_absolute_eigenvalue_initial_values(self):
        menu = self.menu()
        for reference in ('absolute', 'fermi'):
            with self.subTest(reference=reference):
                config, messages = self.response_window_config(), []
                if reference == 'fermi':
                    for key in ('dis_win_min', 'dis_win_max', 'dis_froz_min', 'dis_froz_max'):
                        config['windows'][key] -= 4.2
                    config['windows'].update(reference='fermi', fermi_energy=4.2)
                menu._parameters(config, lambda _: '0', messages.append)
                for key, expected in (('kubo_freq_max', 10.), ('kubo_eigval_max', 14.2)):
                    self.assertAlmostEqual(config['parameters'][key], expected)
                    shown = next(line for line in messages if f'({key})' in line)
                    self.assertIn(f'{expected} eV [初值]', shown)
                    if key == 'kubo_eigval_max':
                        self.assertIn('QE 零点', shown)
                    self.assertAlmostEqual(config['response_parameter_defaults'][key]['value'], expected)

    def test_eigenvalue_manual_value_same_value_and_clear_survive_window_change(self):
        menu = self.menu()
        for entered, expected in [('-2', -2.), ('14.2', 14.2), ('-', None)]:
            with self.subTest(entered=entered):
                config = self.response_window_config()
                key = 'kubo_eigval_max'
                selection = str(list(menu._task_fields(config)).index(key) + 1)
                answers = iter([selection, entered, '0'])
                menu._parameters(config, lambda _: next(answers), lambda _: None)
                answers = iter(['3', '-0.8', '13.2', '0'])
                menu._windows(config, lambda _: next(answers), lambda _: None)
                self.assertEqual(config['parameters'].get(key), expected)
                self.assertIn(key, config.get('output_manual_fields', []))
                self.assertNotIn(key, config.get('response_parameter_defaults', {}))
                self.assertAlmostEqual(config['parameters']['kubo_freq_max'], 9.)

    def test_eigenvalue_enter_and_cancel_keep_automatic_refresh_after_window_edit(self):
        menu = self.menu()
        for entered in ('', 'b'):
            with self.subTest(entered=entered):
                config = self.response_window_config()
                config['parameters']['kubo_freq_max'] = 6.
                key = 'kubo_eigval_max'
                selection = str(list(menu._task_fields(config)).index(key) + 1)
                answers = iter([selection, entered, '0'])
                menu._parameters(config, lambda _: next(answers), lambda _: None)
                answers = iter(['3', '-0.8', '13.2', '0'])
                menu._windows(config, lambda _: next(answers), lambda _: None)
                self.assertAlmostEqual(config['parameters'][key], 13.2)
                self.assertNotIn(key, config.get('output_manual_fields', []))
                self.assertAlmostEqual(config['response_parameter_defaults'][key]['value'], 13.2)
                self.assertEqual(config['parameters']['kubo_freq_max'], 6.)

    def test_eigenvalue_initial_value_can_be_negative_without_occupation_reference(self):
        menu = self.menu()
        config = self.response_window_config()
        config['parameters'].clear()
        config['windows'].update(dis_froz_min=-4., dis_froz_max=-2.)
        messages = []
        menu._parameters(config, lambda _: '0', messages.append)
        self.assertEqual(config['parameters']['kubo_eigval_max'], -2.)
        self.assertNotIn('kubo_freq_max', config['parameters'])
        shown = next(line for line in messages if '(kubo_eigval_max)' in line)
        self.assertIn('-2.0 eV [初值]', shown)

    def test_photon_manual_value_same_value_and_clear_survive_fermi_change(self):
        menu = self.menu()
        for entered, expected in [('6', 6.), ('10', 10.), ('-', None)]:
            with self.subTest(entered=entered):
                config = self.response_window_config()
                keys = list(menu._task_fields(config))
                photon = str(keys.index('kubo_freq_max') + 1)
                fermi = str(keys.index('fermi_energy') + 1)
                answers = iter([photon, entered, fermi, '5.2', '0'])
                menu._parameters(config, lambda _: next(answers), lambda _: None)
                self.assertEqual(config['parameters'].get('kubo_freq_max'), expected)
                self.assertIn('kubo_freq_max', config.get('output_manual_fields', []))
                self.assertNotIn('kubo_freq_max', config.get('response_parameter_defaults', {}))

    def test_photon_enter_and_cancel_keep_automatic_refresh_after_fermi_edit(self):
        menu = self.menu()
        for entered in ('', 'b'):
            with self.subTest(entered=entered):
                config = self.response_window_config()
                keys = list(menu._task_fields(config))
                photon = str(keys.index('kubo_freq_max') + 1)
                fermi = str(keys.index('fermi_energy') + 1)
                answers = iter([photon, entered, fermi, '5.2', '0'])
                menu._parameters(config, lambda _: next(answers), lambda _: None)
                self.assertAlmostEqual(config['parameters']['kubo_freq_max'], 9.)
                self.assertNotIn('kubo_freq_max', config.get('output_manual_fields', []))
                self.assertAlmostEqual(config['response_parameter_defaults']['kubo_freq_max']['value'], 9.)

    def test_window_menu_refreshes_photon_limit_on_edit_and_retracts_it_on_clear(self):
        menu = self.menu()
        config = self.response_window_config()
        menu._parameters(config, lambda _: '0', lambda _: None)
        answers = iter(['3', '-0.8', '13.2', '0'])
        menu._windows(config, lambda _: next(answers), lambda _: None)
        self.assertAlmostEqual(config['parameters']['kubo_freq_max'], 9.)
        self.assertAlmostEqual(config['parameters']['kubo_eigval_max'], 13.2)
        answers = iter(['5', '0'])
        menu._windows(config, lambda _: next(answers), lambda _: None)
        self.assertNotIn('kubo_freq_max', config['parameters'])
        self.assertNotIn('kubo_eigval_max', config['parameters'])

    def test_missing_settings_refreshes_response_default_without_visiting_parameter_menu(self):
        menu = self.menu()
        config = self.response_window_config()
        menu._missing_settings(config)
        self.assertAlmostEqual(config['parameters']['kubo_freq_max'], 10.)
        self.assertAlmostEqual(config['parameters']['kubo_eigval_max'], 14.2)

    def test_shift_current_adaptive_controls_follow_switch_without_losing_saved_values(self):
        menu = self.menu()
        config = {'tasks': ['shift_current'], 'parameters': {'kubo_adpt_smr_fac': 2.,
                                                             'kubo_adpt_smr_max': .4}}
        fields = menu._task_fields(config)
        self.assertNotIn('kubo_adpt_smr_fac', fields)
        self.assertNotIn('kubo_adpt_smr_max', fields)
        config['parameters']['kubo_adpt_smr'] = True
        fields = menu._task_fields(config)
        self.assertIn('kubo_adpt_smr_fac', fields)
        self.assertIn('kubo_adpt_smr_max', fields)
        self.assertEqual(config['parameters']['kubo_adpt_smr_fac'], 2.)
        self.assertEqual(config['parameters']['kubo_adpt_smr_max'], .4)

    def test_registry_inserts_wannier_without_changing_existing_handlers(self):
        from qbox.registry import TASKS, get_task
        self.assertEqual(get_task(10).slug, 'unfold-input')
        self.assertEqual(get_task(11).slug, 'wannier-input')
        self.assertEqual(get_task(12).handler, 'run_qe_scf_calculation')
        self.assertEqual(get_task(38).handler, 'qe_action_vasp_to_cif')
        self.assertEqual([t.id for t in TASKS], list(range(41)))

    def test_six_directions_precede_parameters_and_switch_replaces_tasks(self):
        menu = self.menu()
        config = {'source': None, 'seed': 'test', 'mode': 'new', 'grid': [2, 2, 2],
                  'tasks': [], 'parameters': {}, 'nbnd': None}
        entries = iter(['1', '4', '3 4 1', 'b', '2', 'b', 'q'])
        output = []
        self.assertEqual(menu.run_interactive(config, input_fn=lambda _: next(entries),
                                               output=output.append), 0)
        text = '\n'.join(output)
        self.assertLess(text.index('精细电子结构'), text.index('计算项目与生成模式'))
        self.assertIn('轨道磁性与旋光', text)
        self.assertEqual(config['grid'], [3, 4, 1])
        self.assertEqual(config['tasks'], ['orbitals'])
        self.assertNotIn('bands', config['tasks'])

    def test_menu_invalid_grid_is_rejected_without_losing_common_config(self):
        menu = self.menu()
        config = {'seed': 'retained', 'mode': 'new', 'grid': [2, 2, 2],
                  'tasks': [], 'parameters': {}}
        entries = iter(['3', '4', '2 0 1', 'b', 'q'])
        output = []
        menu.run_interactive(config, input_fn=lambda _: next(entries), output=output.append)
        self.assertEqual(config['grid'], [2, 2, 2])
        self.assertEqual(config['seed'], 'retained')
        self.assertTrue(any('正整数' in line for line in output))

    def test_typed_parameter_editor_accepts_numbers_vectors_and_booleans(self):
        menu = self.menu()
        self.assertEqual(menu.parse_field('25.5', {'type': 'float'}), 25.5)
        self.assertEqual(menu.parse_field('4 5 6', {'type': 'mesh'}), [4, 5, 6])
        self.assertIs(menu.parse_field('yes', {'type': 'bool'}), True)
        with self.assertRaises(ValueError):
            menu.parse_field('2.5', {'type': 'int'})

    def test_required_value_retries_and_cancel_keeps_original(self):
        menu = self.menu()
        config, output = {}, []
        answers = iter(['', '-', 'wrong', '40'])
        self.assertTrue(menu._edit(config, 'nbnd', 'QE 能带数',
                                  {'type': 'int', 'min': 1, 'required': True},
                                  lambda _: next(answers), output.append))
        self.assertEqual(config['nbnd'], 40)
        self.assertTrue(any('必填' in line for line in output))
        self.assertFalse(menu._edit(config, 'nbnd', 'QE 能带数',
                                   {'type': 'int', 'min': 1, 'required': True},
                                   lambda _: 'b', output.append))
        self.assertEqual(config['nbnd'], 40)

    def test_windows_are_optional_and_bounds_are_saved_as_valid_pairs(self):
        menu = self.menu()
        config = {'mode': 'new'}
        menu._windows(config, lambda _: '0', lambda _: None)
        self.assertFalse(config.get('windows'))
        answers = iter(['2', '-5', 'b', '0'])
        menu._windows(config, lambda _: next(answers), lambda _: None)
        self.assertFalse(config.get('windows'))
        answers = iter(['2', '-5', '10', '3', '-6', '8', '0'])
        output = []
        menu._windows(config, lambda _: next(answers), output.append)
        self.assertEqual(config['windows'], {'dis_win_min': -5., 'dis_win_max': 10.})
        self.assertTrue(any('冻结窗' in line and '外窗' in line for line in output))

    def test_explicit_window_clears_lock_defaults_even_when_already_empty(self):
        menu = self.menu()
        for choice in ('1', '5'):
            with self.subTest(choice=choice):
                config = {'mode': 'new'}
                answers = iter([choice, '0'])
                menu._windows(config, lambda _: next(answers), lambda _: None)
                self.assertTrue(config.get('windows_manual'))
                self.assertEqual(config['windows'], {})

    def test_changed_window_pair_locks_defaults_but_cancelled_edit_does_not(self):
        menu = self.menu()
        for values, manual in [(['-3', '8'], True), (['-3', 'b'], False)]:
            with self.subTest(values=values):
                config = {'mode': 'new', 'windows': {'dis_win_min': -5., 'dis_win_max': 10.}}
                answers = iter(['2', *values, '0'])
                menu._windows(config, lambda _: next(answers), lambda _: None)
                self.assertEqual(bool(config.get('windows_manual')), manual)

    def test_projection_add_preserves_existing_projection_lines(self):
        from test_wannier_inputs import SCF
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.in'
            source.write_text(SCF)
            config = {'source': str(source), 'projections': ['Fe1:s']}
            answers = iter(['1', '2', 'p', '0'])
            menu.edit_projections(config, config, lambda _: next(answers), lambda _: None)
            self.assertEqual(config['projections'], ['Fe1:s', 'Fe2:p'])

    def test_filename_help_shows_outputs_and_invalid_paths_do_not_change_seed(self):
        menu = self.menu()
        config, output = {'seed': 'relax'}, []
        answers = iter(['folder/name', '-', 'sample_w90'])
        menu._seed_editor(config, lambda _: next(answers), output.append)
        self.assertEqual(config['seed'], 'sample_w90')
        self.assertIn('relax.win', '\n'.join(output))
        self.assertIn('sample_w90.nscf.in', '\n'.join(output))

    def test_changing_window_energy_reference_preserves_absolute_bounds(self):
        menu = self.menu()
        windows = {'dis_win_min': -5., 'dis_win_max': 10.,
                   'dis_froz_min': -2., 'dis_froz_max': 3.}
        answers = iter(['2', '4.5'])
        menu._window_reference(windows, lambda _: next(answers), lambda _: None)
        self.assertEqual(windows['reference'], 'fermi')
        self.assertEqual(windows['dis_win_min'], -9.5)
        self.assertEqual(windows['dis_froz_max'], -1.5)
        menu._window_reference(windows, lambda _: '1', lambda _: None)
        self.assertEqual(windows['dis_win_min'], -5.)
        self.assertEqual(windows['dis_froz_max'], 3.)

    def test_cancelled_reference_or_path_edit_keeps_saved_values(self):
        menu = self.menu()
        windows = {'dis_win_min': -5., 'dis_win_max': 10.}
        answers = iter(['2', 'b'])
        menu._window_reference(windows, lambda _: next(answers), lambda _: None)
        self.assertEqual(windows, {'dis_win_min': -5., 'dis_win_max': 10.})
        config = {'tasks': ['bands'], 'parameters': {'kpoint_path': 'auto'}}
        answers = iter(['1', '2', 'G 0 0 0 X 0.5 0 0', 'b', 'b'])
        menu._parameters(config, lambda _: next(answers), lambda _: None)
        self.assertEqual(config['parameters']['kpoint_path'], 'auto')

    def test_collinear_view_does_not_freeze_inherited_windows_and_clear_is_explicit(self):
        menu = self.menu()
        config = {'spin_mode': 'collinear',
                  'windows': {'dis_win_min': -5., 'dis_win_max': 5.}}
        answers = iter(['2', 'b'])
        menu._windows(config, lambda _: next(answers), lambda _: None)
        self.assertNotIn('windows', config['channels']['up'])
        answers = iter(['2', '1', '0'])
        menu._windows(config, lambda _: next(answers), lambda _: None)
        self.assertEqual(config['channels']['up']['windows'], {})
        self.assertEqual(config['windows']['dis_win_max'], 5.)

    def test_collinear_clear_excluded_bands_does_not_restore_shared_exclusions(self):
        menu = self.menu()
        config = {'spin_mode': 'collinear', 'exclude_bands': [1, 2]}
        answers = iter(['2', '4', '-', '0'])
        menu._bands(config, lambda _: next(answers), lambda _: None)
        self.assertEqual(config['channels']['up']['exclude_bands'], [])
        self.assertEqual(config['exclude_bands'], [1, 2])

    def test_all_six_directions_have_actionable_required_parameter_guidance(self):
        from qbox.io.wannier_profiles import DIRECTIONS
        menu = self.menu()
        for direction in DIRECTIONS:
            with self.subTest(direction=direction['id']):
                config = {'mode': 'new', 'tasks': list(direction['tasks']), 'parameters': {}}
                missing = menu._missing_settings(config)
                self.assertTrue(any('菜单 5' in item for item in missing))
                self.assertEqual(any('菜单 7' in item for item in missing), direction['id'] != 'optical')
                output = []
                menu._parameters(config, lambda _: 'b', output.append)
                self.assertIn('待补全' if direction['id'] == 'optical' else '待填', '\n'.join(output))

    def test_cif_bridge_runs_after_direction_and_retains_selected_task(self):
        from test_wannier_inputs import SCF
        from qbox.io.wannier_workflow import initial_config
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cif = root / 'relax.cif'
            cif.write_text('data_structure\n')
            scf = root / 'relax.scf.in'
            scf.write_text(SCF)
            config, output = initial_config(cif), []
            entries = iter(['2', 'q'])
            def bridge(source, **kwargs):
                self.assertEqual(source, str(cif))
                self.assertEqual(config['tasks'], ['orbitals'])
                self.assertIn('Wannier90 输入生成：选择计算方向', output)
                self.assertFalse(any('1) 计算项目与生成模式' in line for line in output))
                return scf
            with patch.object(menu, 'find_existing_qe', return_value=[]), \
                 patch.object(menu, 'generate_scf_from_cif', side_effect=bridge), contextlib.chdir(root):
                self.assertEqual(menu.run_interactive(config, lambda _: next(entries), output.append), 0)
            self.assertEqual(config['source'], str(scf))
            self.assertEqual(config['structure_source'], str(cif))
            self.assertEqual(config['seed'], 'relax')
            self.assertEqual(config['tasks'], ['orbitals'])
            self.assertEqual(config['run_root'], str(root))
            self.assertTrue(config['nbnd_confirmed'])
            self.assertTrue(any('SCF 输入' in line for line in output))

    def test_cif_cancel_returns_to_directions_and_does_not_adopt_stale_source(self):
        menu = self.menu()
        config = {'source': '', 'structure_source': '/pending.cif', 'mode': 'new'}
        entries, output = iter(['1', 'q']), []
        with patch.object(menu, 'find_existing_qe', return_value=[]), \
             patch.object(menu, 'generate_scf_from_cif', return_value=None) as bridge:
            self.assertEqual(menu.run_interactive(config, lambda _: next(entries), output.append), 0)
        bridge.assert_called_once()
        self.assertEqual(config['source'], '')
        self.assertEqual(output.count('Wannier90 输入生成：选择计算方向'), 2)

    def test_cif_source_change_cancel_preserves_original_configuration(self):
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            cif = Path(directory) / 'new.cif'
            cif.write_text('data_structure\n')
            config = {'source': 'old.in', 'mode': 'new', 'tasks': ['model'],
                      'parameters': {'fermi_energy': 4.2}, 'nbnd': 12}
            original = dict(config)
            with patch.object(menu, 'find_existing_qe', return_value=[]), \
                 patch.object(menu, 'generate_scf_from_cif', return_value=None):
                menu._sources(config, lambda _: str(cif), lambda _: None)
            self.assertEqual(config, original)

    def test_cif_bridge_failure_keeps_menu_available_to_change_source(self):
        menu = self.menu()
        config = {'source': '', 'structure_source': '/pending.cif', 'mode': 'new'}
        entries, output = iter(['1', 'q']), []
        with patch.object(menu, 'find_existing_qe', return_value=[]), \
             patch.object(menu, 'generate_scf_from_cif', side_effect=ValueError('CIF 转换失败')):
            self.assertEqual(menu.run_interactive(config, lambda _: next(entries), output.append), 0)
        self.assertIn('检查未通过：CIF 转换失败', output)
        self.assertTrue(any('2) 来源' in line for line in output))

    def test_cif_existing_scf_skips_generation_and_imports_its_parameters(self):
        from test_wannier_inputs import SCF
        from qbox.io.wannier_workflow import initial_config
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cif, scf = root / 'relax.cif', root / 'relax.scf.in'
            cif.write_text('data_structure\n')
            scf.write_text(SCF)
            config, output = initial_config(cif), []
            answers = iter(['1', 'q'])
            with patch.object(menu, 'find_existing_qe', return_value=[scf]), \
                 patch.object(menu, 'generate_scf_from_cif') as generate, contextlib.chdir(root):
                self.assertEqual(menu.run_interactive(config, lambda _: next(answers), output.append), 0)
            generate.assert_not_called()
            self.assertEqual(config['source'], str(scf))
            self.assertEqual(config['nbnd'], initial_config(scf)['nbnd'])
            self.assertEqual(config['spin_mode'], initial_config(scf)['spin_mode'])
            self.assertEqual(config['tasks'], ['bands'])
            text = '\n'.join(output)
            self.assertIn('已读取 SCF 输入', text)
            self.assertNotIn('配置 QE', text)
            self.assertNotIn('QE 参数菜单中选择 0', text)
            self.assertNotIn('已生成并读取', text)

    def test_multiple_matching_scf_inputs_allow_selection_or_cancel(self):
        from test_wannier_inputs import SCF
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'one.scf.in', root / 'two.scf.in'
            first.write_text(SCF)
            second.write_text(SCF.replace('nbnd=12', 'nbnd=16'))
            for answer in ('2', 'b'):
                with self.subTest(answer=answer):
                    config = {'source': '', 'structure_source': str(root / 'relax.cif'),
                              'seed': 'relax', 'mode': 'new', 'tasks': ['model']}
                    with patch.object(menu, 'find_existing_qe', return_value=[first, second]), \
                         patch.object(menu, 'generate_scf_from_cif') as generate:
                        result = menu._complete_structure(config, lambda _: answer, lambda _: None)
                    generate.assert_not_called()
                    self.assertEqual(result, answer != 'b')
                    self.assertEqual(config['source'], str(second) if answer == '2' else '')
                    if answer == '2':
                        self.assertEqual(config['nbnd'], 16)

    def test_existing_matching_inputs_do_not_offer_regeneration(self):
        menu = self.menu()
        config = {'source': '', 'structure_source': '/run/relax.cif',
                  'seed': 'relax', 'mode': 'new', 'tasks': ['model']}
        answers, messages = iter(['0', 'b']), []
        with patch.object(menu, 'find_existing_qe', return_value=[Path('/run/a.scf.in'), Path('/run/b.scf.in')]), \
             patch.object(menu, 'generate_scf_from_cif', return_value=None) as generate:
            self.assertFalse(menu._complete_structure(config, lambda _: next(answers), messages.append))
        generate.assert_not_called()
        self.assertFalse(any(line.startswith('0)') for line in messages))

    def test_mode_uses_numbered_explanations_and_preserves_internal_values(self):
        menu = self.menu()
        config = {'mode': 'new', 'tasks': [], 'nbnd_confirmed': True}
        entries = iter(['2', '1', '3', '2', 'q'])
        output = []
        menu.run_interactive(config, lambda _: next(entries), output.append)
        self.assertEqual(config['mode'], 'existing')
        self.assertEqual(config['tasks'], ['model'])
        self.assertFalse(config['nbnd_confirmed'])
        text = '\n'.join(output)
        self.assertIn('1) 从 QE 开始建立 Wannier 模型', text)
        self.assertIn('2) 使用已有 Wannier 模型', text)
        self.assertIn('在位能和跃迁矩阵', text)
        self.assertNotIn('mode=new', text)

    def test_mode_reprompts_on_invalid_input_and_cannot_be_cleared(self):
        from qbox.io.wannier_profiles import DIRECTIONS
        config = {'mode': 'existing', 'tasks': ['model'], 'nbnd_confirmed': True}
        entries = iter(['', '-', 'unknown', '1'])
        output = []
        self.menu()._projects(config, DIRECTIONS[1], lambda _: next(entries), output.append)
        self.assertEqual(config['mode'], 'new')
        self.assertEqual(config['tasks'], ['model'])
        self.assertTrue(any('请输入 1–2' in line for line in output))

    def test_mode_retains_existing_on_enter_and_accepts_legacy_tokens(self):
        from qbox.io.wannier_profiles import DIRECTIONS
        menu = self.menu()
        for answer, expected in [('', 'existing'), ('new', 'new'), ('existing', 'existing')]:
            with self.subTest(answer=answer):
                config = {'mode': 'existing', 'tasks': ['model'], 'nbnd_confirmed': True}
                entries = iter(['', answer])
                menu._projects(config, DIRECTIONS[1], lambda _: next(entries), lambda _: None)
                self.assertEqual(config['mode'], expected)
                self.assertEqual(config['nbnd_confirmed'], expected == 'existing')

    def test_numbered_choices_and_boolean_editor_store_native_values(self):
        menu = self.menu()
        config, output = {}, []
        menu._edit(config, 'reference', '能量参考',
                   {'type': 'choice', 'choices': ('absolute', 'fermi'), 'default': 'absolute'},
                   lambda _: '2', output.append)
        self.assertEqual(config['reference'], 'fermi')
        self.assertTrue(any('费米能' in line for line in output))
        menu._edit(config, 'include_spin', '包含自旋项', {'type': 'bool', 'default': True},
                   lambda _: '2', output.append)
        self.assertIs(config['include_spin'], False)
        menu._edit(config, 'include_spin', '包含自旋项', {'type': 'bool'},
                   lambda _: 'yes', output.append)
        self.assertIs(config['include_spin'], True)

    def test_sources_explain_inputs_for_selected_mode(self):
        for mode, expected in [('new', 'SCF/NSCF 输入文件'), ('existing', '.win')]:
            with self.subTest(mode=mode):
                output, prompts = [], []
                self.menu()._sources({'mode': mode, 'tasks': []},
                                     lambda text: prompts.append(text) or '', output.append)
                self.assertIn(expected, '\n'.join(output))
                self.assertTrue(any('文件路径' in text for text in prompts))

    def test_reselecting_same_source_keeps_manual_basis_and_optional_paths(self):
        from test_wannier_inputs import SCF
        from qbox.io.wannier_workflow import initial_config
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.in'
            source.write_text(SCF)
            cif = Path(directory) / 'source.cif'
            cif.write_text('data_source\n')
            config = initial_config(source)
            config.update(nbnd=40, num_wann=8, projections=['Fe1:s;p', 'Fe2:s;p'],
                          source_output='my.scf.out', tasks=['qe_bands'], band_kpt='my_band.kpt',
                          structure_source=str(cif))
            for same in (source, cif):
                answers = iter([str(same), '', '', ''])
                menu._sources(config, lambda _: next(answers), lambda _: None)
            self.assertEqual(config['nbnd'], 40)
            self.assertEqual(config['num_wann'], 8)
            self.assertEqual(config['projections'], ['Fe1:s;p', 'Fe2:s;p'])
            self.assertEqual(config['source_output'], 'my.scf.out')
            self.assertEqual(config['band_kpt'], 'my_band.kpt')

    def test_correcting_run_directory_retries_defaults_without_restoring_user_clears(self):
        from test_wannier_inputs import SCF
        from qbox.io.wannier_workflow import initial_config
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            root = Path(directory)
            run = root / 'run'
            (run / 'pseudos').mkdir(parents=True)
            (run / 'pseudos/Fe.upf').write_text('<UPF><PP_HEADER z_valence="4"/>'
                                             '<PP_PSWFC><PP_CHI.1 l="0"/>'
                                             '<PP_CHI.2 l="1"/></PP_PSWFC></UPF>')
            source = root / 'source.in'
            source.write_text(SCF.replace('nbnd=12,', '').replace("pseudo_dir='../pseudos'", "pseudo_dir='./pseudos'"))
            config = initial_config(source)
            self.assertIsNone(config['nbnd'])
            answers = iter(['', '', str(run)])
            menu._sources(config, lambda _: next(answers), lambda _: None)
            self.assertEqual((config['nbnd'], config['num_wann']), (12, 8))
            # Explicitly clearing projections must not be undone by a later refresh.
            answers = iter(['4', '0'])
            menu.edit_projections(config, config, lambda _: next(answers), lambda _: None)
            config['nbnd'] = 30
            menu._mark_basis_edit(config, 'nbnd')
            answers = iter(['', '', str(root), '', '', str(run)])
            for _ in range(2):
                menu._sources(config, lambda _: next(answers), lambda _: None)
            self.assertEqual(config['nbnd'], 30)
            self.assertEqual(config['projections'], [])
            # A short imported SCF count needs the same NSCF adjustment after
            # fixing the directory as it does on a successful first import.
            source.write_text(source.read_text().replace('ecutwfc=5.0D1,', 'ecutwfc=5.0D1, nbnd=4,'))
            fresh = initial_config(source)
            self.assertEqual(fresh['nbnd'], 4)
            answers = iter(['', '', str(run)])
            menu._sources(fresh, lambda _: next(answers), lambda _: None)
            self.assertEqual((fresh['nbnd'], fresh['num_wann']), (12, 8))

    def test_first_run_basis_can_generate_without_visiting_menu_five(self):
        from test_wannier_inputs import SCF
        from qbox.io.wannier_workflow import initial_config
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            root = Path(directory)
            (root / 'Fe.upf').write_text('<UPF><PP_HEADER z_valence="4"/>'
                                       '<PP_PSWFC><PP_CHI.1 l="0" label="4S"/>'
                                       '<PP_CHI.2 l="1" label="4P"/></PP_PSWFC></UPF>')
            source = root / 'source.in'
            source.write_text(SCF.replace('nbnd=12,', '').replace("pseudo_dir='../pseudos'", "pseudo_dir='.'"))
            config = initial_config(source)
            self.assertEqual(config['num_wann'], 8)
            self.assertEqual(config['nbnd'], 12)
            self.assertTrue(config['nbnd_confirmed'])
            answers = iter(['2', '1', '3', '', '0'])
            menu.run_interactive(config, lambda _: next(answers), lambda _: None)
            values, _ = _win_parts((root / 'source.win').read_text())
            self.assertEqual(values['num_wann'], '8')
            self.assertEqual(values['num_iter'], '1000')

    def test_short_scf_band_count_is_enlarged_only_for_new_nscf(self):
        from test_wannier_inputs import SCF
        from qbox.io.wannier_workflow import initial_config
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            root = Path(directory)
            (root / 'Fe.upf').write_text('<UPF><PP_HEADER z_valence="4"/>'
                                       '<PP_PSWFC><PP_CHI.1 l="0"/>'
                                       '<PP_CHI.2 l="1"/></PP_PSWFC></UPF>')
            source = root / 'source.in'
            original = SCF.replace('nbnd=12,', 'nbnd=4,').replace("pseudo_dir='../pseudos'", "pseudo_dir='.'")
            source.write_text(original)
            config = initial_config(source)
            self.assertEqual(config['num_wann'], 8)
            self.assertEqual(config['nbnd'], 12)
            self.assertEqual(source.read_text(), original)
            self.assertTrue(any('原 SCF 的 4' in note for note in config['basis_default_notes']))

    def test_changing_source_drops_previous_material_energy_and_path_settings(self):
        from test_wannier_inputs import SCF
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / 'old.in', root / 'new.in'
            old.write_text(SCF)
            new.write_text(SCF.replace('nbnd=12', 'nbnd=20'))
            config = {'source': str(old), 'mode': 'new', 'tasks': ['bands'],
                      'parameters': {'fermi_energy': 3., 'kpoint_path': ['G 0 0 0 X 0.5 0 0']}}
            answers = iter([str(new), '', ''])
            menu._sources(config, lambda _: next(answers), lambda _: None)
            self.assertNotIn('fermi_energy', config['parameters'])
            self.assertNotEqual(config['parameters'].get('kpoint_path'), ['G 0 0 0 X 0.5 0 0'])
            self.assertEqual(config['tasks'], ['bands'])

    def test_existing_status_labels_band_count_after_exclusions(self):
        config = {'mode': 'existing', 'nbnd': 30, 'exclude_bands': [1, 2, 3, 4, 5, 6],
                  'tasks': []}
        entries, output = iter(['1', '5', 'q']), []
        self.menu().run_interactive(config, lambda _: next(entries), output.append)
        text = '\n'.join(output)
        self.assertIn('参与 Wannier 的能带数：30', text)
        self.assertNotIn('QE 能带数：30', text)

    def test_automatic_config_requires_explicit_conflict_strategy(self):
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text('{}')
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    menu.main(['--config', str(path)])
            self.assertEqual(error.exception.code, 2)

    def test_cli_accepts_generated_metadata_wrapper_and_preserves_model_settings(self):
        menu = self.menu()
        from test_wannier_inputs import SCF, config as base_config
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            Path('source.in').write_text(SCF)
            Path('saved.qbox.json').write_text(json.dumps({
                'schema_version': 1, 'config': base_config(source='source.in', num_iter=321)}))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = menu.main(['--config', 'saved.qbox.json', '--conflict', 'backup'])
            self.assertEqual(status, 0)
            self.assertEqual(_win_parts(Path('iron.win').read_text())[0]['num_iter'], '321')
            saved = json.loads(Path('iron.qbox.json').read_text())['config']
            self.assertEqual(saved['grid'], [2, 1, 2])
            self.assertEqual(saved['projections'], ['Fe1:s', 'Fe2:s'])

    def test_cli_rejects_nonobject_nested_config_without_publishing(self):
        menu = self.menu()
        for value in (None, [], 'source.in', 0):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
                Path('saved.qbox.json').write_text(json.dumps({'config': value}))
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
                    status = menu.main(['--config', 'saved.qbox.json', '--conflict', 'backup'])
                self.assertEqual(status, 1)
                self.assertIn('config', errors.getvalue())
                self.assertIn('对象', errors.getvalue())
                self.assertEqual([path.name for path in Path.cwd().iterdir()], ['saved.qbox.json'])

    def test_sampled_midgap_is_labelled_as_occupation_reference(self):
        menu = self.menu()
        config = {'tasks': ['shift_current'], 'parameters': {'fermi_energy': 2.},
                  'qe_output': self.output_record(fermi=None),
                  'output_parameter_values': {'fermi_energy': 2.},
                  'fermi_source': {'method': 'sampled_midgap'}}
        shown = menu._task_setting(config, 'fermi_energy', menu._task_fields(config)['fermi_energy'])
        self.assertIn('占据参考能', shown)
        self.assertIn('带隙中点估计', shown)

    def test_switching_tasks_reapplies_and_releases_gap_reference(self):
        menu, api = self.output_ui()
        from qbox.io.wannier_profiles import DIRECTIONS
        config = {'source': '/calculation/scf.in', 'mode': 'new', 'tasks': ['optical'], 'parameters': {}}
        record = self.output_record(fermi=None)
        record['gap_reference'] = {'value_eV': 2., 'vbm': 1., 'cbm': 3., 'method': 'sampled_midgap'}
        api.apply_output(config, record)
        context = menu._output_context(config)
        config['_output_scan_key'] = context
        answers = iter(['2', ''])
        menu._projects(config, DIRECTIONS[4], lambda _: next(answers), lambda _: None)
        self.assertEqual(config['parameters'].get('fermi_energy'), 2.)
        self.assertEqual(config['fermi_source']['method'], 'sampled_midgap')
        self.assertEqual(config['_output_scan_key'], context)
        answers = iter(['1', ''])
        menu._projects(config, DIRECTIONS[4], lambda _: next(answers), lambda _: None)
        self.assertNotIn('fermi_energy', config['parameters'])

    def test_unique_usable_gap_output_is_selected_without_ambiguous_prompt(self):
        menu, api = self.output_ui()
        config = {'source': '/calculation/scf.in', 'tasks': ['shift_current'], 'parameters': {}}
        unusable = self.output_record(fermi=None)
        usable = self.output_record('/calculation/nscf.out', fermi=None, kind='nscf')
        usable['gap_reference'] = {'value_eV': 2., 'vbm': 1., 'cbm': 3., 'method': 'sampled_midgap'}
        messages = []
        with patch.object(api, 'candidates', return_value=[unusable, usable]):
            menu._scan_outputs(config, lambda _: self.fail('only one usable reference should not prompt'), messages.append)
        self.assertEqual(config['source_output'], usable['path'])
        self.assertEqual(config['parameters'].get('fermi_energy'), 2.)
        self.assertIn('带隙中点估计', '\n'.join(messages))

    def test_pending_generation_and_cli_resume_explain_missing_reference(self):
        menu = self.menu()
        from test_wannier_inputs import SCF, config as base_config
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            Path('source.in').write_text(SCF)
            config = base_config(source='source.in', tasks=['shift_current'], nbnd_confirmed=True)
            messages = []
            self.assertTrue(menu._generate(config, lambda _: self.fail('new files need no prompt'), messages.append))
            self.assertIn('NSCF', '\n'.join(messages))
            self.assertIn('补全', '\n'.join(messages))
            self.assertTrue(json.loads(Path('iron.qbox.json').read_text())['config']['pending_fermi'])
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(io.StringIO()):
                status = menu.main(['--config', 'iron.qbox.json', '--conflict', 'backup'])
            self.assertEqual(status, 0)
            self.assertIn('尚未取得占据参考能', captured.getvalue())
            self.assertIn('菜单 7', captured.getvalue())

    def test_pending_cli_package_rescans_completed_nscf_and_preserves_all_choices(self):
        menu = self.menu()
        from test_wannier_outputs import SCF, UPF, output, fixed_nscf_output
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            root = Path(directory)
            (root / 'pseudo').mkdir()
            (root / 'pseudo/Si.UPF').write_text(UPF)
            Path('scf.in').write_text(SCF)
            Path('scf.out').write_text(output(fermi='highest occupied level (ev): 1.0'))
            config = dict(source=str(root / 'scf.in'), run_root=str(root), mode='new', seed='si',
                          tasks=['shift_current', 'optical'], grid=[2, 1, 1], nbnd=6, num_wann=2,
                          projections=['Si:s'], num_iter=321,
                          parameters={'sc_eta': .17, 'berry_kmesh': [7, 7, 7],
                                      'kubo_freq_max': 5., 'kubo_eigval_max': 8.,
                                      'kpoint_path': [{'start_label': 'G', 'start': [0, 0, 0],
                                                      'end_label': 'X', 'end': [.5, 0, 0]}]})
            Path('settings.json').write_text(json.dumps(config))
            initial_errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(initial_errors):
                status = menu.main(['--config', 'settings.json', '--conflict', 'backup'])
            self.assertEqual(status, 0, initial_errors.getvalue())
            pending = json.loads(Path('si.qbox.json').read_text())['config']
            self.assertTrue(pending['pending_fermi'])
            self.assertEqual(pending['source_output'], str(root / 'scf.out'))
            self.assertNotIn('postw90.x', Path('si.README.txt').read_text())
            Path('si.nscf.out').write_text(fixed_nscf_output().replace('Reading input from nscf.in',
                                                                    'Reading input from si.nscf.in'))
            captured, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(errors):
                status = menu.main(['--config', 'si.qbox.json', '--conflict', 'backup'])
            self.assertEqual(status, 0, errors.getvalue())
            completed = json.loads(Path('si.qbox.json').read_text())['config']
            self.assertFalse(completed.get('pending_fermi'))
            self.assertEqual(completed['source_output'], str(root / 'si.nscf.out'))
            self.assertEqual(completed['fermi_source']['method'], 'sampled_midgap')
            self.assertEqual(completed['parameters']['fermi_energy'], 2.)
            for key in ('tasks', 'grid', 'nbnd', 'num_wann', 'projections', 'num_iter'):
                self.assertEqual(completed[key], config[key])
            self.assertEqual(completed['parameters']['sc_eta'], .17)
            self.assertEqual(completed['parameters']['berry_kmesh'], [7, 7, 7])
            self.assertIn('postw90.x', Path('si.README.txt').read_text())
            self.assertNotIn('尚未取得占据参考能', captured.getvalue())
            self.assertTrue(Path('bak/si.qbox.json.bak').is_file())

    def test_new_shift_current_defers_postprocessing_energies_but_existing_model_requires_them(self):
        menu = self.menu()
        from test_wannier_inputs import config as base_config
        config = base_config(source='scf.in', tasks=['shift_current'], nbnd_confirmed=True)
        self.assertEqual(menu._missing_settings(config), [])
        field = menu._task_fields(config)['fermi_energy']
        shown = menu._task_setting(config, 'fermi_energy', field)
        self.assertIn('待补全', shown)
        self.assertIn('NSCF', shown)
        config['parameters']['kubo_freq_min'] = 1.
        self.assertEqual(menu._missing_settings(config), [])
        config['parameters'].clear()
        config['mode'] = 'existing'
        self.assertIn('费米能', '\n'.join(menu._missing_settings(config)))
        self.assertIn('光子能量上限', '\n'.join(menu._missing_settings(config)))
        self.assertIn('初态和末态', '\n'.join(menu._missing_settings(config)))
        config.update(mode='new', tasks=['shift_current', 'ahc'])
        self.assertIn('费米能', '\n'.join(menu._missing_settings(config)))

    def test_named_and_numeric_cli_forward_all_wannier_arguments(self):
        from test_wannier_inputs import SCF, config as base_config
        with tempfile.TemporaryDirectory(prefix='wannier 参数 ') as directory:
            root = Path(directory)
            (root / 'source.in').write_text(SCF)
            (root / 'space config.json').write_text(json.dumps(base_config(source='source.in')))
            for selector in ('wannier-input', '11'):
                result = subprocess.run(
                    [sys.executable, '-S', '-m', 'qbox', '--task', selector,
                     '--config', 'space config.json', '--conflict', 'backup'],
                    cwd=root, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                    text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(_win_parts((root / 'iron.win').read_text())[0]['write_xyz'], 'true')
            self.assertTrue((root / 'bak/iron.win.bak').is_file())
            self.assertEqual((root / 'source.in').read_text(), SCF)

    def test_guided_projection_editor_expands_species_and_atom_selection(self):
        menu = self.menu()
        from test_wannier_inputs import SCF
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.scf.in'
            source.write_text(SCF)
            config = {'source': str(source), 'projections': []}
            entries = iter(['1', '1', 's;p', '2', '2', 'd', '0'])
            output = []
            menu.edit_projections(config, config, lambda _: next(entries), output.append)
            self.assertEqual(config['projections'], ['Fe1:s;p', 'atom:2:d'])
            self.assertIn('投影实际展开数：9', output)

    def test_new_model_band_editor_accepts_iteration_limits(self):
        from test_wannier_inputs import SCF, config as base_config
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.in'
            source.write_text(SCF)
            config = base_config(source=str(source))
            entries = iter(['6', '1000', '700', '0'])
            menu._bands(config, lambda _: next(entries), lambda _: None)
            self.assertEqual(config.get('num_iter'), 1000)
            self.assertEqual(config.get('dis_num_iter'), 700)

    def test_shift_current_convergence_editor_saves_manual_values_and_disabled_check(self):
        menu = self.menu()
        config = {'source': 'source.in', 'mode': 'new', 'tasks': ['shift_current'],
                  'num_iter': 1000, 'conv_tol': 1e-10, 'conv_window': 5}
        entries = iter(['6', '2', '2d-9', '3', '0', '0', '0'])
        output = []
        menu._bands(config, lambda _: next(entries), output.append)
        self.assertEqual(config['conv_tol'], 2e-9)
        self.assertEqual(config['conv_window'], 0)
        self.assertIn('conv_tol', config['basis_manual_fields'])
        self.assertIn('conv_window', config['basis_manual_fields'])
        self.assertIn('关闭', '\n'.join(output))

    def test_shift_current_convergence_editor_rejects_negative_tolerance_and_window(self):
        menu = self.menu()
        config = {'source': 'source.in', 'mode': 'new', 'tasks': ['shift_current']}
        entries = iter(['6', '2', '-0.1', '0', '3', '-2', '7', '0', '0'])
        output = []
        menu._bands(config, lambda _: next(entries), output.append)
        self.assertEqual(config.get('conv_tol'), 0.)
        self.assertEqual(config['conv_window'], 7)
        self.assertGreaterEqual(sum('输入无效' in line for line in output), 2)

    def test_shift_current_iteration_confirmation_uses_effective_template_not_generic_default(self):
        config = {'source': 'source.in', 'mode': 'new', 'tasks': ['shift_current'],
                  'dis_num_iter': 1000, 'basis_defaults': {'dis_num_iter': 'generic starting limit'}}
        entries = iter(['6', '4', '', '0', '0'])
        self.menu()._bands(config, lambda _: next(entries), lambda _: None)
        self.assertEqual(config['dis_num_iter'], 1200)

    def test_interactive_config_resume_preserves_tasks_and_does_not_publish_on_exit(self):
        from test_wannier_inputs import SCF, config as base_config
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.in').write_text(SCF)
            config = base_config(source=str(root / 'source.in'), tasks=['shift_current'],
                                 source_output_mode='off', parameters={'sc_eta': .17})
            (root / 'saved.qbox.json').write_text(json.dumps({'config': config}))
            (root / 'iron.win').write_text('User-edited input must survive opening a menu.\n')
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            result = subprocess.run(
                [sys.executable, '-S', '-m', 'qbox', '--task', 'wannier-input',
                 '--config', 'saved.qbox.json', '--interactive'], input='7\n0\nq\n',
                cwd=root, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('当前项目：位移电流', result.stdout)
            self.assertIn('0.17', result.stdout)
            self.assertNotIn('方向编号', result.stdout)
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before)

    def test_existing_model_band_editor_does_not_offer_iteration_changes(self):
        prompts = []
        config = {'mode': 'existing', 'num_iter': 500}
        self.menu()._bands(config, lambda prompt: prompts.append(prompt) or '1000', lambda _: None)
        self.assertEqual(prompts, [])
        self.assertEqual(config['num_iter'], 500)

    def test_interactive_generation_publishes_to_current_directory(self):
        menu = self.menu()
        from test_wannier_inputs import SCF
        from qbox.io.wannier_workflow import initial_config
        with tempfile.TemporaryDirectory(prefix='wannier 菜单 ') as directory:
            source = Path(directory) / 'source.scf.in'
            source.write_text(SCF)
            original = source.read_bytes()
            config = initial_config(str(source))
            config.update(seed='iron', num_wann=2, projections=['Fe1:s', 'Fe2:s'])
            # Choosing 0 generates immediately, with no second save question.
            entries = iter(['2', '1', '3', '', '5', '1', '', '0', '0'])
            output = []
            with contextlib.chdir(directory):
                self.assertEqual(menu.run_interactive(
                    config, lambda _: next(entries), output.append,
                    return_to_main_status=menu.RETURN_TO_MAIN), 0)
            self.assertTrue((Path(directory) / 'iron.win').is_file())
            self.assertEqual(_win_parts((Path(directory) / 'iron.win').read_text())[0]['write_hr'], 'true')
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((Path(directory) / 'WANNIER').exists())

    def test_main_menu_bridge_distinguishes_return_from_end_of_input(self):
        for bridge in (False, True):
            for answers in ('q\n', '1\nq\n', '1\nb\nq\n', ''):
                with self.subTest(bridge=bridge, answers=answers):
                    result = subprocess.run(
                        [sys.executable, '-S', '-m', 'qbox.io.wannier_menu']
                        + (['--from-main-menu'] if bridge else []),
                        input=answers, text=True, capture_output=True,
                        env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
                    self.assertEqual(result.returncode, 10 if bridge and answers else 0,
                                     result.stdout + result.stderr)

    def test_preview_does_not_write_and_cancelled_conflict_stays_in_menu(self):
        from test_wannier_inputs import SCF, config as base_config
        menu = self.menu()
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            source = Path('source.in')
            source.write_text(SCF)
            config = base_config(source=str(source.resolve()), nbnd_confirmed=True)
            config['parameters'] = {'kpoint_path': ['G 0 0 0 X 0.5 0 0']}
            entries, output = iter(['1', '8', 'q']), []
            menu.run_interactive(config, lambda _: next(entries), output.append)
            self.assertFalse(Path('iron.win').exists())
            self.assertTrue(any('待保存' in line for line in output))
            Path('iron.win').write_text('existing input')
            entries, output = iter(['1', '0', '3', 'q']), []
            self.assertEqual(menu.run_interactive(config, lambda _: next(entries), output.append), 0)
            self.assertEqual(Path('iron.win').read_text(), 'existing input')
            self.assertFalse(Path('iron.nscf.in').exists())
            self.assertEqual(output.count('1) 计算项目与生成模式'), 2)
            self.assertTrue(any('iron.win' in line for line in output))

    def test_recovery_command_restores_interrupted_input_transaction(self):
        menu = self.menu()
        from qbox.io import wannier_publish
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'iron.win').write_text('old')
            replace = wannier_publish.os.replace
            def crash(src, dst):
                result = replace(src, dst)
                if Path(dst).name == 'iron.win':
                    raise SystemExit('simulated crash')
                return result
            with patch.object(wannier_publish.os, 'replace', side_effect=crash):
                with self.assertRaises(SystemExit):
                    wannier_publish.publish({'iron.win': 'new'}, root, conflict='backup')
            manifest = next(root.glob('.qbox-wannier-*/transaction.json'))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(menu.main(['--recover', str(manifest)]), 0)
            self.assertEqual((root / 'iron.win').read_text(), 'old')

    def test_symlink_conflict_can_be_renamed_without_overwriting_link_target(self):
        menu = self.menu()
        from test_wannier_inputs import SCF, config as base_config
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.in'
            source.write_text(SCF)
            (root / 'existing.chk').write_text('result')
            (root / 'iron.win').symlink_to(root / 'existing.chk')
            config = base_config(source=str(source), nbnd_confirmed=True)
            entries = iter(['2', 'renamed'])
            output = []
            with contextlib.chdir(root):
                self.assertTrue(menu._generate(config, lambda _: next(entries), output.append))
            self.assertTrue((root / 'iron.win').is_symlink())
            self.assertEqual(source.read_text(), SCF)
            self.assertTrue((root / 'renamed.win').is_file())

    def test_path_editor_offers_automatic_original_cell_path(self):
        menu = self.menu()
        entries = iter(['a'])
        self.assertEqual(menu._path_editor(lambda _: next(entries), lambda _: None), 'auto')

    def test_parameters_hide_spinor_only_and_inactive_frequency_fields(self):
        menu = self.menu()
        output = []
        menu._parameters({'tasks': ['orbitals'], 'parameters': {}, 'spin_mode': 'scalar'},
                         lambda _: 'b', output.append)
        self.assertNotIn('wannier_plot_spinor_mode', '\n'.join(output))
        output = []
        menu._parameters({'tasks': ['shc'], 'parameters': {}, 'spin_mode': 'spinor'},
                         lambda _: 'b', output.append)
        self.assertNotIn('kubo_freq_max', '\n'.join(output))

    def test_existing_qe_comparison_sources_are_editable_and_protected(self):
        menu = self.menu()
        config = {'mode': 'existing', 'source': 'seed.win', 'tasks': ['qe_bands']}
        entries = iter(['', 'scf.out', '/original/run', 'original.scf.in', 'seed_band.kpt'])
        menu._sources(config, lambda _: next(entries), lambda _: None)
        self.assertEqual(config['reference_source'], 'original.scf.in')
        self.assertEqual(config['band_kpt'], 'seed_band.kpt')
        protected = menu._protected(config)
        self.assertNotIn(Path('seed.win').resolve(), protected)
        self.assertIn(Path('scf.out').resolve(), protected)
        self.assertIn(Path('original.scf.in').resolve(), protected)
        self.assertIn(Path('seed_band.kpt').resolve(), protected)

    def test_source_editor_retains_imported_existing_task_parameter_values(self):
        menu = self.menu()
        from test_wannier_workflow import WIN
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'seed.win'
            source.write_text(WIN.replace('fermi_energy = 0', 'fermi_energy = 4.25'))
            config = {'tasks': ['ahc'], 'parameters': {}}
            entries = iter([str(source), '', '', ''])
            menu._sources(config, lambda _: next(entries), lambda _: None)
            self.assertEqual(config['parameters'].get('fermi_energy'), 4.25)
            self.assertEqual(config['tasks'], ['ahc'])

    def test_kmesh_public_command_needs_only_standard_library(self):
        result = subprocess.run([sys.executable, '-S', '-m', 'qbox', 'kmesh', '1', '2', '1',
                                 '--format', 'wannier'], text=True, capture_output=True,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(list(map(float, rows[1])), [0, .5, 0])


if __name__ == '__main__':
    unittest.main()
