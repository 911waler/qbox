"""Actual QE reciprocal cells, disconnected phonon branches and Gamma limits."""
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))


class QELatticeTests(unittest.TestCase):
    def build(self, system, rows=None, unit=None):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.qe_lattice'),
                             'QE lattice conversion has not been implemented')
        from qbox.io.qe_lattice import build_cell
        return build_cell({'system': system}, rows, unit)

    def assertCell(self, actual, expected):
        for actual_row, expected_row in zip(actual, expected):
            for a, b in zip(actual_row, expected_row):
                self.assertAlmostEqual(a, b, places=10)

    def test_fcc_retains_qe_axis_signs(self):
        self.assertCell(self.build({'ibrav': 2, 'a': 6}),
                        ((-3, 0, 3), (0, 3, 3), (-3, 3, 0)))

    def test_bohr_and_alat_explicit_cell_scaling(self):
        rows = ((0, 2, 0), (1, 0, 0), (0, 0, 3))
        self.assertCell(self.build({'ibrav': 0}, rows, 'bohr'),
                        ((0, 1.058354421806, 0), (.529177210903, 0, 0), (0, 0, 1.587531632709)))
        self.assertCell(self.build({'ibrav': 0, 'a': 2}, rows, 'alat'),
                        ((0, 4, 0), (2, 0, 0), (0, 0, 6)))
        self.assertCell(self.build({'ibrav': 1, 'celldm(1)': 2}),
                        ((1.058354421806, 0, 0), (0, 1.058354421806, 0), (0, 0, 1.058354421806)))

    def test_qe_bravais_axis_conventions(self):
        root3 = math.sqrt(3)
        cases = {
            1: ((2,0,0),(0,2,0),(0,0,2)),
            3: ((1,1,1),(-1,1,1),(-1,-1,1)),
            -3: ((-1,1,1),(1,-1,1),(1,1,-1)),
            4: ((2,0,0),(-1,root3,0),(0,0,6)),
            5: ((root3/2,-.5,math.sqrt(3)),(0,1,math.sqrt(3)),(-root3/2,-.5,math.sqrt(3))),
            -5: ((.183503419072274,1.40824829046386,1.40824829046386),
                 (1.40824829046386,.183503419072274,1.40824829046386),
                 (1.40824829046386,1.40824829046386,.183503419072274)),
            6: ((2,0,0),(0,2,0),(0,0,6)),
            7: ((1,-1,3),(1,1,3),(-1,-1,3)),
            8: ((2,0,0),(0,4,0),(0,0,6)),
            9: ((1,2,0),(-1,2,0),(0,0,6)),
            -9: ((1,-2,0),(1,2,0),(0,0,6)),
            91: ((2,0,0),(0,2,-3),(0,2,3)),
            10: ((1,0,3),(1,2,0),(0,2,3)),
            11: ((1,2,3),(-1,2,3),(-1,-2,3)),
            12: ((2,0,0),(2,2*root3,0),(0,0,6)),
            -12: ((2,0,0),(0,4,0),(3,0,3*root3)),
            13: ((1,0,-3),(2,2*root3,0),(1,0,3)),
            -13: ((1,2,0),(-1,2,0),(3,0,3*root3)),
        }
        # Rhombohedral cos=.625 yields tx=sqrt(3)/4, ty=1/4, tz=sqrt(3)/2.
        for ibrav, expected in cases.items():
            with self.subTest(ibrav=ibrav):
                params = {'ibrav':ibrav, 'a':2, 'b':4, 'c':6,
                          'cosab': .625 if abs(ibrav)==5 else .5, 'cosac':.5}
                self.assertCell(self.build(params), expected)

    def test_triclinic_angles_have_qe_not_cif_celldm_order(self):
        result = self.build({'ibrav':14, 'a':2, 'b':3, 'c':4,
                             'cosab':.5, 'cosac':.25, 'cosbc':.125})
        self.assertCell(result, ((2,0,0),(1.5,3*math.sqrt(3)/2,0),(1,0,math.sqrt(15))))
        result = self.build({'ibrav':14, 'celldm(1)':2/.529177210903,
                             'celldm(2)':1.5,'celldm(3)':2,
                             'celldm(4)':.125,'celldm(5)':.25,'celldm(6)':.5})
        self.assertCell(result, ((2,0,0),(1.5,3*math.sqrt(3)/2,0),(1,0,math.sqrt(15))))

    def test_rejects_ambiguous_singular_and_incomplete_cells(self):
        for params, rows, unit in [
            ({'ibrav':2,'a':3,'celldm(1)':6},None,None),
            ({'ibrav':8,'a':3},None,None),
            ({'ibrav':5,'a':3,'cosab':-.6},None,None),
            ({'ibrav':14,'a':3,'b':3,'c':3,'cosab':.9,'cosac':.9,'cosbc':-.9},None,None),
            ({'ibrav':0},((1,0,0),(1,0,0),(0,0,1)),'angstrom'),
            ({'ibrav':0},((1,0,0),(0,1,0),(0,0,1)),'alat'),
            ({'ibrav':0,'a':3},((1,0,0),(0,1,0),(0,0,1)),'angstrom'),
        ]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.build(params, rows, unit)


