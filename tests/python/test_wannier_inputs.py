"""Input generation preserves physics and produces matching interface contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from qbox.io.wannier_inputs import build_bundle, parse_qe
from qbox.io.wannier_workflow import _win_parts

SCF = """! do not modify this source
&CONTROL calculation = 'scf', prefix='qe/name', outdir='./scratch ! / data',
 pseudo_dir='../pseudos', wfcdir='./wfc', verbosity='high' /
&SYSTEM ibrav=0, nat=2, ntyp=2, ecutwfc=5.0D1, nbnd=12,
 starting_magnetization(1)=0.25, occupations='smearing', degauss=0.02 /
&ELECTRONS conv_thr=1.0d-8 /
CELL_PARAMETERS {angstrom}
2 0 0
1 2 0
0 0 4
ATOMIC_SPECIES
Fe1 55.8 Fe.upf
Fe2 55.8 Fe.upf
ATOMIC_POSITIONS crystal
Fe1 0 0 0 1 1 1
Fe2 0.5 0.5 0.5
K_POINTS automatic
4 4 4 0 0 0
! trailing physics must survive
HUBBARD (ortho-atomic)
U Fe1-3d 4.0
U Fe2-3d 4.0
"""


def config(**kwargs):
    value = dict(seed='iron', version='3.1.0', mode='new', grid=[2, 1, 2], nbnd=12,
                 num_wann=2, projections=['Fe1:s', 'Fe2:s'], tasks=['centres'], parameters={})
    value.update(kwargs)
    return value


class ParseTests(unittest.TestCase):
    def test_quoted_delimiters_same_line_assignments_and_species_labels(self):
        qe = parse_qe(SCF)
        self.assertEqual(qe.prefix, 'qe/name')
        self.assertEqual(qe.outdir, './scratch ! / data')
        self.assertEqual(qe.get('system', 'ecutwfc'), 50.)
        self.assertEqual(qe.get('system', 'starting_magnetization(1)'), .25)
        self.assertEqual(qe.species, ['Fe1', 'Fe2'])
        self.assertEqual(qe.atoms[1], ('Fe2', (.5, .5, .5)))
        self.assertEqual(qe.cell[1], (1., 2., 0.))

    def test_coordinate_conversion_uses_nonorthogonal_cell(self):
        text = SCF.replace('ATOMIC_POSITIONS crystal', 'ATOMIC_POSITIONS angstrom').replace('Fe2 0.5 0.5 0.5', 'Fe2 1.5 1 2')
        self.assertEqual(parse_qe(text).atoms[1], ('Fe2', (.5, .5, .5)))
        text = SCF.replace('CELL_PARAMETERS {angstrom}', 'CELL_PARAMETERS bohr')
        self.assertAlmostEqual(parse_qe(text).cell[0][0], 1.058354421806, places=10)

    def test_invalid_or_unsupported_structures_are_errors(self):
        for text in [SCF.replace('ibrav=0', 'ibrav=2'), SCF.replace('nat=2', 'nat=3'),
                     SCF.replace('ntyp=2', 'ntyp=1'), SCF.replace('Fe2 0.5', 'Co 0.5'),
                     SCF.replace('0 0 4', '0 0 0'), SCF.replace('0.5 0.5 0.5', 'NaN 0.5 0.5'),
                     SCF.replace('ATOMIC_POSITIONS crystal', 'ATOMIC_POSITIONS crystal_sg'),
                     SCF.replace('{angstrom}', 'alat'), SCF.replace('0.5 0.5 0.5', '1/2 0.5 0.5')]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_qe(text)


class BundleTests(unittest.TestCase):
    def test_shift_current_without_fermi_prepares_inputs_and_defers_response(self):
        cfg = config(tasks=['shift_current'])
        fixed = SCF.replace("occupations='smearing', degauss=0.02", "occupations='fixed'")
        files = build_bundle(fixed, cfg, source_path='/tmp/run/scf.in',
                             run_root='/tmp/run', output_dir='/tmp/run')
        self.assertEqual(parse_qe(files['iron.nscf.in']).get('system', 'occupations'), 'fixed')
        self.assertEqual(parse_qe(files['iron.nscf.in']).get('control', 'verbosity'), 'high')
        values, _ = _win_parts(files['iron.win'])
        self.assertNotIn('fermi_energy', values)
        self.assertEqual(values['berry'], 'true')
        self.assertEqual(values['berry_task'], 'sc')
        record = json.loads(files['iron.qbox.json'])
        self.assertEqual(record['status'], 'pending_occupation_reference')
        self.assertTrue(record['config']['pending_fermi'])
        self.assertEqual(record['config']['tasks'], ['shift_current'])
        guide = files['iron.README.txt']
        self.assertIn('> scf.out', guide)
        self.assertIn('> nscf.out', guide)
        self.assertIn('--config iron.qbox.json --conflict backup', guide)
        self.assertNotIn('postw90.x', guide)
        self.assertNotIn('pending_fermi', cfg)

    def test_pending_shift_current_keeps_other_validation_and_requires_window_reference(self):
        for change in ({'parameters': {'sc_eta': -1}},
                       {'windows': {'reference': 'fermi', 'dis_win_min': -2, 'dis_win_max': 5}},
                       {'tasks': ['shift_current', 'ahc']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_bundle(SCF, config(**{'tasks': ['shift_current'], **change}))

    def test_filled_reference_enables_response_and_clears_pending_state(self):
        files = build_bundle(SCF, config(tasks=['shift_current'], pending_fermi=True,
                                        parameters={'fermi_energy': 3.5, 'kubo_freq_max':8,
                                                    'kubo_eigval_max':12}))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['berry_task'], 'sc')
        self.assertEqual(values['fermi_energy'], '3.5')
        self.assertIn('mpirun -np 4 postw90.x iron', files['iron.README.txt'])
        self.assertFalse(json.loads(files['iron.qbox.json'])['config'].get('pending_fermi'))

    def test_only_required_qe_settings_change_and_grid_matches_win(self):
        original = str(SCF)
        bundle = build_bundle(SCF, config(), run_root='/tmp/run', output_dir='/tmp/run')
        nscf = bundle['iron.nscf.in']
        parsed = parse_qe(nscf)
        self.assertEqual(parsed.get('control', 'calculation'), 'nscf')
        self.assertTrue(parsed.get('system', 'nosym'))
        self.assertTrue(parsed.get('system', 'noinv'))
        self.assertEqual(parsed.get('control', 'disk_io'), 'low')
        self.assertIn("prefix='qe/name'", nscf)
        self.assertIn("outdir='./scratch ! / data'", nscf)
        self.assertIn("starting_magnetization(1)=0.25", nscf)
        self.assertTrue(nscf.endswith('U Fe1-3d 4.0\nU Fe2-3d 4.0\n'))
        values, _ = _win_parts(bundle['iron.win'])
        self.assertEqual(values['mp_grid'], '2 1 2')
        self.assertIn("spin_component = 'none'", bundle['iron.pw2wan'])
        self.assertEqual(values['num_elec_per_state'], '2')
        self.assertEqual(SCF, original)

    def test_paths_resolve_from_run_root_not_source_parent(self):
        bundle = build_bundle(SCF, config(), source_path='/tmp/unrelated/scf.in', run_root='/tmp/runs', output_dir='/tmp/out')
        self.assertEqual(parse_qe(bundle['iron.nscf.in']).outdir, '../runs/scratch ! / data')
        self.assertEqual(parse_qe(bundle['iron.nscf.in']).pseudo_dir, '../pseudos')
        self.assertIn("outdir = '../runs/scratch ! / data'", bundle['iron.pw2wan'])
        self.assertEqual(parse_qe(bundle['iron.nscf.in']).wfcdir, '../runs/wfc')

    def test_defaults_and_environment_paths_are_explicit_and_consistent(self):
        text = SCF.replace("outdir='./scratch ! / data',", '').replace("pseudo_dir='../pseudos',", '').replace("wfcdir='./wfc',", '')
        with patch.dict(os.environ, {'ESPRESSO_TMPDIR': '/tmp/env-qe', 'ESPRESSO_PSEUDO': '/tmp/env-pseudo'}):
            bundle = build_bundle(text, config(), run_root='/tmp/run', output_dir='/tmp/out')
        parsed = parse_qe(bundle['iron.nscf.in'])
        self.assertEqual(parsed.outdir, '../env-qe')
        self.assertEqual(parsed.pseudo_dir, '../env-pseudo')
        self.assertIn("outdir = '../env-qe'", bundle['iron.pw2wan'])
        with self.assertRaisesRegex(ValueError, 'environment|环境'):
            build_bundle(SCF.replace('../pseudos', '$QBOX_MISSING_ENV/pseudo'), config())

    def test_excluded_bands_deduplicate_and_projection_selection_is_checked(self):
        files = build_bundle(SCF, config(exclude_bands='1-2, 2, 4', num_wann=2))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['num_bands'], '9')
        self.assertEqual(values['exclude_bands'], '1, 2, 4')
        files = build_bundle(SCF, config(projections=['Fe1:p'], select_projections=[1, 3]))
        self.assertEqual(_win_parts(files['iron.win'])[0]['select_projections'], '1, 3')
        for overrides in [dict(exclude_bands=[0]), dict(exclude_bands=[13]), dict(num_wann=13),
                          dict(projections=['Fe1:p']), dict(select_projections=[1, 3]),
                          dict(projections=['random']), dict(projections=['Fe1:l=8'])]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                build_bundle(SCF, config(**overrides))

    def test_windows_convert_only_explicit_reference_and_validate_nesting(self):
        windows = dict(dis_win_min=-3, dis_win_max=5, dis_froz_min=-1, dis_froz_max=2,
                       reference='fermi', fermi_energy=6)
        files = build_bundle(SCF, config(windows=windows))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['dis_win_min'], '3')
        self.assertEqual(values['dis_froz_max'], '8')
        for windows in [dict(dis_win_min=5, dis_win_max=-1), dict(dis_win_min=-1, dis_win_max=2, dis_froz_min=-2, dis_froz_max=1),
                        dict(dis_win_min=-1, dis_win_max=2, reference='fermi'), dict(dis_froz_max=1), dict(dis_win_min=float('nan'))]:
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                build_bundle(SCF, config(windows=windows))

    def test_collinear_channels_share_nscf_but_have_separate_models(self):
        text = SCF.replace('ibrav=0', 'nspin=2, ibrav=0')
        files = build_bundle(text, config(channels={'down': {'num_wann': 1, 'projections': ['Fe2:s']}}))
        self.assertEqual(len([name for name in files if name.endswith('.nscf.in')]), 1)
        for channel in ('up', 'down'):
            values, _ = _win_parts(files[f'iron_{channel}.win'])
            self.assertEqual(values['spin'], channel)
            self.assertIn(f"spin_component = '{channel}'", files[f'iron_{channel}.pw2wan'])
            self.assertEqual(values['num_elec_per_state'], '1')
        self.assertEqual(_win_parts(files['iron_down.win'])[0]['num_wann'], '1')
        self.assertNotIn('iron.win', files)
        self.assertEqual(parse_qe(files['iron.nscf.in']).nbnd, 12)

    def test_spinor_counts_spin_components_without_changing_source_soc(self):
        text = SCF.replace('ibrav=0', 'noncolin=.true., lspinorb=.false., ibrav=0')
        files = build_bundle(text, config(projections=['Fe1:s']))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['spinors'], 'true')
        self.assertEqual(values['num_elec_per_state'], '1')
        self.assertFalse(parse_qe(files['iron.nscf.in']).get('system', 'lspinorb'))
        with self.assertRaises(ValueError):
            build_bundle(text, config())

    def test_unsafe_or_missing_choices_fail_before_any_writes(self):
        for overrides in [dict(seed='../x'), dict(seed='a b'), dict(nbnd=None), dict(num_wann=None), dict(grid=[1, 0, 2]), dict(version='latest')]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                build_bundle(SCF, config(**overrides))
        for text in [SCF.replace("'scf'", "'vc-relax'"), SCF + '\nOCCUPATIONS\n1 1 1\n', SCF.replace("'smearing'", "'from_input'")]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                build_bundle(text, config())
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.in'
            source.write_text(SCF)
            bundle = build_bundle(source.read_text(), config(), source_path=source, output_dir=temp)
            self.assertEqual(list(Path(temp).iterdir()), [source])
            meta = json.loads(bundle['iron.qbox.json'])
            self.assertEqual(meta['status'], 'inputs_generated')
            self.assertEqual(meta['spin_mode'], 'scalar')
            self.assertTrue(meta['source']['sha256'])

class InterfaceTests(unittest.TestCase):
    def test_pw2wan_uses_only_supported_export_flags(self):
        files = build_bundle(SCF, config())
        self.assertNotIn('write_eig', files['iron.pw2wan'])

    def test_interface_namelist_edit_preserves_paths_and_comment(self):
        from qbox.io import wannier_inputs
        self.assertTrue(hasattr(wannier_inputs, 'rewrite_namelists'))
        original = "&INPUTPP prefix='iron', outdir='tmp!/', write_amn=.true. ! retain me\n/\n"
        edited = wannier_inputs.rewrite_namelists(original, {'inputpp': {'write_amn': False, 'write_spn': True}})
        self.assertIn("prefix='iron', outdir='tmp!/'", edited)
        self.assertIn('write_amn=.false. ! retain me', edited)
        self.assertIn('write_spn = .true.', edited)

    def test_qe_band_reference_uses_shared_path_and_actual_output_points(self):
        path = ['G 0 0 0 X 0.5 0 0', 'X 0.5 0 0 M 0.5 0.5 0']
        files = build_bundle(SCF, config(tasks=['bands', 'qe_bands'], parameters={'kpoint_path': path, 'bands_num_points': 20}))
        bands = parse_qe(files['iron.bands.in'])
        self.assertEqual(bands.get('control', 'calculation'), 'bands')
        self.assertIn('K_POINTS crystal_b', files['iron.bands.in'])
        self.assertIn('begin kpoint_path', files['iron.win'])
        files = build_bundle(SCF, config(tasks=['qe_bands'], parameters={'kpoint_path': path, 'band_kpt_text': '3\n0 0 0 1\n0.1 0 0 1\n0.5 0 0 1\n'}))
        self.assertIn('K_POINTS crystal\n3\n', files['iron.bands.in'])
        self.assertEqual(len(parse_qe(files['iron.bands.in']).atoms), 2)

    def test_orbital_indices_cannot_exceed_channel_num_wann(self):
        with self.assertRaises(ValueError):
            build_bundle(SCF, config(tasks=['orbitals'], parameters={'wannier_plot_list': [3]}))

    def test_projection_atom_and_spin_subsets_expand_without_random_padding(self):
        files = build_bundle(SCF, config(projections=['atom:2:sp-1', 'Fe1:l=1,mr=2']))
        self.assertIn('f=0.5,0.5,0.5:sp-1', files['iron.win'])
        text = SCF.replace('ibrav=0', 'noncolin=.true., ibrav=0')
        files = build_bundle(text, config(projections=['Fe1:s(u)', 'Fe2:s(d)[0,0,1]']))
        self.assertIn('Fe2:s(d)[0,0,1]', files['iron.win'])

class NativeContractTests(unittest.TestCase):
    def test_bundle_never_duplicates_scalar_wannier_keywords(self):
        for text, overrides in [(SCF, {}), (SCF.replace('ibrav=0', 'nspin=2, ibrav=0'), {}),
                                (SCF.replace('ibrav=0', 'noncolin=.true., ibrav=0'), {'projections': ['Fe1:s']})]:
            files = build_bundle(text, config(**overrides))
            for name, content in files.items():
                if name.endswith('.win'):
                    # Parsing rejects duplicate scalar keys regardless of alignment.
                    self.assertIn('num_elec_per_state', _win_parts(content)[0])

class ValidationEdgeTests(unittest.TestCase):
    def test_logicals_cannot_impersonate_integer_spin_settings(self):
        for replacement in ['ibrav=.false.', 'ibrav=0, nspin=.true.']:
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                parse_qe(SCF.replace('ibrav=0', replacement))

    def test_path_and_prefix_settings_require_strings(self):
        for text in [SCF.replace("prefix='qe/name'", 'prefix=42'), SCF.replace("outdir='./scratch ! / data'", 'outdir=.true.')]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                build_bundle(text, config())

    def test_overflowing_geometry_is_rejected_before_serialization(self):
        with self.assertRaises(ValueError):
            parse_qe(SCF.replace('2 0 0', '1D308 0 0'))

class ReferenceHelperTests(unittest.TestCase):
    def test_existing_channel_reference_is_independent_of_wannier_model_rebuild(self):
        from qbox.io import wannier_inputs
        self.assertTrue(hasattr(wannier_inputs, 'build_reference'))
        qe = parse_qe(SCF.replace('ibrav=0', 'nspin=2, ibrav=0'))
        files = wannier_inputs.build_reference(qe, 'iron_down', {'band_kpt_text': '2\n0 0 0 1\n0.1 0 0 1\n'},
                                              run_root='/tmp/run', output_dir='/tmp/out', spin_channel='down')
        self.assertEqual(set(files), {'iron_down.bands.in', 'iron_down.bands.pp.in'})
        self.assertIn('spin_component = 2', files['iron_down.bands.pp.in'])
        self.assertEqual(parse_qe(files['iron_down.bands.in']).outdir, '../run/scratch ! / data')

class NamelistOnlyTests(unittest.TestCase):
    def test_interface_identity_is_read_without_crystal_cards(self):
        from qbox.io import wannier_inputs
        self.assertTrue(hasattr(wannier_inputs, 'parse_namelists'))
        values = wannier_inputs.parse_namelists("&INPUTPP seedname='Fe_down', spin_component='down', outdir='tmp!/a' /\n")
        self.assertEqual(values['inputpp'], {'seedname': 'Fe_down', 'spin_component': 'down', 'outdir': 'tmp!/a'})

    def test_duplicate_mr_indices_cannot_hide_extra_native_projections(self):
        with self.assertRaises(ValueError):
            build_bundle(SCF, config(num_wann=1, projections=['Fe1:l=1,mr=1,1']))

class DerivedNumberTests(unittest.TestCase):
    def test_fermi_shift_cannot_produce_nonfinite_window(self):
        with self.assertRaises(ValueError):
            build_bundle(SCF, config(windows={'dis_win_min': 1e308, 'dis_win_max': 1e308,
                                              'reference': 'fermi', 'fermi_energy': 1e308}))

    def test_cartesian_conversion_cannot_produce_nonfinite_fraction(self):
        text = SCF.replace('2 0 0', '0.01 0 0').replace('ATOMIC_POSITIONS crystal', 'ATOMIC_POSITIONS angstrom')
        text = text.replace('Fe2 0.5 0.5 0.5', 'Fe2 1e308 0.5 0.5')
        with self.assertRaises(ValueError):
            parse_qe(text)


class IterationControlTests(unittest.TestCase):
    def test_explicit_iteration_limits_reach_generated_models(self):
        files = build_bundle(SCF, config(num_iter=1000, dis_num_iter=700))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['num_iter'], '1000')
        self.assertEqual(values['dis_num_iter'], '700')
        files = build_bundle(SCF.replace('ibrav=0', 'nspin=2, ibrav=0'),
                             config(num_iter=1000, dis_num_iter=700))
        for channel in ('up', 'down'):
            values, _ = _win_parts(files[f'iron_{channel}.win'])
            self.assertEqual(values['num_iter'], '1000')
            self.assertEqual(values['dis_num_iter'], '700')

    def test_iteration_defaults_remain_native_and_invalid_limits_are_rejected(self):
        files = build_bundle(SCF, config())
        self.assertNotIn('num_iter', _win_parts(files['iron.win'])[0])
        for key in ('num_iter', 'dis_num_iter'):
            for value in (0, -1, 1.5, True, 'many'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    build_bundle(SCF, config(**{key: value}))
