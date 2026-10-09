from pathlib import Path
import re
import tempfile
import unittest


WIN = '''num_bands = 2
num_wann = 2
mp_grid = 1 1 1
spinors = false
begin unit_cell_cart
angstrom
3 0 0
0 3 0
0 0 3
end unit_cell_cart
begin atoms_frac
Si 0 0 0
end atoms_frac
begin projections
Si:s;pz
end projections
begin kpoints
0 0 0
end kpoints
berry = true
berry_task = ahc
berry_kmesh = 10
fermi_energy = 0
'''


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        from qbox.io import wannier_workflow
        self.api = wannier_workflow
        self.tmp = tempfile.TemporaryDirectory(prefix='qbox existing 中文 ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'si.win'
        self.source.write_text(WIN)

    def test_cif_starts_as_pending_structure_without_qe_parsing_or_writes(self):
        source = self.root / 'relax structure.CIF'
        source.write_text('data_structure\n_cell_length_a 3.0\n')
        before = set(self.root.iterdir())
        config = self.api.initial_config(source)
        self.assertEqual(config['structure_source'], str(source))
        self.assertEqual(config['source'], '')
        self.assertEqual(config['mode'], 'new')
        self.assertEqual(config['seed'], 'relax_structure')
        self.assertIsNone(config['nbnd'])
        self.assertEqual(set(self.root.iterdir()), before)
        with self.assertRaisesRegex(ValueError, 'CIF.*SCF'):
            self.api.prepare(config, self.root)

    def test_json_cif_source_requests_interactive_scf_configuration(self):
        source = self.root / 'relax.cif'
        source.write_text('data_structure\n')
        with self.assertRaisesRegex(ValueError, 'CIF.*SCF'):
            self.api.prepare({'source': str(source)}, self.root)

    def test_switching_profiles_keeps_basis_and_removes_previous_task(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['model'], parameters={})
        bundle = self.api.prepare(config, self.root)
        win = bundle['si.win']
        self.assertNotIn('berry_task', win)
        self.assertNotIn('berry_kmesh', win)
        self.assertIn('write_hr', win)
        self.assertIn('Si:s;pz', win)
        self.assertIn('num_bands = 2', win)
        self.assertEqual(self.source.read_text(), WIN)
        self.assertEqual(set(bundle), {'si.win', 'si.qbox.json', 'si.README.txt'})
        self.assertIn('chk', bundle['si.README.txt'])
        self.assertIn('未验证', bundle['si.README.txt'])

    def test_existing_model_cannot_be_renamed_or_modified_silently(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['model'], seed='new')
        with self.assertRaisesRegex(ValueError, 'seed|名称|重建'):
            self.api.prepare(config, self.root)
        config['seed'] = 'si'
        config['num_wann'] = 1
        with self.assertRaisesRegex(ValueError, '模型|重建'):
            self.api.prepare(config, self.root)

    def test_existing_iteration_limits_are_imported_and_preserved(self):
        self.source.write_text(WIN + 'num_iter = 1000\ndis_num_iter = 700\n')
        config = self.api.initial_config(self.source)
        self.assertEqual(config.get('num_iter'), 1000)
        self.assertEqual(config.get('dis_num_iter'), 700)
        config.update(tasks=['model'], parameters={})
        win = self.api.prepare(config, self.root)['si.win']
        self.assertIn('num_iter = 1000', win)
        self.assertIn('dis_num_iter = 700', win)

    def test_existing_convergence_settings_are_imported_and_preserved_verbatim(self):
        settings = ('conv_tol = 2.0d-9\nconv_window = 7\ndis_mix_ratio = 0.7\n'
                    'dis_conv_tol = 3.0D-9\ndis_conv_window = 4\n')
        original = WIN + settings
        self.source.write_text(original)
        config = self.api.initial_config(self.source)
        expected = {'conv_tol': 2e-9, 'conv_window': 7, 'dis_mix_ratio': .7,
                    'dis_conv_tol': 3e-9, 'dis_conv_window': 4}
        for key, value in expected.items():
            self.assertEqual(config.get(key), value, key)
        config.update(tasks=['model'], parameters={})
        generated = self.api.prepare(config, self.root)['si.win']
        self.assertIn(settings, generated)
        self.assertEqual(self.source.read_text(), original)

    def test_existing_convergence_settings_cannot_be_added_changed_or_cleared(self):
        original_settings = {'conv_tol': 1e-10, 'conv_window': 5, 'dis_mix_ratio': .5,
                             'dis_conv_tol': 1e-10, 'dis_conv_window': 3}
        for key, value in original_settings.items():
            for original in (WIN, WIN + f'{key} = {value}\n'):
                self.source.write_text(original)
                for replacement in (value * 2, None):
                    config = self.api.initial_config(self.source)
                    config.update(tasks=['model'], parameters={})
                    config[key] = replacement
                    if replacement is None and original == WIN:
                        continue
                    with self.subTest(key=key, original=original, replacement=replacement):
                        with self.assertRaisesRegex(ValueError, key):
                            self.api.prepare(config, self.root)

    def test_existing_native_disabled_convergence_values_are_preserved(self):
        settings = ('conv_tol = 0\nconv_window = -1\ndis_conv_tol = 0\n'
                    'dis_conv_window = 0\ndis_mix_ratio = 1.0\n')
        self.source.write_text(WIN + settings)
        config = self.api.initial_config(self.source)
        self.assertEqual(config.get('conv_window'), -1)
        self.assertEqual(config.get('dis_conv_window'), 0)
        config.update(tasks=['model'], parameters={})
        self.assertIn(settings, self.api.prepare(config, self.root)['si.win'])

    def test_existing_convergence_numbers_reject_invalid_values_and_boolean_json(self):
        for key, bad in [('conv_tol', '-1'), ('conv_tol', 'nan'),
                         ('conv_window', '1.5'), ('dis_mix_ratio', '0'),
                         ('dis_mix_ratio', '1.1'), ('dis_conv_tol', 'inf'),
                         ('dis_conv_window', '-1')]:
            self.source.write_text(WIN + f'{key} = {bad}\n')
            with self.subTest(key=key, bad=bad), self.assertRaisesRegex(ValueError, key):
                self.api.initial_config(self.source)
        for key in ('conv_tol', 'conv_window', 'dis_mix_ratio', 'dis_conv_tol', 'dis_conv_window'):
            self.source.write_text(WIN + f'{key} = 1\n')
            config = self.api.initial_config(self.source)
            config.update(tasks=['model'], parameters={})
            config[key] = True
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                self.api.prepare(config, self.root)

    def test_existing_shift_current_reuses_original_path_when_parameters_omit_it(self):
        self.source.write_text(WIN + 'begin kpoint_path\nG 0 0 0 X .5 0 0\nend kpoint_path\n')
        config = self.api.initial_config(self.source)
        config.update(tasks=['shift_current'],
                      parameters={'fermi_energy': 0, 'kubo_freq_max': 3, 'kubo_eigval_max': 4})
        win = self.api.prepare(config, self.root)['si.win']
        self.assertIn('begin kpoint_path\nG 0 0 0 X 0.5 0 0\nend kpoint_path', win)
        self.assertIn('bands_plot = true', win)
        self.assertEqual(win.count('begin kpoint_path'), 1)
        self.assertIn('restart = plot', win)

    def test_existing_shift_current_uses_automatic_path_when_original_has_none(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['shift_current'],
                      parameters={'fermi_energy': 0, 'kubo_freq_max': 3, 'kubo_eigval_max': 4})
        win = self.api.prepare(config, self.root)['si.win']
        self.assertIn('begin kpoint_path', win)
        self.assertIn('bands_plot = true', win)

    def test_existing_shift_current_replaces_all_supported_restart_syntax(self):
        for restart in ('restart wannierise', 'restart = wannierise',
                        'restart: wannierise', 'ReStArT\twannierise ! original mode'):
            with self.subTest(restart=restart):
                self.source.write_text(WIN + restart + '\n')
                config = self.api.initial_config(self.source)
                config.update(tasks=['shift_current'],
                              parameters={'fermi_energy': 0, 'kubo_freq_max': 3,
                                          'kubo_eigval_max': 4,
                                          'kpoint_path': ['G 0 0 0 X .5 0 0']})
                win = self.api.prepare(config, self.root)['si.win']
                restart_lines = re.findall(r'(?im)^\s*restart\b[^\n]*', win)
                self.assertEqual([line.strip() for line in restart_lines], ['restart = plot'])
                self.source.write_text(win)
                restored = self.api.initial_config(self.source)
                restored['tasks'] = ['shift_current']
                regenerated = self.api.prepare(restored, self.root)['si.win']
                self.assertEqual(self.api._win_parts(regenerated)[0]['restart'], 'plot')

    def test_existing_shift_current_missing_energy_limits_cannot_use_pending_stage(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['shift_current'], parameters={'fermi_energy': 0})
        with self.assertRaisesRegex(ValueError, 'kubo_freq_max|kubo_eigval_max'):
            self.api.prepare(config, self.root)

    def test_existing_shift_current_preserves_explicit_smearing_and_tail_settings(self):
        self.source.write_text(
            WIN + 'kubo_freq_max = 3\nkubo_eigval_max = 4\n'
            'kubo_smr_type = cold\nsc_w_thr = 8\nkubo_adpt_smr = true\n'
            'kubo_adpt_smr_fac = 1.2\nkubo_adpt_smr_max = 0.6\n'
            'begin kpoint_path\nG 0 0 0 X .5 0 0\nend kpoint_path\n')
        config = self.api.initial_config(self.source)
        config['tasks'] = ['shift_current']
        expected = {'sc_w_thr': 8, 'kubo_smr_type': 'cold', 'kubo_adpt_smr': True,
                    'kubo_adpt_smr_fac': 1.2, 'kubo_adpt_smr_max': .6}
        for key, value in expected.items():
            self.assertEqual(config['parameters'].get(key), value, key)
        win = self.api.prepare(config, self.root)['si.win']
        values, _ = self.api._win_parts(win)
        for key, value in {'sc_w_thr': '8', 'kubo_smr_type': 'cold', 'kubo_adpt_smr': 'true',
                           'kubo_adpt_smr_fac': '1.2', 'kubo_adpt_smr_max': '0.6'}.items():
            self.assertEqual(values.get(key), value, key)

    def test_existing_iteration_changes_or_new_limits_require_rebuilding(self):
        for original in (WIN, WIN + 'num_iter = 1000\ndis_num_iter = 700\n'):
            self.source.write_text(original)
            for key in ('num_iter', 'dis_num_iter'):
                config = self.api.initial_config(self.source)
                config.update(tasks=['model'], parameters={})
                config[key] = 800
                with self.subTest(key=key, original=original), self.assertRaisesRegex(ValueError, key):
                    self.api.prepare(config, self.root)
            self.assertEqual(self.source.read_text(), original)

    def test_existing_native_zero_iterations_remain_valid_but_malformed_limits_fail(self):
        self.source.write_text(WIN + 'num_iter = 0\ndis_num_iter = 0\n')
        config = self.api.initial_config(self.source)
        self.assertEqual(config.get('num_iter'), 0)
        self.assertEqual(config.get('dis_num_iter'), 0)
        config.update(tasks=['model'], parameters={})
        self.assertIn('num_iter = 0', self.api.prepare(config, self.root)['si.win'])
        for value in ('-1', '1.5', '.true.'):
            self.source.write_text(WIN + 'num_iter = ' + value + '\n')
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'num_iter'):
                self.api.initial_config(self.source)

    def test_existing_iteration_json_types_cannot_impersonate_matching_integer(self):
        self.source.write_text(WIN + 'num_iter = 1\n')
        for value in (True, 1.0):
            config = self.api.initial_config(self.source)
            config.update(tasks=['model'], parameters={}, num_iter=value)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'num_iter'):
                self.api.prepare(config, self.root)

    def test_existing_result_must_stay_with_its_original_directory(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['model'])
        target = self.root / 'elsewhere'
        target.mkdir()
        with self.assertRaisesRegex(ValueError, '目录'):
            self.api.prepare(config, target)

    def test_dimension_mismatch_is_reported_and_never_written(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['model'])
        (self.root / 'si.chk').write_bytes(b'external checkpoint')
        (self.root / 'si.eig').write_text('1 1 -1.0\n')
        (self.root / 'si.mmn').write_text('fixture\n3 1 6\n')
        with self.assertRaisesRegex(ValueError, '维度|eig|mmn'):
            self.api.prepare(config, self.root)
        self.assertEqual(self.source.read_text(), WIN)

    def test_missing_operators_explain_same_wavefunction_requirement(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['orbital_magnetization'],
                      parameters={'fermi_energy': 0, 'berry_kmesh': [8, 8, 8]})
        (self.root / 'si.pw2wan').write_text("&inputpp\n prefix='different', outdir='./wave data', seedname='si'\n/\n")
        bundle = self.api.prepare(config, self.root)
        self.assertIn('write_uhu', bundle['si.pw2wan'].lower())
        self.assertIn("prefix='different'", bundle['si.pw2wan'])
        self.assertIn('同一批', bundle['si.README.txt'])
        self.assertIn('需先补齐', bundle['si.README.txt'])
        self.assertNotIn('si.nscf.in', bundle)
        self.assertIn('si.nnkp', bundle['si.README.txt'])

    def test_supplement_refuses_wrong_seed_or_spin_interface(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['orbital_magnetization'],
                      parameters={'fermi_energy': 0, 'berry_kmesh': [8, 8, 8]})
        for values in ("seedname='other', spin_component='none'", "seedname='si', spin_component='up'"):
            (self.root / 'si.pw2wan').write_text('&inputpp\n' + values + '\n/\n')
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, 'seed|自旋|通道'):
                self.api.prepare(config, self.root)

    def test_existing_native_scalar_mesh_and_boolean_are_imported(self):
        self.source.write_text(WIN + 'shc_freq_scan = .true.\n')
        config = self.api.initial_config(self.source)
        self.assertEqual(config['parameters']['berry_kmesh'], [10, 10, 10])
        self.assertIs(config['parameters']['shc_freq_scan'], True)
        config.update(tasks=['ahc'])
        self.assertIn('berry_task', self.api.prepare(config, self.root)['si.win'])

    def test_each_kpoint_window_population_is_checked_when_eig_exists(self):
        self.source.write_text(WIN.replace('num_wann = 2', 'num_wann = 1') +
                               'dis_win_min = -2\ndis_win_max = 2\n'
                               'dis_froz_min = -1\ndis_froz_max = 1\n')
        (self.root / 'si.eig').write_text('1 1 -0.5\n2 1 0.5\n')
        config = self.api.initial_config(self.source)
        config['tasks'] = ['model']
        with self.assertRaisesRegex(ValueError, '冻结|frozen'):
            self.api.prepare(config, self.root)

    def test_existing_energy_windows_accept_fortran_d_exponents(self):
        self.source.write_text(WIN + 'dis_win_min = -2.0d0\ndis_win_max = 2.0D0\n')
        (self.root / 'si.eig').write_text('1 1 -0.5\n2 1 0.5\n')
        config = self.api.initial_config(self.source)
        config['tasks'] = ['model']
        self.assertIn('dis_win_min = -2.0d0', self.api.prepare(config, self.root)['si.win'])

    def test_existing_equal_dimension_model_preserves_inactive_windows_without_counting_them(self):
        original = WIN + 'dis_win_min = 0\ndis_win_max = 1\n'
        self.source.write_text(original)
        (self.root / 'si.eig').write_text('1 1 -0.5\n2 1 0.5\n')
        config = self.api.initial_config(self.source)
        config['tasks'] = ['model']
        generated = self.api.prepare(config, self.root)['si.win']
        self.assertIn('dis_win_min = 0\ndis_win_max = 1\n', generated)
        self.assertEqual(self.source.read_text(), original)

    def test_fermi_energy_requires_a_real_fermi_record(self):
        output = self.root / 'scf.out'
        output.write_text('the Fermi energy is    5.4321 ev\n')
        self.assertEqual(self.api.read_fermi_energy(output), 5.4321)
        output.write_text('highest occupied level (ev): 5.3\n')
        with self.assertRaisesRegex(ValueError, '费米'):
            self.api.read_fermi_energy(output)

    def test_existing_band_comparison_requires_original_qe_source(self):
        config = self.api.initial_config(self.source)
        config.update(tasks=['qe_bands'], parameters={'kpoint_path': ['G 0 0 0 X 0.5 0 0']})
        with self.assertRaisesRegex(ValueError, 'reference_source|SCF'):
            self.api.prepare(config, self.root)

    def test_existing_qe_reference_uses_actual_points_and_preserves_model(self):
        from test_wannier_inputs import SCF
        reference = self.root / 'scf.in'
        reference.write_text(SCF.replace('nat=2, ntyp=2', 'nat=1, ntyp=1')
                             .replace('Fe2 55.8 Fe.upf\n', '')
                             .replace('Fe2 0.5 0.5 0.5\n', '')
                             .replace('2 0 0\n1 2 0\n0 0 4', '3 0 0\n0 3 0\n0 0 3')
                             .replace('Fe1', 'Si'))
        kpt = self.root / 'si_band.kpt'
        kpt.write_text('2\n0 0 0 1\n0.125 0 0 1\n')
        config = self.api.initial_config(self.source)
        config.update(tasks=['qe_bands'], reference_source=str(reference), band_kpt=str(kpt),
                      parameters={'kpoint_path': ['G 0 0 0 X 0.5 0 0']})
        files = self.api.prepare(config, self.root)
        self.assertIn('si.bands.in', files)
        self.assertIn('K_POINTS crystal\n2\n', files['si.bands.in'])
        self.assertIn('0.125 0 0 1', files['si.bands.in'])
        self.assertNotIn('si.nscf.in', files)
        self.assertIn('Si:s;pz', files['si.win'])
        # An SCF can omit nbnd or only include occupied states. The reference
        # must still contain all bands represented by the existing model.
        from qbox.io.wannier_inputs import parse_qe
        for setting in ('', 'nbnd=1, '):
            reference.write_text(re.sub(r'nbnd=\d+,?\s*', '', reference.read_text())
                                 .replace('ecutwfc=5.0D1, ', 'ecutwfc=5.0D1, ' + setting))
            files = self.api.prepare(config, self.root)
            self.assertEqual(parse_qe(files['si.bands.in']).nbnd, 2)


if __name__ == '__main__':
    unittest.main()