@unittest.skipUnless(importlib.util.find_spec('seekpath'), 'optional seekpath is absent')
class PhononPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def scf(self, cell=((3,0,0),(0,4,0),(0,0,5)), atoms=(('Si',(0,0,0)),), system=''):
        path = self.directory / 'si.scf.in'
        geometry = '\n'.join(' '.join(str(v) for v in row) for row in cell)
        positions = '\n'.join(label+' '+' '.join(str(v) for v in row) for label,row in atoms)
        species = '\n'.join(label+' 28.085 Si.UPF' for label in dict.fromkeys(a[0] for a in atoms))
        path.write_text(f"&CONTROL\n calculation='scf', prefix='si', outdir='./tmp'\n/\n"
                        f"&SYSTEM\n ibrav=0, nat={len(atoms)}, ntyp={len(species.splitlines())}, ecutwfc=30, {system}\n/\n"
                        "&ELECTRONS\n/\nATOMIC_SPECIES\n"+species+'\nCELL_PARAMETERS angstrom\n'+geometry+
                        '\nATOMIC_POSITIONS crystal\n'+positions+'\nK_POINTS automatic\n4 4 4 0 0 0\n')
        return path

    def generate(self, scf=None, **kwargs):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.phonon_paths'),
                             'phonon path generation has not been implemented')
        from qbox.io.phonon_paths import generate_phonon_path
        return generate_phonon_path(scf or self.scf(), points_per_segment=5, **kwargs)

    def test_nonstandard_axes_are_expressed_in_actual_scf_reciprocal_basis(self):
        result = self.generate(self.scf(((0,4,0),(3,0,0),(0,0,5))))
        self.assertEqual(result['coordinate_system'], 'crystal')
        self.assertEqual(result['qpoints'][result['labels'].index('X')], [0,.5,0])
        self.assertEqual(result['qpoints'][result['labels'].index('Y')], [.5,0,0])

    def test_disconnected_segments_are_not_interpolated_or_plotted_as_bridges(self):
        result = self.generate()
        points, segments = result['qpoints'], result['segments']
        self.assertEqual(result['breaks'], [segment['start'] for segment in segments[1:]])
        self.assertTrue(any(points[a['end']] != points[b['start']] for a,b in zip(segments,segments[1:])))
        for segment in segments:
            self.assertEqual(segment['end']-segment['start']+1,5)
            first, middle, last = (points[segment[k]] for k in ('start','start','end'))
            middle = points[segment['start']+2]
            for i in range(3):
                self.assertAlmostEqual(middle[i],(first[i]+last[i])/2)

    def test_every_gamma_limit_uses_its_own_segment_direction(self):
        # Doubled SCF cell makes some primitive endpoints nonzero reciprocal integers.
        result = self.generate(self.scf(((3,0,0),(0,6,0),(0,0,3)),
                                        (('Si',(0,0,0)),('Si',(0,.5,0)))))
        self.assertTrue(result['is_supercell'])
        self.assertTrue(any('primitive' in message.lower() for message in result['warnings']))
        points = result['qpoints']
        self.assertTrue(result['guard_indices'])
        checked = 0
        for segment in result['segments']:
            for index, other in ((segment['start'],segment['start']+1),(segment['end'],segment['end']-1)):
                if any(abs(x-round(x))>1e-10 for x in points[index]):
                    continue
                # Directly reproduce QE 7.5's documented adjacent-row choice.
                neighbor = index+1 if index==0 or (points[index-1]==[0,0,0] and index+1<len(points)) else index-1
                want = [points[index][i]-points[other][i] for i in range(3)]
                actual = [points[index][i]-points[neighbor][i] for i in range(3)]
                self.assertGreater(sum(x*x for x in actual),0)
                cross = [actual[1]*want[2]-actual[2]*want[1],actual[2]*want[0]-actual[0]*want[2],actual[0]*want[1]-actual[1]*want[0]]
                self.assertLess(sum(x*x for x in cross),1e-16)
                checked += 1
        self.assertGreater(checked,3)

    def test_two_dimensional_axis_is_explicit_and_preserved_under_permutation(self):
        path = self.scf(((3,0,0),(0,20,0),(0,0,4)))
        slab = self.generate(path,dimension=2,periodic_axis=2)
        self.assertTrue(all(point[1]==0 for point in slab['qpoints']))
        bulk = self.generate(path)
        self.assertTrue(any(abs(point[1])>.1 for point in bulk['qpoints']))

    def test_two_dimensional_skew_vacuum_axis_is_rejected(self):
        path = self.scf(((3,0,0),(0,4,0),(1,0,20)))
        with self.assertRaisesRegex(ValueError,'orthogonal|perpendicular'):
            self.generate(path,dimension=2,periodic_axis=3)

    @unittest.skipUnless(importlib.util.find_spec('pymatgen'), 'optional pymatgen is absent')
    def test_cif_mismatch_is_rejected_but_equivalent_axis_rotation_accepted(self):
        from pymatgen.core import Structure
        cif = self.directory / 'si.cif'
        Structure(((3,0,0),(0,4,0),(0,0,5)),['Si'],[[0,0,0]]).to(filename=str(cif))
        rotated = self.scf(((0,4,0),(3,0,0),(0,0,5)))
        self.generate(rotated,cif_file=cif)
        Structure(((3,0,0),(0,4,0),(0,0,5)),['C'],[[0,0,0]]).to(filename=str(cif))
        with self.assertRaisesRegex(ValueError,'CIF.*SCF|SCF.*CIF'):
            self.generate(rotated,cif_file=cif)

    def test_sampling_and_dimension_validation(self):
        for args in ({'dimension':0},{'dimension':2,'periodic_axis':0},{'dimension':2,'periodic_axis':True}):
            with self.subTest(args=args),self.assertRaises(ValueError):
                self.generate(**args)

    def test_two_point_sampling_preserves_ending_folded_gamma_direction(self):
        from qbox.io.phonon_paths import generate_phonon_path
        path = self.scf(((3,0,0),(0,6,0),(0,0,3)),
                        (('Si',(0,0,0)),('Si',(0,.5,0))))
        result = generate_phonon_path(path,points_per_segment=2)
        segment = result['segments'][0]
        # Gamma -> folded X=(0,1,0) needs an interior sample. Otherwise QE
        # sees preceding Gamma and takes its direction from the next segment.
        self.assertEqual(result['qpoints'][segment['start']], [0,0,0])
        self.assertEqual(result['qpoints'][segment['end']], [0,1,0])
        self.assertNotEqual(result['qpoints'][segment['end']-1], [0,0,0])

    def test_explicit_sampling_rejects_noninteger_and_too_small_counts(self):
        from qbox.io.phonon_paths import generate_phonon_path
        for count in (0,1,True,2.5):
            with self.subTest(count=count),self.assertRaises(ValueError):
                generate_phonon_path(self.scf(),points_per_segment=count)

    def test_matdyn_coordinates_use_qe_alat_and_fcc_reciprocal_axes(self):
        path = self.directory / 'si.scf.in'
        path.write_text("&CONTROL\n calculation='scf',prefix='si',outdir='./tmp'\n/\n"
                        "&SYSTEM\n ibrav=2,A=5.43,nat=2,ntyp=1,ecutwfc=30\n/\n"
                        "&ELECTRONS\n/\nATOMIC_SPECIES\nSi 28.085 Si.UPF\n"
                        "ATOMIC_POSITIONS crystal\nSi 0 0 0\nSi .25 .25 .25\n"
                        "K_POINTS automatic\n4 4 4 0 0 0\n")
        result = self.generate(path)
        self.assertIn('alat_angstrom',result)
        self.assertAlmostEqual(result['alat_angstrom'],5.43)
        self.assertEqual(result['qpoints'][1],[0,.125,.125])
        for actual,expected in zip(result['qpoints_matdyn'][1],[0,.25,0]):
            self.assertAlmostEqual(actual,expected,places=12)

    def test_matdyn_alat_for_explicit_cells_is_first_vector_length(self):
        result = self.generate(self.scf(((0,4,0),(3,0,0),(0,0,5))))
        self.assertIn('alat_angstrom',result)
        self.assertEqual(result['alat_angstrom'],4)
        for actual,expected in zip(result['qpoints_matdyn'][result['labels'].index('X')],[2/3,0,0]):
            self.assertAlmostEqual(actual,expected,places=12)

    def test_one_dimensional_actual_cell_path_follows_each_explicit_axis(self):
        for axis, endpoint, cartesian, label in (
                (1,[.5,0,0],[.5,0,0],'X'),
                (2,[0,.5,0],[0,.375,0],'Y'),
                (3,[0,0,.5],[0,0,.3],'Z')):
            with self.subTest(axis=axis):
                result = self.generate(dimension=1,periodic_axis=axis)
                self.assertEqual(result['qpoints'],[
                    [0,0,0], [value/4 for value in endpoint],
                    [value/2 for value in endpoint], [value*3/4 for value in endpoint], endpoint])
                self.assertEqual(result['labels'],['GAMMA','','','',label])
                self.assertEqual(len(result['segments']),1)
                self.assertEqual(result['periodic_axis'],axis)
                self.assertEqual(result['breaks'],[])
                for actual,expected in zip(result['qpoints_matdyn'][-1],cartesian):
                    self.assertAlmostEqual(actual,expected,places=12)

    def test_one_dimensional_supercell_path_uses_its_own_zone_boundary(self):
        path = self.scf(((6,0,0),(0,10,0),(0,0,12)),
                        (('Si',(0,0,0)),('Si',(.5,0,0))))
        result = self.generate(path,dimension=1,periodic_axis=1)
        self.assertEqual(result['qpoints'][-1],[.5,0,0])
        self.assertTrue(result['is_supercell'])
        self.assertTrue(any('fold' in message.lower() for message in result['warnings']))
        self.assertFalse(any('associated primitive-cell path' in message for message in result['warnings']))

    def test_one_dimensional_tilted_periodic_axis_is_rejected(self):
        path = self.scf(((3,1,0),(0,10,0),(0,0,12)))
        with self.assertRaisesRegex(ValueError,'Cartesian|orthogonal|perpendicular'):
            self.generate(path,dimension=1,periodic_axis=1)


