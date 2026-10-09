"""Response defaults reach generated files without modifying source models."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qbox.io.wannier_inputs import build_bundle
from qbox.io.wannier_workflow import _basis, _win_parts, initial_config, prepare
from test_wannier_inputs import SCF, config
from test_wannier_workflow import WIN


EF = 10.4551
WINDOWS = dict(dis_win_min=-6.1, dis_win_max=27.3,
               dis_froz_min=5.4551, dis_froz_max=20.4551)
PATH = ['G 0 0 0 X .5 0 0']


class ResponseIntegrationTests(unittest.TestCase):
    def test_direct_bundle_derives_both_limits_before_pending_checks(self):
        cfg = config(tasks=['shift_current'], windows=dict(WINDOWS),
                     parameters={'fermi_energy': EF, 'kpoint_path': PATH},
                     pending_response_parameters=['fermi_energy', 'kubo_freq_max', 'kubo_eigval_max'])
        before = copy.deepcopy(cfg)
        files = build_bundle(SCF, cfg)
        values, _ = _win_parts(files['iron.win'])
        record = json.loads(files['iron.qbox.json'])
        self.assertEqual(values.get('kubo_freq_max'), '10')
        self.assertEqual(values.get('kubo_eigval_max'), '20.4551')
        self.assertNotIn('pending_response_parameters', record['config'])
        self.assertNotIn('pending_fermi', record['config'])
        self.assertEqual(record['status'], 'inputs_generated')
        self.assertIn('postw90.x iron', files['iron.README.txt'])
        self.assertEqual(cfg, before)

    def test_absolute_frozen_bound_supplies_eigenvalue_limit_before_fermi_is_known(self):
        cfg = config(tasks=['shift_current'], windows=dict(WINDOWS),
                     parameters={'kpoint_path': PATH})
        before = copy.deepcopy(cfg)
        files = build_bundle(SCF, cfg)
        values, _ = _win_parts(files['iron.win'])
        record = json.loads(files['iron.qbox.json'])
        self.assertEqual(values.get('kubo_eigval_max'), '20.4551')
        self.assertNotIn('fermi_energy', values)
        self.assertNotIn('kubo_freq_max', values)
        self.assertEqual(record['config']['pending_response_parameters'],
                         ['fermi_energy', 'kubo_freq_max'])
        self.assertEqual(record['status'], 'pending_occupation_reference')
        self.assertNotIn('postw90.x', files['iron.README.txt'])
        self.assertEqual(cfg, before)

    def test_relative_window_limits_use_absolute_bound_and_actual_occupation_reference(self):
        windows = dict(reference='fermi', reference_energy=8.4551,
                       dis_win_min=-15, dis_win_max=20, dis_froz_min=-3, dis_froz_max=12)
        cfg = config(tasks=['shift_current'], windows=windows,
                     parameters={'fermi_energy': EF, 'kpoint_path': PATH})
        before = copy.deepcopy(cfg)
        files = build_bundle(SCF, cfg)
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values.get('dis_froz_max'), '20.4551')
        self.assertEqual(values.get('kubo_eigval_max'), '20.4551')
        self.assertEqual(values.get('kubo_freq_max'), '10')
        self.assertEqual(json.loads(files['iron.qbox.json'])['status'], 'inputs_generated')
        self.assertEqual(cfg, before)

    def test_direct_bundle_preserves_manual_limits_and_clears_stale_pending(self):
        cfg = config(tasks=['shift_current'], windows=dict(WINDOWS),
                     parameters={'fermi_energy': EF, 'kubo_freq_max': 7,
                                 'kubo_eigval_max': 24, 'kpoint_path': PATH},
                     pending_fermi=True, pending_response_parameters=['kubo_freq_max'])
        before = copy.deepcopy(cfg)
        files = build_bundle(SCF, cfg)
        values, _ = _win_parts(files['iron.win'])
        record = json.loads(files['iron.qbox.json'])
        self.assertEqual(values['kubo_freq_max'], '7')
        self.assertEqual(values['kubo_eigval_max'], '24')
        self.assertEqual(record['status'], 'inputs_generated')
        self.assertNotIn('pending_response_parameters', record['config'])
        self.assertNotIn('pending_fermi', record['config'])
        self.assertEqual(cfg, before)

    def test_manual_eigenvalue_override_or_clear_survives_regeneration_and_window_changes(self):
        from qbox.io.wannier_output_defaults import mark_manual
        original = config(tasks=['shift_current'], windows=dict(WINDOWS),
                          parameters={'fermi_energy': EF, 'kpoint_path': PATH})
        automatic = json.loads(build_bundle(SCF, original)['iron.qbox.json'])['config']
        self.assertEqual(automatic['parameters'].get('kubo_eigval_max'), 20.4551)
        for replacement in (24, None):
            with self.subTest(replacement=replacement):
                cfg = copy.deepcopy(automatic)
                if replacement is None:
                    mark_manual(cfg, 'kubo_eigval_max')
                    cfg['parameters'].pop('kubo_eigval_max')
                else:
                    cfg['parameters']['kubo_eigval_max'] = replacement
                for upper in (21.4551, 22.4551):
                    cfg['windows']['dis_froz_max'] = upper
                    before = copy.deepcopy(cfg)
                    files = build_bundle(SCF, cfg)
                    values, _ = _win_parts(files['iron.win'])
                    record = json.loads(files['iron.qbox.json'])
                    if replacement is None:
                        self.assertNotIn('kubo_eigval_max', values)
                        self.assertEqual(record['config']['pending_response_parameters'], ['kubo_eigval_max'])
                        self.assertNotIn('postw90.x', files['iron.README.txt'])
                    else:
                        self.assertEqual(values.get('kubo_eigval_max'), '24')
                        self.assertNotIn('pending_response_parameters', record['config'])
                    self.assertEqual(cfg, before)
                    cfg = record['config']

    def test_source_spin_controls_channel_limits_when_json_spin_is_missing_or_stale(self):
        source = SCF.replace('ibrav=0', 'ibrav=0, nspin=2')
        for spin_mode in (None, 'scalar', 'collinear'):
            with self.subTest(spin_mode=spin_mode):
                cfg = config(tasks=['shift_current'], windows=dict(WINDOWS),
                             channels={'down': {'windows': {**WINDOWS, 'dis_froz_max': 18.4551}}},
                             parameters={'fermi_energy': EF, 'kpoint_path': PATH})
                if spin_mode is not None:
                    cfg['spin_mode'] = spin_mode
                before = copy.deepcopy(cfg)
                files = build_bundle(source, cfg)
                for channel in ('up', 'down'):
                    values, _ = _win_parts(files[f'iron_{channel}.win'])
                    self.assertNotIn('kubo_freq_max', values)
                    self.assertNotIn('kubo_eigval_max', values)
                record = json.loads(files['iron.qbox.json'])
                self.assertEqual(record['config']['spin_mode'], 'collinear')
                self.assertEqual(record['config']['pending_response_parameters'],
                                 ['kubo_freq_max', 'kubo_eigval_max'])
                self.assertEqual(cfg, before)

    def test_prepare_retracts_derived_common_limit_after_reading_source_spin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'scf.in'
            original = SCF.replace('ibrav=0', 'ibrav=0, nspin=2')
            source.write_text(original, encoding='utf-8')
            cfg = config(source=str(source), run_root=str(root), tasks=['shift_current'],
                         windows=dict(WINDOWS), source_output_mode='off',
                         channels={'down': {'windows': {**WINDOWS, 'dis_froz_max': 18.4551}}},
                         parameters={'fermi_energy': EF, 'kpoint_path': PATH})
            before = copy.deepcopy(cfg)
            files = prepare(cfg, root)
            for channel in ('up', 'down'):
                values, _ = _win_parts(files[f'iron_{channel}.win'])
                self.assertNotIn('kubo_freq_max', values)
                self.assertNotIn('kubo_eigval_max', values)
            record = json.loads(files['iron.qbox.json'])
            self.assertNotIn('kubo_freq_max', record['config'].get('response_parameter_defaults', {}))
            self.assertNotIn('kubo_eigval_max', record['config'].get('response_parameter_defaults', {}))
            self.assertEqual(record['config']['pending_response_parameters'],
                             ['kubo_freq_max', 'kubo_eigval_max'])
            self.assertEqual(cfg, before)
            self.assertEqual(source.read_text(encoding='utf-8'), original)

    def test_prepare_uses_fermi_imported_by_ensure_output_without_mutating_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'scf.in'
            source.write_text(SCF, encoding='utf-8')
            cfg = config(source=str(source), run_root=str(root), tasks=['shift_current'],
                         windows=dict(WINDOWS), parameters={'kpoint_path': PATH},
                         source_output_mode='off')
            before = copy.deepcopy(cfg)

            def import_fermi(working):
                working['parameters']['fermi_energy'] = EF

            with patch('qbox.io.wannier_output_defaults.ensure_output', side_effect=import_fermi) as ensure:
                files = prepare(cfg, root)
            ensure.assert_called_once()
            values, _ = _win_parts(files['iron.win'])
            record = json.loads(files['iron.qbox.json'])
            self.assertEqual(values.get('kubo_freq_max'), '10')
            self.assertEqual(values.get('kubo_eigval_max'), '20.4551')
            self.assertNotIn('pending_response_parameters', record['config'])
            self.assertFalse(record['config'].get('pending_fermi'))
            self.assertEqual(record['status'], 'inputs_generated')
            self.assertIn('postw90.x iron', files['iron.README.txt'])
            self.assertEqual(source.read_text(encoding='utf-8'), SCF)
            self.assertEqual(cfg, before)
            self.assertEqual(set(root.iterdir()), {source})

    def existing_model(self, root):
        text = WIN.replace('num_bands = 2', 'num_bands = 3')
        text += ('! frozen model energies retain their original spelling\n'
                 'dis_win_min  = -6.1000D0\n'
                 'dis_win_max  =  27.300D0\n'
                 'dis_froz_min =  5.4551D0\n'
                 'dis_froz_max = 20.4551D0 ! original frozen upper\n')
        source = root / 'si.win'
        source.write_text(text, encoding='utf-8')
        return source, text

    def test_existing_minimal_config_reads_frozen_bound_from_original_basis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, original = self.existing_model(root)
            cfg = dict(mode='existing', source=str(source), seed='si', tasks=['shift_current'],
                       parameters={'fermi_energy': EF, 'kpoint_path': PATH})
            before = copy.deepcopy(cfg)
            files = prepare(cfg, root)
            values, _ = _win_parts(files['si.win'])
            record = json.loads(files['si.qbox.json'])
            self.assertEqual(values.get('kubo_freq_max'), '10')
            self.assertEqual(values.get('kubo_eigval_max'), '20.4551')
            self.assertTrue(files['si.win'].startswith(_basis(original)))
            self.assertEqual(values['dis_froz_max'], '20.4551D0')
            self.assertEqual(record['state'], 'inputs_generated')
            self.assertNotIn('pending_response_parameters', record['config'])
            self.assertIn('postw90.x si', files['si.README.txt'])
            self.assertEqual(source.read_text(encoding='utf-8'), original)
            self.assertEqual(cfg, before)
            self.assertEqual(set(root.iterdir()), {source})

    def test_existing_imported_config_derives_limit_and_preserves_model_locks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, original = self.existing_model(root)
            cfg = initial_config(source)
            cfg.update(tasks=['shift_current'], parameters={'fermi_energy': EF, 'kpoint_path': PATH})
            before = copy.deepcopy(cfg)
            files = prepare(cfg, root)
            self.assertEqual(_win_parts(files['si.win'])[0].get('kubo_freq_max'), '10')
            self.assertEqual(_win_parts(files['si.win'])[0].get('kubo_eigval_max'), '20.4551')
            self.assertEqual(cfg, before)
            cfg['windows']['dis_froz_max'] = '21'
            with self.assertRaisesRegex(ValueError, 'windows.*锁定'):
                prepare(cfg, root)
            self.assertEqual(source.read_text(encoding='utf-8'), original)

    def test_existing_native_frozen_max_without_other_window_keys_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'si.win'
            original = WIN.replace('num_bands = 2', 'num_bands = 3') + 'dis_froz_max = 20.4551D0\n'
            source.write_text(original, encoding='utf-8')
            cfg = initial_config(source)
            cfg.update(tasks=['shift_current'], parameters={'fermi_energy': EF, 'kpoint_path': PATH})
            before = copy.deepcopy(cfg)
            files = prepare(cfg, root)
            self.assertEqual(_win_parts(files['si.win'])[0].get('kubo_freq_max'), '10')
            self.assertEqual(_win_parts(files['si.win'])[0].get('kubo_eigval_max'), '20.4551')
            self.assertTrue(files['si.win'].startswith(_basis(original)))
            self.assertEqual(cfg, before)
            self.assertEqual(source.read_text(encoding='utf-8'), original)


if __name__ == '__main__':
    unittest.main()
