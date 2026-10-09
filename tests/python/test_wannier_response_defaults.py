"""Response limits follow frozen windows without overriding research choices."""
import copy
import unittest

from qbox.io.wannier_output_defaults import apply_output, clear_output, mark_manual


def config():
    return dict(mode='new', tasks=['shift_current'], spin_mode='scalar',
                parameters={'fermi_energy': 10.4551},
                windows=dict(reference='absolute', dis_win_min=-6.1, dis_win_max=27.3,
                             dis_froz_min=5.4551, dis_froz_max=20.4551))


class ResponseDefaultsTests(unittest.TestCase):
    def refresh(self, cfg):
        from qbox.io.wannier_response_defaults import refresh_response_defaults
        refresh_response_defaults(cfg)

    def test_absolute_and_relative_windows_give_same_photon_limit(self):
        for relative in (False, True):
            cfg = config()
            if relative:
                cfg['windows'].update(reference='fermi', fermi_energy=10.4551)
                for key in ('dis_win_min', 'dis_win_max', 'dis_froz_min', 'dis_froz_max'):
                    cfg['windows'][key] -= 10.4551
            before = copy.deepcopy(cfg['windows'])
            self.refresh(cfg)
            self.assertEqual(cfg['parameters']['kubo_freq_max'], 10.)
            self.assertAlmostEqual(cfg['parameters'].get('kubo_eigval_max', 0), 20.4551)
            self.assertEqual(cfg['windows'], before)
            self.assertEqual(cfg['response_parameter_defaults']['kubo_freq_max']['value'], 10.)

    def test_reference_is_actual_occupation_energy_not_coordinate_offset(self):
        cfg = config()
        cfg['windows'].update(reference='fermi', fermi_energy=10.)
        cfg['windows']['dis_froz_max'] = 10.
        cfg['parameters']['fermi_energy'] = 11.
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 9.)
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 20.)

    def test_follow_window_reference_and_task_changes(self):
        cfg = config()
        self.refresh(cfg)
        cfg['windows']['dis_froz_max'] += 2.
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 12.)
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 22.4551)
        cfg['parameters']['fermi_energy'] += 1.
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 11.)
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 22.4551)
        cfg['tasks'] = ['bands']
        self.refresh(cfg)
        self.assertNotIn('kubo_freq_max', cfg['parameters'])
        self.assertNotIn('kubo_eigval_max', cfg['parameters'])
        cfg['tasks'] = ['shift_current']
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 11.)
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 22.4551)

    def test_clearing_dependency_retracts_auto_value_without_locking_future_defaults(self):
        cfg = config()
        self.refresh(cfg)
        cfg['windows'].pop('dis_froz_max')
        self.refresh(cfg)
        self.assertNotIn('kubo_freq_max', cfg['parameters'])
        self.assertNotIn('kubo_eigval_max', cfg['parameters'])
        cfg['windows']['dis_froz_max'] = 20.4551
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 10.)
        cfg['parameters'].pop('fermi_energy')
        self.refresh(cfg)
        self.assertNotIn('kubo_freq_max', cfg['parameters'])
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 20.4551)

    def test_manual_same_value_clear_and_json_changes_survive_refresh(self):
        for change in ('same', 'clear', 'json_edit', 'json_delete'):
            with self.subTest(change=change):
                cfg = config()
                self.refresh(cfg)
                if change in ('same', 'clear'):
                    mark_manual(cfg, 'kubo_freq_max')
                if change in ('clear', 'json_delete'):
                    cfg['parameters'].pop('kubo_freq_max')
                elif change == 'json_edit':
                    cfg['parameters']['kubo_freq_max'] = 8.
                cfg['windows']['dis_froz_max'] += 2.
                self.refresh(cfg)
                self.refresh(cfg)
                expected = {'same': 10., 'json_edit': 8.}.get(change)
                self.assertEqual(cfg['parameters'].get('kubo_freq_max'), expected)
                self.assertNotIn('kubo_freq_max', cfg.get('response_parameter_defaults', {}))

    def test_untracked_manual_values_are_preserved(self):
        cfg = config()
        cfg['parameters']['kubo_freq_max'] = 6.
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 6.)
        self.assertNotIn('kubo_freq_max', cfg.get('response_parameter_defaults', {}))
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 20.4551)

    def test_invalid_or_nonpositive_derived_ranges_are_not_filled(self):
        cases = [dict(fermi_energy=None), dict(fermi_energy=float('nan')),
                 dict(fermi_energy=float('inf')), dict(fermi_energy=20.4551),
                 dict(fermi_energy=21.), dict(kubo_freq_min=10.),
                 dict(kubo_freq_min=11.)]
        for values in cases:
            with self.subTest(values=values):
                cfg = config()
                cfg['parameters'].update(values)
                self.refresh(cfg)
                self.assertNotIn('kubo_freq_max', cfg['parameters'])

    def test_only_optical_shift_current_and_frequency_shc_use_default(self):
        for task, scan, expected in [('optical', False, 10.), ('shift_current', False, 10.),
                                      ('shc', False, None), ('shc', True, 10.),
                                      ('ahc', True, None), ('gyrotropic', True, None)]:
            cfg = config()
            cfg['tasks'] = [task]
            cfg['parameters']['shc_freq_scan'] = scan
            self.refresh(cfg)
            self.assertEqual(cfg['parameters'].get('kubo_freq_max'), expected)
            self.assertEqual(cfg['parameters'].get('kubo_eigval_max'),
                             20.4551 if task in ('optical', 'shift_current', 'shc') else None)

    def test_spin_channel_windows_must_agree_before_assigning_shared_default(self):
        cfg = config()
        cfg.update(spin_mode='collinear', channels={'up': {}, 'down': {}})
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 10.)
        cfg['channels']['down']['windows'] = {**cfg['windows'], 'dis_froz_max': 19.4551}
        self.refresh(cfg)
        self.assertNotIn('kubo_freq_max', cfg['parameters'])
        self.assertNotIn('kubo_eigval_max', cfg['parameters'])
        cfg['channels']['up']['windows'] = copy.deepcopy(cfg['channels']['down']['windows'])
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 9.)
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 19.4551)

    def test_output_reselection_updates_reference_and_retracts_only_automatic_values(self):
        cfg = config()
        cfg['parameters'].pop('fermi_energy')
        record = dict(path='/work/scf.out', sha256='digest', kind='scf', fermi_energy=10.4551)
        apply_output(cfg, record)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 10.)
        apply_output(cfg, {**record, 'fermi_energy': 11.4551})
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 9.)
        clear_output(cfg, disable=True)
        self.assertNotIn('kubo_freq_max', cfg['parameters'])
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), 20.4551)
        self.assertNotIn('kubo_freq_max', cfg.get('output_manual_fields', []))
        apply_output(cfg, record)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 10.)
        mark_manual(cfg, 'kubo_freq_max')
        clear_output(cfg, disable=True)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 10.)

    def test_eigenvalue_default_does_not_require_fermi_or_positive_absolute_energy(self):
        for upper in (20.4551, 0., -2.):
            cfg = config()
            cfg['parameters'].clear()
            cfg['windows'] = dict(dis_froz_max=upper)
            self.refresh(cfg)
            self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), upper)
            self.assertNotIn('kubo_freq_max', cfg['parameters'])
        cfg['windows'] = dict(reference='fermi', reference_energy=-4., dis_froz_max=2.)
        self.refresh(cfg)
        self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), -2.)
        cfg['windows'].pop('reference_energy')
        self.refresh(cfg)
        self.assertNotIn('kubo_eigval_max', cfg['parameters'])

    def test_manual_eigenvalue_value_and_clear_do_not_stop_photon_refresh(self):
        for change, expected in [('same', 20.4551), ('edit', 24.), ('clear', None),
                                 ('json_edit', 24.), ('json_delete', None)]:
            with self.subTest(change=change):
                cfg = config()
                self.refresh(cfg)
                if change in ('same', 'edit', 'clear'):
                    mark_manual(cfg, 'kubo_eigval_max')
                if change in ('clear', 'json_delete'):
                    cfg['parameters'].pop('kubo_eigval_max', None)
                elif change in ('edit', 'json_edit'):
                    cfg['parameters']['kubo_eigval_max'] = 24.
                cfg['windows']['dis_froz_max'] = 22.4551
                self.refresh(cfg)
                self.refresh(cfg)
                self.assertEqual(cfg['parameters'].get('kubo_eigval_max'), expected)
                self.assertEqual(cfg['parameters']['kubo_freq_max'], 12.)
                self.assertNotIn('kubo_eigval_max', cfg.get('response_parameter_defaults', {}))

    def test_manual_eigenvalue_before_first_refresh_does_not_stop_photon_default(self):
        cfg = config()
        cfg['parameters']['kubo_eigval_max'] = 24.
        self.refresh(cfg)
        self.assertEqual(cfg['parameters']['kubo_eigval_max'], 24.)
        self.assertEqual(cfg['parameters']['kubo_freq_max'], 10.)
        self.assertNotIn('kubo_eigval_max', cfg['response_parameter_defaults'])

    def test_missing_or_invalid_frozen_bound_does_not_invent_a_cutoff(self):
        for windows in ({}, {'dis_win_max': 27.3}, {'dis_froz_max': float('nan')},
                        {'dis_froz_max': float('inf')}, {'dis_froz_max': True},
                        {'reference': 'fermi', 'dis_froz_max': 10.}):
            cfg = config()
            self.refresh(cfg)
            cfg['windows'] = windows
            self.refresh(cfg)
            self.assertNotIn('kubo_eigval_max', cfg['parameters'])
            self.assertNotIn('kubo_freq_max', cfg['parameters'])

    def test_json_boolean_edit_is_preserved_for_normal_numeric_validation(self):
        from qbox.io.wannier_profiles import render_profile
        for key, upper, reference, value in [('kubo_eigval_max', 0., -10., False),
                                            ('kubo_freq_max', 10., 9., True)]:
            cfg = config()
            cfg['parameters']['kpoint_path'] = ['G 0 0 0 X .5 0 0']
            cfg['windows'] = dict(dis_froz_max=upper)
            cfg['parameters']['fermi_energy'] = reference
            self.refresh(cfg)
            cfg['parameters'][key] = value
            cfg['windows']['dis_froz_max'] += 2.
            self.refresh(cfg)
            self.assertIs(cfg['parameters'][key], value)
            with self.assertRaisesRegex(ValueError, 'numeric.*boolean'):
                render_profile(cfg['tasks'], cfg['parameters'], 'scalar', '3.1.0')


if __name__ == '__main__':
    unittest.main()
