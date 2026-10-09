"""Initial basis values come from actual SCF/UPF data and preserve user edits."""
import copy
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCF = """&CONTROL calculation='scf', pseudo_dir='./pseudos' /
&SYSTEM ibrav=0, nat=8, ntyp=2 /
CELL_PARAMETERS angstrom
3 0 0
0 3 0
0 0 10
ATOMIC_SPECIES
C 12 C.UPF
Si 28 Si.UPF
ATOMIC_POSITIONS crystal
C 0 0 0
C .5 .5 .25
C 0 0 .5
C .5 .5 .75
Si .25 .25 .125
Si .75 .75 .375
Si .25 .25 .625
Si .75 .75 .875
K_POINTS automatic
4 4 2 0 0 0
"""


def upf(shells=(0, 1), valence=4):
    return ('<UPF><PP_HEADER z_valence="' + str(valence) + '"/>'
            '<PP_NONLOCAL><PP_BETA.1 angular_momentum="2"/></PP_NONLOCAL>'
            '<PP_PSWFC>' + ''.join(f'<PP_CHI.{i} l="{angular}" label="test{i}"/>'
                                  for i, angular in enumerate(shells, 1)) + '</PP_PSWFC></UPF>')


class InitialDefaultsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='wannier defaults ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pseudos = self.root / 'pseudos'; self.pseudos.mkdir()
        self.source = self.root / 'elsewhere' / 'source.in'
        self.source.parent.mkdir()
        self.source.write_text(SCF)
        for name in ('C.UPF', 'Si.UPF'):
            (self.pseudos / name).write_text(upf())
        self.config = {'source': str(self.source), 'run_root': str(self.root), 'mode': 'new',
                       'nbnd': None, 'num_wann': None, 'projections': []}

    def apply(self, config=None):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.wannier_defaults'))
        api = importlib.import_module('qbox.io.wannier_defaults')
        return api.apply_initial_defaults(self.config if config is None else config)

    def test_si4c4_defaults_32_orbitals_40_bands_and_does_not_use_beta_d(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        notes = self.apply()
        self.assertEqual(self.config['projections'], ['C:s;p', 'Si:s;p'])
        self.assertEqual(self.config['num_wann'], 32)
        self.assertEqual(self.config['nbnd'], 40)
        self.assertTrue(self.config['nbnd_confirmed'])
        self.assertEqual(self.config['num_iter'], 1000)
        self.assertEqual(self.config['dis_num_iter'], 1000)
        self.assertEqual(self.config['exclude_bands'], [])
        self.assertEqual(self.config['select_projections'], [])
        self.assertIn('num_wann', self.config['basis_defaults'])
        self.assertTrue(all(isinstance(n, str) for n in notes))
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_existing_explicit_values_are_preserved_on_repeated_application(self):
        self.config.update(nbnd=60, num_wann=8, projections=['C:s', 'Si:s'],
                           num_iter=250, dis_num_iter=300, windows={'dis_win_min': -4, 'dis_win_max': 7})
        values = copy.deepcopy(self.config)
        self.apply(); self.apply()
        for key, value in values.items():
            self.assertEqual(self.config[key], value, key)
        self.assertNotIn('nbnd', self.config.get('basis_defaults', {}))
        self.assertTrue(self.config['nbnd_confirmed'])

    def test_initial_iteration_provenance_distinguishes_an_explicit_same_value(self):
        explicit = {**self.config, 'num_iter': 1000, 'dis_num_iter': 1000}
        self.apply(explicit)
        self.apply()
        for key in ('num_iter', 'dis_num_iter'):
            self.assertEqual(explicit[key], self.config[key])
            self.assertNotIn(key, explicit.get('basis_defaults', {}))
            self.assertIn(key, self.config['basis_defaults'])

    def test_manual_projections_and_selected_subset_determine_missing_num_wann(self):
        self.config.update(projections=['C:s;p', 'Si:s;p'], select_projections=[1, 3, 5, 7])
        self.apply()
        self.assertEqual(self.config['num_wann'], 4)
        self.assertEqual(self.config['nbnd'], 20)  # 16-electron-pair capacity plus four.

    def test_no_automatic_projection_overrides_an_incompatible_orbital_count(self):
        self.config['num_wann'] = 8
        notes = self.apply()
        self.assertEqual(self.config['num_wann'], 8)
        self.assertFalse(self.config.get('projections'))
        self.assertTrue(any('不一致' in n for n in notes))

    def test_missing_pseudo_prevents_invented_basis_and_band_count(self):
        (self.pseudos / 'C.UPF').unlink()
        notes = self.apply()
        self.assertFalse(self.config.get('projections'))
        self.assertIsNone(self.config.get('num_wann'))
        self.assertIsNone(self.config.get('nbnd'))
        self.assertTrue(any('UPF' in n for n in notes))

    def test_repeated_l_including_unresolved_spin_orbit_pair_needs_manual_basis(self):
        for shells in ((0, 0, 1), (1, 1, 0)):
            with self.subTest(shells=shells):
                config = copy.deepcopy(self.config)
                (self.pseudos / 'Si.UPF').write_text(upf(shells))
                notes = self.apply(config)
                self.assertFalse(config.get('projections'))
                self.assertIsNone(config.get('num_wann'))
                self.assertTrue(any('径向' in n or '重复' in n for n in notes))

    def test_missing_or_unsupported_orbital_metadata_does_not_guess(self):
        for content in ('<PP_HEADER z_valence="4"/>', upf((0, 4))):
            with self.subTest(content=content):
                config = copy.deepcopy(self.config)
                (self.pseudos / 'Si.UPF').write_text(content)
                self.assertTrue(self.apply(config))
                self.assertFalse(config.get('projections'))
                self.assertIsNone(config.get('num_wann'))

    def test_spinor_doubles_projections_and_uses_single_occupancy_capacity(self):
        self.source.write_text(SCF.replace('ibrav=0', 'noncolin=.true., ibrav=0'))
        self.apply()
        self.assertEqual(self.config['projections'], ['C:s;p(u,d)', 'Si:s;p(u,d)'])
        self.assertEqual(self.config['num_wann'], 64)
        self.assertEqual(self.config['nbnd'], 80)

    def test_collinear_uses_per_channel_basis_and_conservative_capacity(self):
        self.source.write_text(SCF.replace('ibrav=0', 'nspin=2, ibrav=0'))
        self.config['channels'] = {'up': {'num_wann': 9}}
        self.apply()
        self.assertEqual(self.config['num_wann'], 32)
        self.assertEqual(self.config['nbnd'], 40)
        self.assertEqual(self.config['channels'], {'up': {'num_wann': 9}})

    def test_source_nbnd_exclusions_and_electron_charge_enter_base_before_buffer(self):
        self.source.write_text(SCF.replace('ibrav=0', 'nbnd=48, tot_charge=-2, ibrav=0'))
        self.config['exclude_bands'] = [1, 2]
        self.apply()
        self.assertEqual(self.config['nbnd'], 60)
        self.assertEqual(self.config['exclude_bands'], [1, 2])

    def test_invalid_explicit_nbnd_is_not_replaced_or_confirmed(self):
        for nbnd in (0, True, 'wrong'):
            with self.subTest(nbnd=nbnd):
                config = {**self.config, 'nbnd': nbnd, 'nbnd_confirmed': False}
                self.apply(config)
                self.assertEqual(config['nbnd'], nbnd)
                self.assertFalse(config.get('nbnd_confirmed'))

    def test_invalid_charge_does_not_leave_an_uncharged_capacity_estimate(self):
        self.source.write_text(SCF.replace('ibrav=0', 'tot_charge=unknown, ibrav=0'))
        self.config['projections'] = ['C:s;p', 'Si:s;p']
        self.apply()
        self.assertEqual(self.config['num_wann'], 32)
        self.assertIsNone(self.config.get('nbnd'))

    def test_distinct_semicore_angular_channels_are_included_without_excluding_bands(self):
        (self.pseudos / 'Si.UPF').write_text(upf((0, 1, 2), valence=14))
        self.apply()
        self.assertEqual(self.config['projections'], ['C:s;p', 'Si:s;p;d'])
        self.assertEqual(self.config['num_wann'], 52)
        self.assertEqual(self.config['nbnd'], 65)
        self.assertEqual(self.config['exclude_bands'], [])

    def test_channel_overrides_constrain_the_shared_band_estimate_without_being_changed(self):
        self.source.write_text(SCF.replace('ibrav=0', 'nspin=2, ibrav=0'))
        self.config['channels'] = {'up': {'num_wann': 50, 'exclude_bands': [1, 2]}}
        before = copy.deepcopy(self.config['channels'])
        self.apply()
        self.assertEqual(self.config['nbnd'], 65)
        self.assertEqual(self.config['channels'], before)

    def test_existing_models_and_missing_sources_are_untouched(self):
        for config in ({'mode': 'existing', 'source': str(self.source)}, {'mode': 'new', 'source': ''}):
            before = copy.deepcopy(config)
            self.apply(config)
            self.assertEqual(config, before)


if __name__ == '__main__':
    unittest.main()
