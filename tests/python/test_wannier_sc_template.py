"""SC generation follows the reviewed template without inventing energies."""
import json
import unittest

from qbox.io.wannier_inputs import build_bundle, parse_qe
from qbox.io.wannier_profiles import render_profile
from qbox.io.wannier_workflow import _win_parts
from test_wannier_inputs import SCF, config


PARAMETERS = dict(fermi_energy=3.5, kubo_freq_max=8., kubo_eigval_max=12.,
                  kpoint_path=['G 0 0 0 X .5 0 0'])


class ShiftCurrentTemplateTests(unittest.TestCase):
    def bundle(self, **overrides):
        cfg = config(tasks=['shift_current'], parameters=dict(PARAMETERS))
        cfg.update(overrides)
        return build_bundle(SCF, cfg)

    def test_new_sc_model_has_active_localisation_and_disentanglement_controls(self):
        files = self.bundle()
        values, blocks = _win_parts(files['iron.win'])
        for key, expected in {'num_iter':'1000', 'conv_tol':'1e-10', 'conv_window':'5',
                              'dis_num_iter':'1200', 'dis_mix_ratio':'0.5',
                              'dis_conv_tol':'1e-10', 'dis_conv_window':'3',
                              'berry':'true', 'berry_task':'sc', 'sc_phase_conv':'2',
                              'kubo_freq_step':'0.03', 'kubo_smr_type':'gauss',
                              'sc_w_thr':'5', 'bands_plot':'true',
                              'bands_plot_format':'gnuplot'}.items():
            with self.subTest(key=key):
                self.assertEqual(values.get(key), expected)
        self.assertIn('kpoint_path', blocks)
        nscf = parse_qe(files['iron.nscf.in'])
        self.assertTrue(nscf.get('electrons', 'diago_full_acc'))
        self.assertIn('U Fe1-3d 4.0', nscf.text)
        self.assertIn('write_unk = .false.', files['iron.pw2wan'])

    def test_equal_dimension_sc_omits_all_inactive_disentanglement_parameters(self):
        files = self.bundle(nbnd=2, windows=dict(dis_win_min=-20, dis_win_max=20,
                                               dis_froz_min=-20, dis_froz_max=6.5))
        values, _ = _win_parts(files['iron.win'])
        self.assertFalse(any(key.startswith('dis_') for key in values))
        self.assertEqual(values['kubo_eigval_max'], '12')

    def test_manual_iteration_and_response_choices_override_template(self):
        files = self.bundle(num_iter=200, conv_tol=1e-8, conv_window=8,
                            dis_num_iter=250, dis_mix_ratio=.7, dis_conv_tol=1e-7,
                            dis_conv_window=4,
                            parameters={**PARAMETERS, 'sc_phase_conv':1, 'kubo_freq_step':.02})
        values, _ = _win_parts(files['iron.win'])
        for key, expected in {'num_iter':'200', 'conv_tol':'1e-08', 'conv_window':'8',
                              'dis_num_iter':'250', 'dis_mix_ratio':'0.7',
                              'dis_conv_tol':'1e-07', 'dis_conv_window':'4',
                              'sc_phase_conv':'1', 'kubo_freq_step':'0.02'}.items():
            self.assertEqual(values.get(key), expected)

    def test_invalid_model_controls_cannot_silently_fall_back_to_defaults(self):
        for key, value in [('conv_tol',-1), ('conv_tol',True), ('conv_window',1.5),
                           ('conv_window',-2), ('dis_mix_ratio',0), ('dis_mix_ratio',1.1),
                           ('dis_conv_tol',float('nan')), ('dis_conv_window',-1)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.bundle(**{key:value})

    def test_missing_response_energies_are_recorded_without_losing_sc_task(self):
        files = self.bundle(parameters={'kpoint_path':PARAMETERS['kpoint_path']})
        values, _ = _win_parts(files['iron.win'])
        record = json.loads(files['iron.qbox.json'])['config']
        self.assertEqual(record.get('pending_response_parameters'),
                         ['fermi_energy', 'kubo_freq_max', 'kubo_eigval_max'])
        self.assertEqual(values['berry_task'], 'sc')
        for key in record['pending_response_parameters']:
            self.assertNotIn(key, values)

    def test_fermi_alone_does_not_mark_the_sc_response_ready(self):
        files = self.bundle(parameters={'fermi_energy':3.5, 'kpoint_path':PARAMETERS['kpoint_path']})
        record = json.loads(files['iron.qbox.json'])
        self.assertEqual(record['status'], 'pending_response_parameters')
        self.assertEqual(record['config']['pending_response_parameters'],
                         ['kubo_freq_max', 'kubo_eigval_max'])

    def test_frozen_window_cannot_supply_implicit_sc_response_limits(self):
        files = self.bundle(windows=dict(dis_win_min=-5, dis_win_max=20,
                                        dis_froz_min=-2, dis_froz_max=6.5))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['kubo_freq_max'], '8')
        self.assertEqual(values['kubo_eigval_max'], '12')

    def test_standalone_response_requires_both_explicit_energy_limits(self):
        for key in ['kubo_freq_max', 'kubo_eigval_max']:
            params = dict(PARAMETERS); params.pop(key)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                render_profile(['shift_current'], params, 'scalar')

    def test_optical_only_does_not_inherit_sc_template_defaults(self):
        files = build_bundle(SCF, config(tasks=['optical'], parameters={'fermi_energy':3.5}))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['kubo_freq_step'], '0.01')
        self.assertNotIn('conv_window', values)
        self.assertNotIn('bands_plot', values)
