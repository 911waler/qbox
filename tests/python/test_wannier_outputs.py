"""Only completed, physically compatible QE outputs may supply energy data."""
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest


SCF = """&CONTROL calculation='scf', pseudo_dir='./pseudo' /
&SYSTEM ibrav=0, nat=2, ntyp=1, nbnd=4, ecutwfc=40, ecutrho=160 /
CELL_PARAMETERS bohr
6 0 0
0 6 0
0 0 6
ATOMIC_SPECIES
Si 28 Si.UPF
ATOMIC_POSITIONS crystal
Si 0 0 0
Si .25 .25 .25
K_POINTS automatic
2 2 2 0 0 0
"""
UPF = '<UPF><PP_HEADER z_valence="4" functional="PBE"/></UPF>\n'


def output(kind='scf', input_name='scf.in', spin='scalar', eigenvalues=True,
           fermi='the Fermi energy is 2.5000 ev', pseudo=UPF):
    spin_text = {'scalar': '', 'collinear': 'Starting magnetic structure\n',
                 'spinor': 'Non magnetic calculation with spin-orbit\n'}[spin]
    section = ('Self-consistent Calculation\nEnd of self-consistent calculation\n'
               if kind == 'scf' else 'Band Structure Calculation\nEnd of band structure calculation\n')
    energies = ('k = 0 0 0 (30 PWs) bands (ev):\n\n -5.0 -1.0 3.0 7.0\n\n'
                'occupation numbers\n 2.0 2.0 0.0 0.0\n'
                'k = .5 0 0 (30 PWs) bands (ev):\n\n -4.0 0.0 4.0 8.0\n\n') if eigenvalues else ''
    if spin == 'collinear' and eigenvalues:
        energies = '------ SPIN UP ------------\n' + energies + '------ SPIN DOWN ----------\n' + energies
    return f"""Program PWSCF v.7.5 starts on 8Oct2026
Reading input from {input_name}
bravais-lattice index = 0
lattice parameter (alat) = 6.0000 a.u.
number of atoms/cell = 2
number of atomic types = 1
number of electrons = 8.00
number of Kohn-Sham states= 4
kinetic-energy cutoff = 40.0000 Ry
charge density cutoff = 160.0000 Ry
Exchange-correlation= PBE
{spin_text}
celldm(1)= 6.000000 celldm(2)= 0.000000
crystal axes: (cart. coord. in units of alat)
a(1) = (1.000000 0.000000 0.000000)
a(2) = (0.000000 1.000000 0.000000)
a(3) = (0.000000 0.000000 1.000000)
PseudoPot. # 1 for Si read from file:
./pseudo/Si.UPF
MD5 check sum: {hashlib.md5(pseudo.encode()).hexdigest()}
Pseudo is Norm-conserving, Zval = 4.0
atomic species valence mass pseudopotential
Si 4.00 28.00 Si(1.00)
Cartesian axes
site n. atom positions (alat units)
1 Si tau(1) = (0.0000000 0.0000000 0.0000000)
2 Si tau(2) = (.2500000 .2500000 .2500000)
Crystallographic axes
site n. atom positions (cryst. coord.)
1 Si tau(1) = (0.0000000 0.0000000 0.0000000)
2 Si tau(2) = (.2500000 .2500000 .2500000)
number of k points= {4 if spin == 'collinear' else 2}
{section}{energies}{fermi}
{'convergence has been achieved in 6 iterations' if kind == 'scf' else ''}
JOB DONE.
"""


def fixed_nscf_output():
    text = output(kind='nscf', input_name='nscf.in', fermi='highest occupied, lowest unoccupied level (ev): 1.0 3.0')
    text = text.replace('states= 4', 'states= 6')
    text = text.replace('-5.0 -1.0 3.0 7.0', '-5.0 -3.0 -1.0 0.0 3.0 7.0')
    text = text.replace('-4.0 0.0 4.0 8.0', '-4.0 -2.0 0.0 1.0 4.0 8.0')
    return text.replace('number of k points= 2', '''number of k points= 2
cart. coord. in units 2pi/alat
k(1) = (0.0 0.0 0.0), wk = 1.0
k(2) = (0.5 0.0 0.0), wk = 1.0
cryst. coord.
k(1) = (0.0 0.0 0.0), wk = 1.0
k(2) = (0.5 0.0 0.0), wk = 1.0''')


class WannierOutputsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='wannier outputs ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'scf.in'
        self.source.write_text(SCF)
        (self.root / 'pseudo').mkdir()
        (self.root / 'pseudo/Si.UPF').write_text(UPF)

    def api(self):
        return importlib.import_module('qbox.io.wannier_outputs')

    def write(self, text=None, name='scf.out'):
        path = self.root / name
        path.write_text(output() if text is None else text)
        return path

    def read(self, path=None, **kwargs):
        return self.api().read_output(path or self.write(), self.source, **kwargs)

    def test_record_has_explicit_fermi_and_only_final_eigenvalues_not_occupations(self):
        path = self.write()
        record = self.read(path)
        self.assertEqual(record['path'], str(path))
        self.assertEqual(record['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(record['kind'], 'scf')
        self.assertEqual(record['nbnd'], 4)
        self.assertEqual(record['fermi_energy'], 2.5)
        self.assertEqual((record['eigenvalue_min'], record['eigenvalue_max']), (-5, 8))
        self.assertIsNone(record['homo']); self.assertIsNone(record['lumo'])
        self.assertTrue(any('可信' in note or '参考' in note for note in record['notes']))

    def test_homo_lumo_are_not_substituted_for_fermi(self):
        path = self.write(output(fermi='highest occupied, lowest unoccupied level (ev): 1.25 3.75'))
        record = self.read(path)
        self.assertIsNone(record['fermi_energy'])
        self.assertEqual((record['homo'], record['lumo']), (1.25, 3.75))
        path.write_text(output(fermi='highest occupied level (ev): 1.25'))
        record = self.read(path)
        self.assertEqual(record['homo'], 1.25); self.assertIsNone(record['lumo'])

    def test_dual_fermi_not_replaced_by_old_iteration_common_fermi(self):
        self.source.write_text(SCF.replace('ibrav=0', 'nspin=2, ibrav=0'))
        text = output(spin='collinear', fermi='the spin up/dw Fermi energies are 1.00 2.00 ev')
        text = text.replace('Self-consistent Calculation', 'the Fermi energy is 9.0 ev\nSelf-consistent Calculation')
        record = self.read(self.write(text))
        self.assertIsNone(record['fermi_energy'])
        self.assertTrue(any('双' in note or '分别' in note for note in record['notes']))

    def test_fortran_exponents_and_absent_eigenvalue_dump(self):
        record = self.read(self.write(output(eigenvalues=False, fermi='the Fermi energy is 2.5D+00 ev')))
        self.assertEqual(record['fermi_energy'], 2.5)
        self.assertIsNone(record['eigenvalue_min']); self.assertIsNone(record['eigenvalue_max'])

    def test_native_adjacent_negative_k_coordinates_keep_existing_scf_readable(self):
        text = output(fermi='highest occupied level (ev): 1.25').replace('k = .5 0 0', 'k = 0.5000-0.0000 0.0000')
        record = self.read(self.write(text))
        self.assertEqual(record['homo'], 1.25)
        self.assertIsNone(record['gap_reference'])

    def test_unrecognized_k_coordinate_format_only_disables_gap_inference(self):
        path = self.fixed_nscf()
        path.write_text(path.read_text().replace('k = .5 0 0', 'k = unsupported'))
        record = self.read(path)
        self.assertEqual(record['eigenvalue_min'], -5.)
        self.assertIsNone(record['gap_reference'])

    def test_nscf_requires_actual_companion_input_and_allows_band_mesh_occupation_changes(self):
        (self.root / 'dense.in').write_text(SCF.replace("calculation='scf'", "calculation='nscf'")
                                                .replace('nbnd=4', "nbnd=8, occupations='smearing', degauss=.01")
                                                .replace('2 2 2 0 0 0', '4 4 4 0 0 0'))
        text = output(kind='nscf', input_name='dense.in', eigenvalues=False).replace('states= 4', 'states= 8')
        record = self.read(self.write(text, 'unrelated-name.log'))
        self.assertEqual((record['kind'], record['nbnd']), ('nscf', 8))
        self.assertTrue(any('dense.in' in note for note in record['notes']))
        (self.root / 'dense.in').unlink()
        with self.assertRaisesRegex(ValueError, 'NSCF|输入|类型'):
            self.read(self.root / 'unrelated-name.log')

    def test_bands_and_relax_are_rejected_even_if_renamed_scf(self):
        for kind in ('bands', 'relax', 'vc-relax'):
            with self.subTest(kind=kind):
                (self.root / 'other.in').write_text(SCF.replace("calculation='scf'", f"calculation='{kind}'"))
                with self.assertRaises(ValueError):
                    self.read(self.write(output(input_name='other.in', kind='nscf' if kind == 'bands' else 'scf')))

    def test_incomplete_failed_nonconverged_and_concatenated_runs_are_rejected(self):
        good = output()
        for text in (good.replace('JOB DONE.', ''), good.replace('convergence has been achieved', 'convergence NOT achieved'),
                     good.replace('JOB DONE.', 'Error in routine c_bands (1)\nJOB DONE.'),
                     good + good, good.replace('End of self-consistent calculation', 'stopped'),
                     good.replace('JOB DONE.', 'Maximum CPU time exceeded\nJOB DONE.')):
            with self.subTest(text=text[-100:]):
                with self.assertRaises(ValueError):
                    self.read(self.write(text))

    def test_output_structure_cutoff_electrons_species_and_spin_are_checked(self):
        for old, new in [('a(1) = (1.000000', 'a(1) = (1.010000'),
                         ('(.2500000 .2500000 .2500000)', '(.2700000 .2500000 .2500000)'),
                         ('kinetic-energy cutoff = 40.0000', 'kinetic-energy cutoff = 50.0000'),
                         ('charge density cutoff = 160.0000', 'charge density cutoff = 200.0000'),
                         ('number of electrons = 8.00', 'number of electrons = 7.00'),
                         ('2 Si tau', '2 C tau'),
                         ('Exchange-correlation= PBE', 'Exchange-correlation= LDA')]:
            with self.subTest(new=new):
                with self.assertRaises(ValueError):
                    self.read(self.write(output().replace(old, new)))
        for spin in ('collinear', 'spinor'):
            with self.subTest(spin=spin):
                with self.assertRaises(ValueError):
                    self.read(self.write(output(spin=spin)))

    def test_matching_spinor_and_collinear_and_periodic_reordering(self):
        for spin, settings in [('spinor', 'noncolin=.true., lspinorb=.true., '), ('collinear', 'nspin=2, ')]:
            self.source.write_text(SCF.replace('ibrav=0', settings + 'ibrav=0'))
            text = output(spin=spin).replace('1 Si tau(1) = (0.0000000 0.0000000 0.0000000)\n2 Si tau(2) = (.2500000 .2500000 .2500000)',
                                            '1 Si tau(1) = (1.2500000 .2500000 .2500000)\n2 Si tau(2) = (0.0000000 0.0000000 0.0000000)')
            self.assertEqual(self.read(self.write(text))['fermi_energy'], 2.5)

    def test_pseudopotential_hash_mismatch_is_rejected_despite_same_name(self):
        with self.assertRaisesRegex(ValueError, '赝势|UPF'):
            self.read(self.write(output(pseudo=UPF + 'different')))

    def test_missing_provenance_is_rejected_instead_of_guessing_from_filename(self):
        for text in (output().replace('crystal axes: (cart. coord. in units of alat)', 'no cell'),
                     output().replace('number of electrons = 8.00', ''),
                     output().replace('kinetic-energy cutoff = 40.0000 Ry', ''),
                     output().replace('number of Kohn-Sham states= 4', '')):
            with self.subTest(text=text[:90]):
                with self.assertRaises(ValueError):
                    self.read(self.write(text))

    def test_companion_changed_charge_soc_or_hubbard_cannot_supply_reference(self):
        for setting in ('tot_charge=1, ', 'noncolin=.true., lspinorb=.true., ', 'lda_plus_u=.true., Hubbard_U(1)=4, '):
            with self.subTest(setting=setting):
                (self.root / 'other.in').write_text(SCF.replace('ibrav=0', setting + 'ibrav=0'))
                with self.assertRaises(ValueError):
                    self.read(self.write(output(input_name='other.in')))

    def test_electric_field_source_requires_companion_when_output_cannot_confirm_it(self):
        self.source.write_text(SCF.replace("calculation='scf'", "calculation='scf', tefield=.true., dipfield=.true.")
                                  .replace('ibrav=0', 'eamp=.01, edir=3, ibrav=0'))
        path = self.write(output(input_name='missing.in'), 'archived.out')
        with self.assertRaisesRegex(ValueError, '附加物理设置|对应输入'):
            self.read(path)
        self.assertEqual(self.api().discover_outputs(self.source, [self.root]), [])

    def test_unverified_hamiltonian_settings_require_companion(self):
        for section, setting in [('control', 'lelfield=.true.'), ('control', 'lfcp=.true.'),
                                 ('control', 'gate=.true.'), ('system', 'exx_fraction=.3'),
                                 ('system', 'screening_parameter=.2'), ('system', "vdw_corr='grimme-d3'"),
                                 ('system', 'esm_efield=.01'), ('system', 'fixed_magnetization(3)=1'),
                                 ('system', 'tot_magnetization=2'), ('system', 'Hubbard_U(1)=4'),
                                 ('system', 'starting_magnetization(1)=.2'),
                                 ('system', 'angle1(1)=90'), ('system', 'angle2(1)=45')]:
            with self.subTest(setting=setting):
                anchor = "calculation='scf'" if section == 'control' else 'ibrav=0'
                self.source.write_text(SCF.replace(anchor, anchor + ', ' + setting))
                path = self.write(output(input_name='missing.in'), 'archived.out')
                with self.assertRaisesRegex(ValueError, '附加物理设置|对应输入'):
                    self.read(path)

    def test_explicit_inactive_defaults_do_not_require_companion(self):
        self.source.write_text(SCF.replace("calculation='scf'", "calculation='scf', tefield=.false., dipfield=.false., gate=.false.")
                                  .replace('ibrav=0', "lda_plus_u=.false., assume_isolated='none', constrained_magnetization='none', tot_magnetization=-1, input_dft='PBE', ibrav=0"))
        path = self.write(output(input_name='missing.in'), 'archived.out')
        self.assertEqual(self.read(path)['fermi_energy'], 2.5)

    def test_matching_companion_permits_same_additional_hamiltonian_settings(self):
        text = SCF.replace("calculation='scf'", "calculation='scf', tefield=.true., dipfield=.true.")
        text = text.replace('ibrav=0', 'eamp=.01, edir=3, ibrav=0')
        self.source.write_text(text)
        (self.root / 'field.in').write_text(text)
        self.assertEqual(self.read(self.write(output(input_name='field.in')))['fermi_energy'], 2.5)

    def test_companion_initial_magnetic_state_must_match_including_soc_angles(self):
        for setting in ('starting_magnetization(1)=.2', 'angle1(1)=90', 'angle2(1)=45'):
            with self.subTest(setting=setting):
                text = SCF.replace('ibrav=0', 'noncolin=.true., lspinorb=.true., ibrav=0')
                self.source.write_text(text)
                (self.root / 'magnetic.in').write_text(text.replace('ibrav=0', setting + ', ibrav=0'))
                with self.assertRaisesRegex(ValueError, '物理设置'):
                    self.read(self.write(output(input_name='magnetic.in', spin='spinor')))

    def test_discovery_returns_every_valid_candidate_without_writes(self):
        self.write(name='old.out'); self.write(name='recent.pwo'); self.write(name='another.log')
        self.write(output().replace('JOB DONE.', ''), 'incomplete.out')
        self.write(output().replace('number of electrons = 8.00', 'number of electrons = 7.00'), 'wrong.out')
        self.write(name='irrelevant.txt')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        records = self.api().discover_outputs(self.source, [self.root, self.root, self.root / 'missing'])
        self.assertEqual({Path(r['path']).name for r in records}, {'old.out', 'recent.pwo', 'another.log'})
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_automatic_discovery_never_blocks_manual_setup_when_evidence_is_missing(self):
        path = self.write()
        (self.root / 'pseudo/Si.UPF').unlink()
        self.assertEqual(self.api().discover_outputs(self.source, [self.root]), [])
        with self.assertRaisesRegex(ValueError, 'UPF'):
            self.read(path)
        self.source.unlink()
        self.assertEqual(self.api().discover_outputs(self.source, [self.root]), [])
        with self.assertRaises(ValueError):
            self.read(path)

    def test_source_relative_pseudopaths_resolve_against_explicit_run_root(self):
        location = self.root / 'input files'; location.mkdir()
        self.source = location / 'source.in'; self.source.write_text(SCF)
        self.assertEqual(self.read(self.write(), run_root=self.root)['nbnd'], 4)

    def test_inconsistent_or_truncated_printed_band_rows_do_not_produce_bounds(self):
        text = output().replace('-5.0 -1.0 3.0 7.0', '-5.0 -1.0 3.0')
        with self.assertRaisesRegex(ValueError, '能带|本征值'):
            self.read(self.write(text))

    def fixed_nscf(self):
        text = SCF.replace("calculation='scf'", "calculation='nscf'").replace('nbnd=4', 'nbnd=6')
        text = text.replace('2 2 2 0 0 0', '2 1 1 0 0 0')
        (self.root / 'nscf.in').write_text(text)
        return self.write(fixed_nscf_output(), 'nscf.out')

    def test_complete_fixed_scalar_nscf_gets_separate_sampled_midgap_reference(self):
        record = self.read(self.fixed_nscf())
        self.assertIsNone(record['fermi_energy'])
        gap = record['gap_reference']
        self.assertEqual((gap['method'], gap['value_eV'], gap['vbm'], gap['cbm']),
                         ('sampled_midgap', 2.0, 1.0, 3.0))
        self.assertEqual((gap['electron_count'], gap['occupied_bands'], gap['kpoint_count']), (8, 4, 2))
        self.assertEqual(gap['grid'], [2, 1, 1])
        self.assertTrue(any('采样' in note for note in record['notes']))

    def test_midgap_requires_empty_bands_and_not_only_homo_or_printed_extrema(self):
        path = self.fixed_nscf()
        companion = self.root / 'nscf.in'
        companion.write_text(companion.read_text().replace('nbnd=6', 'nbnd=4'))
        path.write_text(output(kind='nscf', input_name='nscf.in', fermi='highest occupied level (ev): 7.0'))
        self.assertIsNone(self.read(path).get('gap_reference'))
        self.assertIsNone(self.read(self.write(output(fermi='highest occupied, lowest unoccupied level (ev): 1 3'))).get('gap_reference'))

    def test_overlap_tiny_gap_missing_or_duplicated_kpoints_prevent_midgap(self):
        path = self.fixed_nscf()
        valid = path.read_text()
        for text in (valid.replace('-4.0 -2.0 0.0 1.0 4.0 8.0', '-4.0 -2.0 0.0 3.5 4.0 8.0'),
                     valid.replace('0.0 3.0 7.0', '0.0 1.0001 7.0'),
                     valid.replace('k = .5 0 0 (30 PWs) bands (ev):\n\n -4.0 -2.0 0.0 1.0 4.0 8.0\n\n', ''),
                     valid.replace('k = .5 0 0', 'k = 0 0 0'),
                     valid.replace('k(2) = (0.5 0.0 0.0)', 'k(2) = (0.4 0.0 0.0)'),
                     valid.replace('cryst. coord.\nk(1)', 'unknown coord.\nk(1)')):
            with self.subTest(text=text[-120:]):
                path.write_text(text)
                self.assertIsNone(self.read(path).get('gap_reference'))

    def test_smearing_charge_and_spin_disable_midgap_even_with_positive_edges(self):
        path = self.fixed_nscf()
        companion = self.root / 'nscf.in'
        original = companion.read_text()
        for occupation in ('smearing', 'tetrahedra'):
            companion.write_text(original.replace('ibrav=0', f"occupations='{occupation}', ibrav=0"))
            self.assertIsNone(self.read(path).get('gap_reference'))
        for spin, settings in [('collinear', 'nspin=2'), ('spinor', 'noncolin=.true., lspinorb=.true.')]:
            self.source.write_text(SCF.replace('ibrav=0', settings + ', ibrav=0'))
            companion.write_text(original.replace('ibrav=0', settings + ', ibrav=0'))
            text = fixed_nscf_output().replace('Exchange-correlation= PBE', 'Exchange-correlation= PBE\n' +
                   ('Starting magnetic structure' if spin == 'collinear' else 'Non magnetic calculation with spin-orbit'))
            path.write_text(text)
            self.assertIsNone(self.read(path).get('gap_reference'))
        self.source.write_text(SCF.replace('ibrav=0', 'tot_charge=2, ibrav=0'))
        companion.write_text(original.replace('ibrav=0', 'tot_charge=2, ibrav=0'))
        path.write_text(fixed_nscf_output().replace('number of electrons = 8.00', 'number of electrons = 6.00'))
        self.assertIsNone(self.read(path).get('gap_reference'))

    def test_explicit_uniform_mesh_accepts_periodic_points_but_not_a_line_path(self):
        path = self.fixed_nscf()
        companion = self.root / 'nscf.in'
        text = companion.read_text().replace('K_POINTS automatic\n2 1 1 0 0 0',
            'K_POINTS crystal\n2\n0 0 0 .5\n-.5 0 0 .5')
        companion.write_text(text)
        self.assertEqual(self.read(path)['gap_reference']['value_eV'], 2.0)
        companion.write_text(text.replace('-.5 0 0 .5', '.4 0 0 .5'))
        self.assertIsNone(self.read(path).get('gap_reference'))

    def test_neutral_odd_or_fractional_electron_count_does_not_guess_occupancy(self):
        path = self.fixed_nscf()
        for valence, electrons in ((3.5, 7), (4.1, 8.2)):
            with self.subTest(electrons=electrons):
                payload = UPF.replace('z_valence="4"', f'z_valence="{valence}"')
                (self.root / 'pseudo/Si.UPF').write_text(payload)
                text = fixed_nscf_output().replace('number of electrons = 8.00', f'number of electrons = {electrons}')
                text = text.replace(hashlib.md5(UPF.encode()).hexdigest(), hashlib.md5(payload.encode()).hexdigest())
                path.write_text(text)
                self.assertIsNone(self.read(path)['gap_reference'])

    def test_shifted_full_mesh_and_native_joined_negative_band_coordinates(self):
        path = self.fixed_nscf()
        companion = self.root / 'nscf.in'
        companion.write_text(companion.read_text().replace('2 1 1 0 0 0', '2 1 1 1 0 0'))
        text = fixed_nscf_output().replace('k(1) = (0.0 0.0 0.0)', 'k(1) = (0.25 0.0 0.0)')
        text = text.replace('k(2) = (0.5 0.0 0.0)', 'k(2) = (0.75 0.0 0.0)')
        text = text.replace('k = 0 0 0', 'k = 0.2500 0.0000-0.0000')
        text = text.replace('k = .5 0 0', 'k = 0.7500 0.0000-0.0000')
        path.write_text(text)
        self.assertEqual(self.read(path)['gap_reference']['value_eV'], 2.)


if __name__ == '__main__':
    unittest.main()