@unittest.skipUnless(importlib.util.find_spec('pymatgen') and importlib.util.find_spec('seekpath'),
                     'optional pymatgen/seekpath are absent')
class PhononCifReadingTests(unittest.TestCase):
    """CIF verification retains measured values instead of idealizing them."""
    scf = PhononPathTests.scf
    generate = PhononPathTests.generate

    def setUp(self):
        PhononPathTests.setUp(self)
        self.cif = self.directory / 'sic.cif'
        self.cif.write_bytes((Path(__file__).resolve().parents[1] /
                             'fixtures/structures/phonon_sic.cif').read_bytes())

    def sic_scf(self):
        a, c = 3.094936, 10.132228
        return self.scf(((a,0,0),(-a/2,a*math.sqrt(3)/2,0),(0,0,c)), (
            ('Si',(0,0,.18789558)),('Si',(.33333336,.66666672,.43784524)),
            ('C',(0,0,.00044958)),('C',(.33333336,.66666672,.24980867)),
            ('Si',(.99999995,0,.68789556)),('Si',(.66666656,.33333317,.93784522)),
            ('C',(-.00000003,.99999990,.50044956)),('C',(.66666656,.33333317,.74980864))))

    def test_label_only_cif_is_quiet_and_path_still_uses_actual_scf(self):
        scf = self.sic_scf()
        original = self.cif.read_bytes()
        expected = self.generate(scf)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            result = self.generate(scf,cif_file=self.cif)
        self.assertEqual([str(item.message) for item in caught],[])
        self.assertEqual(self.cif.read_bytes(),original)
        for key in ('qpoints','qpoints_matdyn','cell_angstrom'):
            self.assertEqual(result[key],expected[key])

    def test_original_and_exact_thirds_are_not_rounded_or_warned(self):
        from qbox.io import phonon_paths
        self.assertTrue(hasattr(phonon_paths,'_load_cif_structure'))
        for x,y in (('0.33333336','0.66666672'),(repr(1/3),repr(2/3))):
            with self.subTest(x=x):
                text = self.cif.read_text().replace('0.33333336',x).replace('0.66666672',y)
                self.cif.write_text(text)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    structure = phonon_paths._load_cif_structure(self.cif)
                site = next(site for site in structure if abs(site.frac_coords[2]-.43784524)<1e-12)
                self.assertEqual(site.frac_coords[0],float(x))
                self.assertEqual(site.frac_coords[1],float(y))
                self.assertAlmostEqual(structure.lattice.a,3.094936,places=12)
                self.assertAlmostEqual(structure.lattice.c,10.132228,places=12)
                self.assertEqual(structure.composition.get_el_amt_dict(),{'Si':4.,'C':4.})
                self.assertEqual([str(item.message) for item in caught],[])

    def test_inconsistent_formula_is_rejected_not_only_warned(self):
        original = self.cif.read_text()
        for formula in ("_chemical_formula_sum 'Si4 C2'\n",
                        "_chemical_formula_sum 'Si C'\n_chemical_formula_structural 'Si4 C2'\n",
                        "_chemical_formula_sum ?\n_chemical_formula_structural 'Si4 C2'\n"):
            with self.subTest(formula=formula):
                self.cif.write_text(original.replace('data_system\n','data_system\n'+formula))
                with self.assertRaisesRegex(ValueError,'CIF.*(formula|composition|stoichiometry)'):
                    self.generate(self.sic_scf(),cif_file=self.cif)

    def test_invalid_or_partial_occupancy_cannot_be_assumed_full(self):
        original = self.cif.read_text()
        for occupancy in ('?', 'nan', '-1', '0', '.5', '1.1'):
            with self.subTest(occupancy=occupancy):
                lines = original.replace('_atom_site_fract_z\n','_atom_site_fract_z\n_atom_site_occupancy\n').splitlines()
                self.cif.write_text('\n'.join(line+' '+occupancy if line.startswith(('Si ','C ')) else line for line in lines)+'\n')
                with self.assertRaises(ValueError):
                    self.generate(self.sic_scf(),cif_file=self.cif)

    def test_unknown_element_or_invalid_coordinate_is_not_dropped(self):
        original = self.cif.read_text()
        for extra in ('?? 0.9 0.9 0.9\n','Xx1 0.9 0.9 0.9\n','Si9 nan 0.9 0.9\n','Si9 ? 0.9 0.9\n'):
            with self.subTest(extra=extra):
                self.cif.write_text(original+extra)
                with self.assertRaises(ValueError):
                    self.generate(self.sic_scf(),cif_file=self.cif)

    def test_other_cif_diagnostics_remain_actionable(self):
        original = self.cif.read_text()
        self.cif.write_text(original.replace('loop_\n_symmetry_equiv_pos_as_xyz\nx,y,z\n',''))
        with self.assertRaisesRegex(ValueError,'CIF.*(symmetry|parse|diagnostic)'):
            self.generate(self.sic_scf(),cif_file=self.cif)

    def test_explicit_space_group_and_scalar_p1_operation_are_quiet(self):
        original = self.cif.read_text()
        expected = self.generate(self.sic_scf())
        for symmetry in ("_symmetry_space_group_name_H-M 'P 1'\n",
                         "_symmetry_equiv_pos_as_xyz 'x,y,z'\n"):
            with self.subTest(symmetry=symmetry):
                self.cif.write_text(original.replace(
                    'loop_\n_symmetry_equiv_pos_as_xyz\nx,y,z\n',symmetry))
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    result = self.generate(self.sic_scf(),cif_file=self.cif)
                self.assertEqual([str(item.message) for item in caught],[])
                self.assertEqual(result['qpoints'],expected['qpoints'])

    def test_missing_formula_markers_are_optional_metadata(self):
        original = self.cif.read_text()
        for marker in ('?', '.'):
            with self.subTest(marker=marker):
                self.cif.write_text(original.replace('data_system\n',
                    f'data_system\n_chemical_formula_sum {marker}\n_chemical_formula_structural {marker}\n'))
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    self.generate(self.sic_scf(),cif_file=self.cif)
                self.assertEqual([str(item.message) for item in caught],[])

    def test_rounded_formula_uses_parser_stoichiometry_tolerance(self):
        from pymatgen.core import Structure
        cell = ((3,0,0),(0,4,0),(0,0,5))
        atoms = (('Si',(0,0,0)),('C',(.25,.25,.25)),('C',(.5,.5,.5)))
        Structure(cell,[atom[0] for atom in atoms],[atom[1] for atom in atoms]).to(filename=str(self.cif))
        text = self.cif.read_text()
        text = '\n'.join("_chemical_formula_sum 'Si0.3333 C0.6667'" if line.startswith('_chemical_formula_sum')
                         else line for line in text.splitlines())+'\n'
        self.cif.write_text(text)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            self.generate(self.scf(cell,atoms),cif_file=self.cif)
        self.assertEqual([str(item.message) for item in caught],[])

    def test_formula_stoichiometry_does_not_depend_on_overall_scale(self):
        original = self.cif.read_text()
        for formula in ('Si C', 'Si4000 C4000'):
            with self.subTest(formula=formula):
                self.cif.write_text(original.replace('data_system\n',
                    f"data_system\n_chemical_formula_sum '{formula}'\n"))
                self.generate(self.sic_scf(),cif_file=self.cif)
        self.cif.write_text(original.replace('data_system\n',
            "data_system\n_chemical_formula_sum 'Si4000 C2000'\n"))
        with self.assertRaisesRegex(ValueError,'CIF.*(formula|composition|stoichiometry)'):
            self.generate(self.sic_scf(),cif_file=self.cif)


if __name__ == '__main__':
    unittest.main()
