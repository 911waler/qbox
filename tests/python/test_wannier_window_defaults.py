"""Trial energy windows use complete spectra and preserve deliberate edits."""
import copy
import contextlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from test_wannier_outputs import SCF, UPF, fixed_nscf_output


class WindowDefaultsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='qbox windows ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(contextlib.chdir(self.root))
        (self.root / 'pseudo').mkdir()
        (self.root / 'pseudo/Si.UPF').write_text(UPF)
        self.source = self.root / 'nscf.in'
        self.source.write_text(SCF.replace("calculation='scf'", "calculation='nscf'")
                               .replace('nbnd=4', 'nbnd=6')
                               .replace('K_POINTS automatic\n2 2 2 0 0 0',
                                        'K_POINTS crystal\n2\n0 0 0 1\n.5 0 0 1'))
        self.output = self.root / 'nscf.out'
        self.output.write_text(fixed_nscf_output())
        self.config = dict(source=str(self.source), run_root=str(self.root), seed='si',
                           mode='new', tasks=['shift_current'], grid=[2, 1, 1], nbnd=6,
                           num_wann=4, projections=['Si:s;pz'],
                           parameters={'kpoint_path': ['G 0 0 0 X .5 0 0']})
        self.refresh_record()

    def refresh_record(self):
        from qbox.io.wannier_outputs import read_output
        from qbox.io.wannier_qe_reuse import inspect_qe
        self.config['qe_progress'] = inspect_qe(self.config)
        self.config['qe_output'] = read_output(self.output, self.source, run_root=self.root)

    def collinear_spectrum(self):
        """Two complete spin channels share k points but have different energies."""
        self.source.write_text(self.source.read_text().replace('ibrav=0', 'nspin=2, ibrav=0'))
        text = fixed_nscf_output().replace('number of k points= 2', 'number of k points= 4')
        points = ('k(1) = (0.0 0.0 0.0), wk = 1.0\n'
                  'k(2) = (0.5 0.0 0.0), wk = 1.0')
        text = text.replace(points, points + '\nk(3) = (0.0 0.0 0.0), wk = 1.0\n'
                            'k(4) = (0.5 0.0 0.0), wk = 1.0')
        start = text.index('k = 0 0 0 (30 PWs) bands (ev):')
        stop = text.index('highest occupied, lowest unoccupied level', start)
        up = text[start:stop]
        down = up.replace('-5.0 -3.0 -1.0 0.0 3.0 7.0', '-8.0 -6.0 -2.0 2.0 6.0 12.0')
        down = down.replace('-4.0 -2.0 0.0 1.0 4.0 8.0', '-7.0 -5.0 -1.0 3.0 7.0 13.0')
        self.output.write_text(text[:start] + '------ SPIN UP ------------\n' + up
                               + '------ SPIN DOWN ------------\n' + down + text[stop:])
        self.config['spin_mode'] = 'collinear'
        self.config['parameters']['fermi_energy'] = 2.
        self.refresh_record()

    def api(self):
        return importlib.import_module('qbox.io.wannier_window_defaults')

    def test_full_spectrum_supplies_editable_absolute_initial_windows(self):
        self.api().initialize_window_defaults(self.config)
        windows = self.config['windows']
        self.assertEqual(windows, dict(reference='absolute', fermi_energy=2.,
                                      dis_win_min=-5.1, dis_win_max=8.1,
                                      dis_froz_min=-3., dis_froz_max=6.999))
        self.assertEqual(self.config['window_defaults']['source'], str(self.output))
        self.assertEqual(self.config['window_defaults']['values'], windows)
        self.assertNotIn('fermi_energy', self.config['parameters'])
        self.assertIn('收窄', self.config['window_defaults']['adjustment_note'])

    def test_user_preset_is_reference_minus_five_plus_ten_when_capacity_allows(self):
        self.output.write_text(fixed_nscf_output()
                              .replace('-5.0 -3.0 -1.0 0.0 3.0 7.0', '-20.0 -10.0 -4.0 0.0 9.0 20.0')
                              .replace('-4.0 -2.0 0.0 1.0 4.0 8.0', '-18.0 -8.0 -3.0 1.0 8.0 22.0'))
        self.refresh_record()
        self.config['parameters']['fermi_energy'] = 0.
        self.api().initialize_window_defaults(self.config)
        windows = self.config['windows']
        self.assertEqual((windows['dis_froz_min'], windows['dis_froz_max']), (-5., 10.))
        self.assertNotIn('adjustment_note', self.config['window_defaults'])

    def test_homo_alone_does_not_masquerade_as_fermi_reference(self):
        self.config['qe_output'].update(fermi_energy=None, gap_reference=None, homo=1.)
        self.api().initialize_window_defaults(self.config)
        self.assertIn('dis_win_min', self.config['windows'])
        self.assertNotIn('dis_froz_min', self.config['windows'])
        self.assertNotIn('dis_froz_max', self.config['windows'])

    def test_degeneracy_at_requested_lower_bound_does_not_create_invalid_frozen_window(self):
        self.output.write_text(fixed_nscf_output()
                              .replace('-5.0 -3.0 -1.0 0.0 3.0 7.0', '-5.0 -3.0 0.0 0.0 0.0 7.0')
                              .replace('-4.0 -2.0 0.0 1.0 4.0 8.0', '-4.0 -2.0 0.0 0.0 0.0 8.0'))
        self.refresh_record()
        self.config.update(num_wann=2, parameters={'fermi_energy': 5.})
        self.api().initialize_window_defaults(self.config)
        self.assertNotIn('dis_froz_min', self.config['windows'])
        self.assertNotIn('dis_froz_max', self.config['windows'])
        self.assertIn('未设置', self.config['window_defaults']['adjustment_note'])

    def test_reference_outside_spectrum_does_not_create_reversed_bounds(self):
        self.config['parameters']['fermi_energy'] = 30.
        self.api().initialize_window_defaults(self.config)
        self.assertNotIn('dis_froz_min', self.config['windows'])
        self.assertNotIn('dis_froz_max', self.config['windows'])
        self.assertIn('未设置', self.config['window_defaults']['adjustment_note'])

    def test_complete_collinear_spectrum_supplies_windows_covering_both_spins(self):
        self.collinear_spectrum()
        self.assertTrue(self.config['qe_progress']['nscf']['completed'])
        self.api().initialize_window_defaults(self.config)
        windows = self.config['windows']
        self.assertEqual((windows['dis_win_min'], windows['dis_win_max']), (-8.1, 13.1))
        self.assertEqual((windows['dis_froz_min'], windows['dis_froz_max']), (-3., 6.999))

    def test_collinear_shared_windows_respect_channel_dimensions_and_exclusions(self):
        self.collinear_spectrum()
        self.config['parameters']['fermi_energy'] = 5.
        self.config['channels'] = {'down': {'num_wann': 2, 'exclude_bands': '1'}}
        self.api().initialize_window_defaults(self.config)
        windows = self.config['windows']
        self.assertEqual((windows['dis_win_min'], windows['dis_win_max']), (-6.1, 13.1))
        self.assertEqual(windows['dis_froz_min'], 0.)
        self.assertAlmostEqual(windows['dis_froz_max'], 11.999)
        retained = ((4, (-5., -3., -1., 0., 3., 7.)),
                    (4, (-4., -2., 0., 1., 4., 8.)),
                    (2, (-6., -2., 2., 6., 12.)),
                    (2, (-5., -1., 3., 7., 13.)))
        for dimension, row in retained:
            self.assertLessEqual(sum(windows['dis_froz_min'] <= energy <= windows['dis_froz_max']
                                     for energy in row), dimension)
            self.assertGreaterEqual(sum(windows['dis_win_min'] <= energy <= windows['dis_win_max']
                                        for energy in row), dimension)

    def test_manual_channel_window_survives_shared_window_refresh(self):
        self.collinear_spectrum()
        manual = dict(reference='absolute', dis_win_min=-9., dis_win_max=14.,
                      dis_froz_min=-9., dis_froz_max=-2.5)
        self.config['channels'] = {'down': {'num_wann': 2, 'windows': copy.deepcopy(manual)}}
        self.api().initialize_window_defaults(self.config)
        self.assertEqual(self.config['channels']['down']['windows'], manual)
        self.assertEqual(self.config['windows']['dis_win_min'], -5.1)
        self.assertEqual(self.config['windows']['dis_win_max'], 8.1)
        self.config['num_wann'] = 2
        self.api().initialize_window_defaults(self.config)
        self.assertEqual(self.config['channels']['down']['windows'], manual)
        self.assertAlmostEqual(self.config['windows']['dis_froz_max'], -.001)

    def test_equal_dimension_channel_extrema_remain_in_shared_outer_window(self):
        self.collinear_spectrum()
        self.config['parameters']['fermi_energy'] = 5.
        self.config['channels'] = {'down': {'num_wann': 6}}
        self.api().initialize_window_defaults(self.config)
        windows = self.config['windows']
        self.assertEqual((windows['dis_win_min'], windows['dis_win_max']), (-8.1, 13.1))
        self.assertEqual((windows['dis_froz_min'], windows['dis_froz_max']), (0., 13.1))

    def test_prepare_generates_windows_without_opening_menu(self):
        from qbox.io.wannier_workflow import prepare, _win_parts
        files = prepare(self.config, self.root)
        values, _ = _win_parts(files['si.win'])
        for key, expected in dict(dis_win_min=-5.1, dis_win_max=8.1,
                                  dis_froz_min=-3., dis_froz_max=6.999).items():
            self.assertAlmostEqual(float(values[key]), expected)
        self.assertEqual(values['berry_task'], 'sc')
        self.assertNotIn('si.nscf.in', files)
        saved = json.loads(files['si.qbox.json'])['config']
        self.assertEqual(saved['window_defaults']['values']['dis_froz_max'], 6.999)
        self.assertNotIn('windows', self.config)

    def test_frozen_count_never_exceeds_model_dimension_even_with_manual_reference(self):
        self.config.update(num_wann=2, parameters={'fermi_energy': 5.})
        self.api().initialize_window_defaults(self.config)
        windows = self.config['windows']
        self.assertEqual(windows['dis_froz_min'], 0.)
        self.assertAlmostEqual(windows['dis_froz_max'], 3.999)
        for row in ((-5., -3., -1., 0., 3., 7.), (-4., -2., 0., 1., 4., 8.)):
            self.assertLessEqual(sum(windows['dis_froz_min'] <= e <= windows['dis_froz_max']
                                     for e in row), 2)

    def test_excluded_bands_and_relative_reference_are_applied_before_counting(self):
        self.config.update(num_wann=2, exclude_bands='1-2',
                           windows={'reference': 'fermi', 'fermi_energy': 2.})
        self.api().initialize_window_defaults(self.config)
        windows = self.config['windows']
        self.assertAlmostEqual(windows['dis_win_min'], -3.1)
        self.assertAlmostEqual(windows['dis_win_max'], 6.1)
        self.assertAlmostEqual(windows['dis_froz_max'], .999)
        from qbox.io.wannier_inputs import _windows
        self.assertAlmostEqual(_windows(self.config)['dis_froz_max'], 2.999)

    def test_manual_bounds_and_explicit_clear_survive_refresh(self):
        manual = dict(reference='absolute', dis_win_min=-9., dis_win_max=9.)
        self.config['windows'] = copy.deepcopy(manual)
        self.api().initialize_window_defaults(self.config)
        self.assertEqual(self.config['windows'], manual)
        self.config.pop('windows')
        self.api().initialize_window_defaults(self.config)
        self.api().mark_windows_manual(self.config)
        self.config['windows'] = {'reference': 'absolute'}
        from qbox.io.wannier_output_defaults import apply_output
        apply_output(self.config, self.config['qe_output'])
        self.api().initialize_window_defaults(self.config)
        self.assertEqual(self.config['windows'], {'reference': 'absolute'})

    def test_config_edits_without_gui_are_not_reset(self):
        self.api().initialize_window_defaults(self.config)
        self.config['windows']['dis_win_max'] = 6.
        before = copy.deepcopy(self.config['windows'])
        self.api().initialize_window_defaults(self.config)
        self.assertEqual(self.config['windows'], before)

    def test_manual_reference_alias_is_preserved(self):
        self.config['windows'] = {'reference': 'fermi', 'reference_energy': 10.}
        from qbox.io.wannier_output_defaults import ensure_output
        ensure_output(self.config)
        self.assertNotIn('fermi_energy', self.config['windows'])
        self.assertAlmostEqual(self.config['windows']['dis_win_min'], -15.1)
        from qbox.io.wannier_inputs import _windows
        self.assertAlmostEqual(_windows(self.config)['dis_win_min'], -5.1)

    def test_accepting_same_automatic_fermi_as_manual_preserves_it_on_refresh(self):
        from qbox.io.wannier_output_defaults import mark_manual, apply_output
        self.config['windows'] = {'reference': 'fermi'}
        self.api().initialize_window_defaults(self.config)
        mark_manual(self.config, 'windows.fermi_energy')
        apply_output(self.config, self.config['qe_output'])
        self.assertEqual(self.config['windows']['fermi_energy'], 2.)
        from qbox.io.wannier_inputs import _windows
        self.assertAlmostEqual(_windows(self.config)['dis_win_min'], -5.1)

    def test_new_output_and_new_dimensions_refresh_only_initial_values(self):
        self.api().initialize_window_defaults(self.config)
        self.config['num_wann'] = 2
        self.api().initialize_window_defaults(self.config)
        self.assertAlmostEqual(self.config['windows']['dis_froz_max'], -.001)
        self.config['num_wann'] = 4
        self.output.write_text(fixed_nscf_output().replace('4.0 8.0', '4.0 9.0'))
        self.refresh_record()
        self.api().initialize_window_defaults(self.config)
        self.assertEqual(self.config['windows']['dis_win_max'], 9.1)

    def test_incomplete_or_changed_spectrum_does_not_supply_bounds(self):
        for change in ('scf', 'incomplete', 'changed', 'grid'):
            with self.subTest(change=change):
                config = copy.deepcopy(self.config)
                if change == 'scf':
                    config['qe_output']['kind'] = 'scf'
                elif change == 'incomplete':
                    config['qe_progress']['nscf']['completed'] = False
                elif change == 'grid':
                    config['grid'] = [4, 1, 1]
                else:
                    config['qe_output']['sha256'] = 'changed'
                self.api().initialize_window_defaults(config)
                self.assertNotIn('dis_win_max', config.get('windows', {}))

    def test_equal_dimension_existing_mode_and_disabled_import_keep_native_windows(self):
        for update in ({'num_wann': 6}, {'mode': 'existing'}, {'source_output_mode': 'off'}):
            with self.subTest(update=update):
                config = {**copy.deepcopy(self.config), **update}
                self.api().initialize_window_defaults(config)
                self.assertNotIn('dis_win_max', config.get('windows', {}))

    def test_removing_import_discards_only_automatic_defaults(self):
        self.api().initialize_window_defaults(self.config)
        from qbox.io.wannier_output_defaults import clear_output
        clear_output(self.config, disable=True)
        self.assertNotIn('dis_win_max', self.config.get('windows', {}))
        self.assertNotIn('window_defaults', self.config)


if __name__ == '__main__':
    unittest.main()
