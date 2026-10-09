"""Read-only basis guidance derives electron counts from actual QE/UPF data."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCF = """&CONTROL calculation='scf', pseudo_dir='./pseudos' /
&SYSTEM ibrav=0, nat=3, ntyp=2, occupations='fixed', tot_charge=2 /
CELL_PARAMETERS angstrom
3 0 0
0 3 0
0 0 3
ATOMIC_SPECIES
Si1 28.085 Si.upf ! First species label
Si_down 28.085 Other.upf
ATOMIC_POSITIONS crystal
Si1 0 0 0
Si_down 0.25 0.25 0.25
Si1 0.5 0.5 0.5
K_POINTS automatic
4 4 4 0 0 0
"""


class BasisHelpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='basis help ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run_root = self.root / 'run'
        self.pseudos = self.run_root / 'pseudos'
        self.pseudos.mkdir(parents=True)
        self.source = self.root / 'input elsewhere' / 'sample.in'
        self.source.parent.mkdir()
        self.source.write_text(SCF)
        (self.pseudos / 'Si.upf').write_text('<UPF><PP_HEADER z_valence="4.0D+0"/></UPF>')
        (self.pseudos / 'Other.upf').write_text('<UPF><PP_HEADER z_valence="6.0"/></UPF>')
        self.config = {'source': str(self.source), 'run_root': str(self.run_root), 'mode': 'new'}

    def describe(self, config=None):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.wannier_basis_help'),
                             'the basis menu needs read-only electronic guidance')
        from qbox.io.wannier_basis_help import describe_basis
        lines = describe_basis(self.config if config is None else config)
        self.assertIsInstance(lines, list)
        self.assertTrue(all(isinstance(line, str) for line in lines))
        return '\n'.join(lines)

    def test_counts_species_labels_and_charge_using_run_root_without_mutation(self):
        before_config = copy.deepcopy(self.config)
        before_files = {str(p.relative_to(self.root)): p.read_bytes()
                        for p in self.root.rglob('*') if p.is_file()}
        text = self.describe()
        # 2 Si1 atoms x 4 + 1 Si_down atom x 6 - positive charge 2 = 12.
        self.assertRegex(text, r'价电子数[：:]\s*12(?=（|\s|$)')
        self.assertRegex(text, r'双占据轨道数参考[：:]\s*6(?=（|\s|$)')
        self.assertIn('空带', text)
        self.assertIn('不代表所需空带或目标 Wannier 轨道数', text)
        self.assertIn('nbnd', text)
        self.assertIn('num_wann', text)
        self.assertEqual(self.config, before_config)
        self.assertEqual({str(p.relative_to(self.root)): p.read_bytes()
                          for p in self.root.rglob('*') if p.is_file()}, before_files)

    def test_legacy_upf_valence_is_the_number_before_its_own_label(self):
        (self.pseudos / 'Other.upf').write_text(
            '<PP_HEADER>\n 6.000000 Z valence\n35.0 Suggested cutoff\n</PP_HEADER>')
        self.assertRegex(self.describe(), r'价电子数[：:]\s*12(?=（|\s|$)')

    def test_invalid_or_missing_pseudopotential_does_not_invent_count_or_fail(self):
        pseudo = self.pseudos / 'Other.upf'
        cases = [None, '<PP_HEADER z_valence="NaN"/>', '<PP_HEADER z_valence="0"/>',
                 '<PP_HEADER z_valence="6junk"/>',
                 '<PP_INFO>z_valence="6"</PP_INFO><PP_HEADER>\nZ valence\n35 cutoff\n</PP_HEADER>']
        for content in cases:
            with self.subTest(content=content):
                if content is None:
                    pseudo.unlink(missing_ok=True)
                else:
                    pseudo.write_text(content)
                text = self.describe()
                self.assertIn('无法', text)
                self.assertIn('UPF', text)
                self.assertNotRegex(text, r'价电子数[：:]\s*\d')
                self.assertNotRegex(text, r'双占据轨道数参考[：:]\s*\d')

    def test_spin_and_partial_occupancy_never_receive_scalar_band_estimate(self):
        cases = [('nspin=2, ', "occupations='fixed'", 'tot_charge=2', '自旋', '12'),
                 ('noncolin=.true., ', "occupations='fixed'", 'tot_charge=2', '旋量', '12'),
                 ('', "occupations='smearing'", 'tot_charge=2', '展宽', '12'),
                 ('', "occupations='tetrahedra'", 'tot_charge=2', '占据', '12'),
                 ('', "occupations='fixed'", 'tot_charge=1.5', '分数', '12.5'),
                 ('', "occupations='fixed'", 'tot_charge=1', '奇数', '13')]
        for spin, occupation, charge, explanation, expected in cases:
            with self.subTest(spin=spin, occupation=occupation, charge=charge):
                self.source.write_text(SCF.replace('ibrav=0', spin + 'ibrav=0')
                                       .replace("occupations='fixed'", occupation)
                                       .replace('tot_charge=2', charge))
                text = self.describe()
                self.assertIn('价电子数：' + expected + '（', text)
                self.assertNotRegex(text, r'双占据轨道数参考[：:]\s*\d')
                self.assertIn(explanation, text)

    def test_fractional_upf_and_negative_charge_use_actual_values(self):
        (self.pseudos / 'Si.upf').write_text('<PP_HEADER z_valence="3.5"/>')
        self.source.write_text(SCF.replace('tot_charge=2', 'tot_charge=-1.5D0'))
        self.assertRegex(self.describe(), r'价电子数[：:]\s*14\.5(?=（|\s|$)')

    def test_espresso_pseudo_fallback_is_resolved_against_run_root(self):
        self.source.write_text(SCF.replace(", pseudo_dir='./pseudos'", ''))
        with patch.dict(os.environ, {'ESPRESSO_PSEUDO': './pseudos'}):
            self.assertRegex(self.describe(), r'价电子数[：:]\s*12(?=（|\s|$)')

    def test_unavailable_or_invalid_sources_return_actionable_help(self):
        for source in ['', str(self.root / 'missing.in'), 'bad\0path']:
            with self.subTest(source=source):
                text = self.describe({**self.config, 'source': source})
                self.assertIn('无法', text)
                self.assertIn('SCF', text)
        for content in ['data_structure\n', SCF.replace('tot_charge=2', 'tot_charge=nan')]:
            with self.subTest(content=content):
                self.source.write_text(content)
                self.assertIn('无法', self.describe())

    def test_existing_win_is_not_mistaken_for_qe_electron_information(self):
        source = self.root / 'model.win'
        source.write_text('num_wann=6\nnum_bands=12\n')
        text = self.describe({**self.config, 'source': str(source), 'mode': 'existing'})
        self.assertIn('已有', text)
        self.assertNotRegex(text, r'价电子数[：:]\s*\d')


if __name__ == '__main__':
    unittest.main()
