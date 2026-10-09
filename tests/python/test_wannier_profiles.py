"""The generated task inputs must select real 3.1.0 functionality safely."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from qbox.io.wannier_profiles import render_profile, fields_for_tasks, DIRECTIONS, TASKS, FIELDS

PATH = ['G 0 0 0 X 0.5 0 0']
PARAMS = dict(fermi_energy=4.2, kpoint_path=PATH, dos_energy_min=-5,
              dos_energy_max=8, dos_project=[1, 2], wannier_plot_list=[1],
              boltz_mu_min=4, boltz_mu_max=5, boltz_temp_min=100,
              boltz_temp_max=500, boltz_relax_time=10,
              kubo_freq_max=5, kubo_eigval_max=12,
              gyrotropic_freq_max=5, kslice_corner=[0, 0, 0],
              kslice_b1=[1, 0, 0], kslice_b2=[0, 1, 0])

class ProfileTests(unittest.TestCase):
    def test_pending_occupation_reference_preserves_selected_response_tasks(self):
        for tasks, expected in ((['shift_current'], 'sc'),
                                (['optical', 'shift_current'], 'kubo sc')):
            with self.subTest(tasks=tasks):
                profile = render_profile(tasks, {'kpoint_path':PATH}, 'scalar', defer_fermi=True,
                                         defer_response=('kubo_freq_max','kubo_eigval_max'))
                self.assertIn('berry = true', profile.win_lines)
                self.assertIn('berry_task = ' + expected, profile.win_lines)
                self.assertFalse(any(line.startswith('fermi_energy =') for line in profile.win_lines))
                self.assertTrue(any('pending' in line for line in profile.win_lines))

    def test_every_subtask_selects_actual_functionality(self):
        cases = {'bands':'bands_plot = true', 'qe_bands':'bands_plot = true',
                 'dos':'dos = true', 'projected_dos':'dos_project = 1 2',
                 'fermi_surface':'fermi_surface_plot = true',
                 'orbitals':'wannier_plot = true', 'centres':'write_xyz = true',
                 'model':'write_hr = true', 'boltzmann':'boltzwann = true',
                 'berry_path':'kpath_task = curv', 'berry_slice':'kslice_task = curv',
                 'ahc':'berry_task = ahc', 'shc':'berry_task = shc',
                 'optical':'berry_task = kubo', 'shift_current':'berry_task = sc',
                 'orbital_magnetization':'berry_task = morb',
                 'natural_optical_activity':'gyrotropic_task = -noa',
                 'current_induced_optical':'gyrotropic_task = -dw-c',
                 'current_induced_magnetization':'gyrotropic_task = -k-c'}
        for task, expected in cases.items():
            with self.subTest(task=task):
                self.assertIn(expected, render_profile([task], PARAMS, 'spinor').win_lines)

    def test_multi_tasks_union_operators_without_uiu(self):
        result = render_profile(['shc', 'orbitals', 'orbital_magnetization'], PARAMS, 'spinor')
        self.assertEqual(result.pw2_flags, {'write_amn':True, 'write_mmn':True,
                         'write_unk':True, 'write_spn':True, 'write_uHu':True})
        self.assertIn('berry_task = shc morb', result.win_lines)

    def test_spin_occupation_counts_are_not_inferred_from_soc(self):
        for mode, count in [('scalar',2), ('collinear',1), ('up',1), ('down',1), ('spinor',1)]:
            self.assertIn(f'num_elec_per_state = {count}', render_profile(['dos'], PARAMS, mode).win_lines)

    def test_spin_matrix_tasks_require_spinor_source(self):
        for task, extra in [('shc',{}), ('natural_optical_activity',{'include_spin':True}),
                            ('current_induced_magnetization',{'include_spin':True})]:
            with self.subTest(task=task), self.assertRaisesRegex(ValueError, 'spinor'):
                render_profile([task], {**PARAMS, **extra}, 'collinear')

    def test_spin_gyrotropic_and_orbital_dependencies(self):
        noa = render_profile(['natural_optical_activity'], {**PARAMS,'include_spin':True}, 'spinor')
        self.assertIn('gyrotropic_task = -noa-spin', noa.win_lines)
        self.assertTrue(noa.pw2_flags['write_spn'])
        self.assertNotIn('write_uHu', noa.pw2_flags)
        k = render_profile(['current_induced_magnetization'], {**PARAMS,'include_spin':True}, 'spinor')
        self.assertIn('gyrotropic_task = -k-spin-c', k.win_lines)
        self.assertTrue(k.pw2_flags['write_uHu'])

    def test_unknown_version_task_and_keywords_are_rejected(self):
        for options in [dict(version='latest'), dict(tasks=['wrong']),
                        dict(parameters={'shc_method':'qiao'}),
                        dict(parameters={'sc_use_eta_corr':True}),
                        dict(parameters={'explicit_kpath':True})]:
            args = dict(tasks=['centres'], parameters={}, spin_mode='scalar')
            args.update(options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                render_profile(**args)

    def test_invalid_numeric_and_geometric_parameters_rejected(self):
        cases = [('ahc', {'fermi_energy':float('nan')}),
                 ('ahc', {'berry_kmesh':[1,0,2]}),
                 ('dos', {'dos_energy_min':10}),
                 ('dos', {'dos_energy_step':0}),
                 ('boltzmann', {'boltz_temp_min':0}),
                 ('boltzmann', {'boltz_relax_time':-1}),
                 ('optical', {'kubo_freq_min':6}),
                 ('optical', {'kubo_freq_step':0}),
                 ('shift_current', {'sc_phase_conv':3}),
                 ('shift_current', {'sc_eta':0}),
                 ('shc', {'shc_alpha':4}),
                 ('berry_slice', {'kslice_b2':[2,0,0]}),
                 ('projected_dos', {'dos_project':[0]}),
                 ('orbitals', {'wannier_plot_format':'png'})]
        for task, bad in cases:
            with self.subTest(task=task,bad=bad), self.assertRaises(ValueError):
                render_profile([task], {**PARAMS, **bad}, 'spinor')

    def test_required_unknown_physical_values_not_fabricated(self):
        for task, key in [('ahc','fermi_energy'),('dos','dos_energy_min'),
                          ('boltzmann','boltz_relax_time'),('optical','fermi_energy'),
                          ('shift_current','fermi_energy'),('bands','kpoint_path')]:
            values = PARAMS.copy(); values.pop(key)
            with self.subTest(task=task), self.assertRaisesRegex(ValueError,key):
                render_profile([task],values,'scalar')

    def test_response_energy_limits_can_use_native_defaults(self):
        for task in ('optical', 'shc'):
            with self.subTest(task=task):
                profile = render_profile([task], {'fermi_energy': 4.2}, 'spinor')
                self.assertFalse(any(line.startswith(('kubo_freq_max', 'kubo_eigval_max'))
                                     for line in profile.win_lines))
                self.assertIn('fermi_energy = 4.2', profile.win_lines)

    def test_sc_explicit_smearing_and_threshold_override_template_defaults(self):
        profile = render_profile(['shift_current'], {**PARAMS,
            'kubo_adpt_smr': True, 'kubo_adpt_smr_fac': 1.2,
            'kubo_adpt_smr_max': .6, 'kubo_smr_type':'cold', 'sc_w_thr':8}, 'scalar')
        for line in ('kubo_adpt_smr = true', 'kubo_adpt_smr_fac = 1.2',
                     'kubo_adpt_smr_max = 0.6', 'kubo_smr_type = cold', 'sc_w_thr = 8'):
            self.assertIn(line, profile.win_lines)

    def test_nonzero_frequency_minimum_requires_an_explicit_maximum(self):
        with self.assertRaisesRegex(ValueError, 'kubo_freq_max'):
            render_profile(['optical'], {'fermi_energy': 4.2, 'kubo_freq_min': 3.}, 'scalar')
        profile = render_profile(['optical'], {'fermi_energy': 4.2, 'kubo_freq_min': 3.,
                                               'kubo_freq_max': 5.}, 'scalar')
        self.assertIn('kubo_freq_max = 5', profile.win_lines)

    def test_spinor_plot_explains_amplitude_and_all_metadata_covers_tasks(self):
        profile = render_profile(['orbitals'], PARAMS,'spinor')
        self.assertIn('wannier_plot_spinor_mode = total', profile.win_lines)
        self.assertTrue(any('spinor' in warning for warning in profile.warnings))
        self.assertEqual(len(DIRECTIONS),6)
        self.assertEqual(set(TASKS), {task for direction in DIRECTIONS for task in direction['tasks']})
        for field in FIELDS.values():
            self.assertTrue({'label','type','unit','required','default','tasks'} <= field.keys())

    def test_xsf_uses_native_xcrysden_keyword(self):
        result = render_profile(['orbitals'], {**PARAMS,'wannier_plot_format':'xsf'},'scalar')
        self.assertIn('wannier_plot_format = xcrysden', result.win_lines)

    def test_cube_radius_is_adjustable_without_inflating_supercell(self):
        default = render_profile(['orbitals'], PARAMS, 'scalar')
        self.assertIn('wannier_plot_radius = 3.5', default.win_lines)
        self.assertIn('wannier_plot_supercell = 2 2 2', default.win_lines)
        smaller = render_profile(['orbitals'], {**PARAMS, 'wannier_plot_radius': 1.2}, 'scalar')
        self.assertIn('wannier_plot_radius = 1.2', smaller.win_lines)
        self.assertEqual(fields_for_tasks(['orbitals'])['wannier_plot_radius']['unit'], 'Å')
        self.assertNotIn('wannier_plot_radius', fields_for_tasks(['dos']))
        for radius in (0, -1, float('nan'), float('inf'), True):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                render_profile(['orbitals'], {**PARAMS, 'wannier_plot_radius': radius}, 'scalar')

    def test_cube_reports_runtime_coverage_limit_and_available_remedies(self):
        result = render_profile(['orbitals'], PARAMS, 'scalar')
        warning = next((warning for warning in result.warnings if 'FFT' in warning), '')
        for detail in ('cube', 'final Wannier centres', 'cannot be guaranteed',
                       'wannier_plot_supercell', 'wannier_plot_radius', 'xsf'):
            self.assertIn(detail, warning)
        xsf = render_profile(['orbitals'], {**PARAMS, 'wannier_plot_format': 'xsf'}, 'scalar')
        self.assertFalse(any('FFT' in warning for warning in xsf.warnings))

    def test_boltzmann_identifies_thermal_coefficient_before_open_circuit_correction(self):
        result = render_profile(['boltzmann'], PARAMS, 'scalar')
        warning = next(warning for warning in result.warnings if 'BoltzWann' in warning)
        for detail in ('Seebeck S', 'conductivity σ', 'coefficient K', 'kappa.dat',
                       'κ_e = K − T Sᵀ σ S', 'open-circuit', 'lattice'):
            self.assertIn(detail, warning)

if __name__ == '__main__': unittest.main()
