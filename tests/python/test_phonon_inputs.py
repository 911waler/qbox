"""Scientific input contracts for the phonon writer (no QE executable needed)."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qbox.io.phonon_inputs import (
    PhononSettings, generate_inputs, load_scf, resolve_settings, write_inputs,
)


SCF = """&CONTROL calculation='scf', PREFIX='actual', outdir='./scratch', pseudo_dir='./pseudo' /
&SYSTEM ibrav=0, NAT=2, ntyp=2, input_dft='LDA', occupations='fixed' /
&ELECTRONS conv_thr=1d-10 /
ATOMIC_SPECIES
O 15.999 O.upf ! species order must be preserved
C 12.011 C.upf
CELL_PARAMETERS angstrom
4 0 0
0 4 0
0 0 20
ATOMIC_POSITIONS crystal
C 0.25 0.25 0.5 0 0 0
O 0.5 0.5 0.5 1 1 1
K_POINTS gamma
"""
PATH_DATA = {'coordinate_system': 'crystal',
             'qpoints': [(0., 0., 0.), (.5, 0., 0.), (.5, .5, 0.)]}


class PhononInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'misleading-filename.scf.in'
        self.source.write_text(SCF)

    def load(self, text=SCF):
        self.source.write_text(text)
        return load_scf(self.source)

    def pseudo(self, header='pseudo_type="NC" functional="SLA PW NOGX NOGC"'):
        folder = self.root / 'pseudo'
        folder.mkdir(exist_ok=True)
        for name in ('C', 'O'):
            (folder / (name + '.upf')).write_text('<UPF><PP_HEADER ' + header + '/></UPF>')

    def test_compact_assignments_read_control_and_species_order(self):
        scf = self.load()
        self.assertEqual((scf.nat, scf.ntyp, scf.prefix), (2, 2, 'actual'))
        self.assertEqual(scf.outdir, str(self.root / 'scratch'))
        self.assertEqual([(item.label, item.mass) for item in scf.species],
                         [('O', 15.999), ('C', 12.011)])
        self.assertEqual(scf.atoms[0], ('C', (.25, .25, .5)))
        self.assertEqual(scf.position_flags[0], (0, 0, 0))

    def test_comments_and_quoted_bang_slash_do_not_forge_assignments(self):
        scf = self.load(SCF.replace("PREFIX='actual'", "PREFIX='a!b', ! nat=999\n title='fake prefix=xx'"))
        self.assertEqual(scf.prefix, 'a!b')
        self.assertEqual(scf.nat, 2)

    def test_compact_card_units_and_fortran_escaped_strings(self):
        source = SCF.replace('ATOMIC_POSITIONS crystal', 'ATOMIC_POSITIONS(crystal)')
        source = source.replace("PREFIX='actual'", "PREFIX='a''b'")
        files = generate_inputs(self.load(source), PhononSettings())
        self.assertIn("prefix = 'a''b'", files['a_b.ph.in'])
        self.assertEqual(self.load(source).atoms[0][1], (.25, .25, .5))

    def test_invalid_source_fails_before_any_output(self):
        for text, expected in [(SCF.replace('NAT=2', 'NAT='), 'nat'),
                               (SCF.replace('ntyp=2', 'ntyp=0'), 'ntyp'),
                               (SCF.replace('NAT=2', 'NAT=3'), 'ATOMIC_POSITIONS'),
                               (SCF.replace('O 15.999', 'O -1'), '质量'),
                               (SCF.replace("calculation='scf'", "calculation='relax'"), 'scf')]:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    self.load(text)
        with self.assertRaisesRegex(ValueError, '不存在'):
            load_scf(self.root / 'missing.in')
        self.assertEqual(list(self.root.glob('*.ph.in')), [])

    def test_gamma_has_title_actual_saved_data_and_ordered_masses(self):
        files = generate_inputs(self.load(), PhononSettings())
        ph = files['actual.ph.in']
        self.assertFalse(ph.splitlines()[0].startswith('&'))
        self.assertIn("prefix = 'actual'", ph)
        self.assertIn("outdir = '" + str(self.root / 'scratch') + "'", ph)
        self.assertIn('amass(1) = 15.999', ph)
        self.assertIn('amass(2) = 12.011', ph)
        self.assertIn('tr2_ph = 1d-12', ph)
        self.assertIn("asr = 'crystal'", files['actual.dynmat.in'])
        self.assertNotIn('fildvscf', ph)

    def test_asr_defaults_and_adsorbate_subset(self):
        scf = self.load()
        self.assertEqual(resolve_settings(scf, PhononSettings(system='gas')).asr, 'zero-dim')
        files = generate_inputs(scf, PhononSettings(system='adsorbate', selected_atoms=(2,)))
        self.assertIn('nat_todo = 1', files['actual.ph.in'])
        self.assertIn('nogg = .true.', files['actual.ph.in'])
        self.assertTrue(files['actual.ph.in'].endswith('0.0 0.0 0.0\n2\n'))
        self.assertIn("asr = 'no'", files['actual.dynmat.in'])
        self.assertIn('remove_interaction_blocks = .true.', files['actual.dynmat.in'])
        with self.assertRaisesRegex(ValueError, 'ASR|asr'):
            generate_inputs(scf, PhononSettings(system='adsorbate', selected_atoms=(2,), asr='zero-dim'))

    def test_dispersion_explicit_qpoints_and_qgrid(self):
        settings = PhononSettings(task='dispersion', q_grid=(6, 5, 4), tr2_ph='2d-14')
        files = generate_inputs(self.load(), settings, PATH_DATA)
        ph, matdyn = files['actual.ph.in'], files['actual.matdyn.in']
        self.assertIn('nq1 = 6', ph)
        self.assertIn('nq2 = 5', ph)
        self.assertIn('nq3 = 4', ph)
        self.assertIn('tr2_ph = 2d-14', ph)
        self.assertNotIn('epsil =', ph)  # QE ldisp determines it from occupations.
        self.assertIn("flfrq = 'actual.freq'", matdyn)
        self.assertNotIn('flfreq', matdyn)
        self.assertIn('q_in_cryst_coord = .true.', matdyn)
        self.assertIn('q_in_band_form = .false.', matdyn)
        self.assertTrue(matdyn.endswith('/\n3\n0 0 0\n0.5 0 0\n0.5 0.5 0\n'))

    def test_invalid_qgrid_threshold_and_incomplete_path_are_rejected(self):
        scf = self.load()
        for opts in (PhononSettings(q_grid=(0, 4, 4)), PhononSettings(tr2_ph='nan'),
                     PhononSettings(tr2_ph='1d-12;exit'), PhononSettings(q_grid=(2.5, 4, 4))):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                generate_inputs(scf, opts)
        with self.assertRaisesRegex(ValueError, '路径'):
            generate_inputs(scf, PhononSettings(task='dispersion'))
        with self.assertRaisesRegex(ValueError, 'epsil.*自动|自动.*epsil'):
            generate_inputs(scf, PhononSettings(task='dispersion', epsil=False), PATH_DATA)

    def test_matdyn_comments_preserve_labels_segments_guards_and_numeric_rows(self):
        path = {'coordinate_system': 'crystal',
                'qpoints': [[0, 0, 0], [.5, 0, 0], [0, 0, 0], [0, 0, 0], [0, .5, 0]],
                'labels': ['GAMMA', 'X', '', 'GAMMA', 'Y'], 'guard_indices': [2],
                'segments': [{'start': 0, 'end': 1}, {'start': 3, 'end': 4}]}
        text = generate_inputs(self.load(), PhononSettings(task='dispersion'), path)['actual.matdyn.in']
        rows = text.split('/\n', 1)[1].splitlines()
        self.assertEqual(rows[0], '5 ! qbox:path-v1')
        self.assertEqual(rows[1:], ['0 0 0 ! GAMMA qbox:start', '0.5 0 0 ! X qbox:end',
                                    '0 0 0 ! qbox:guard', '0 0 0 ! GAMMA qbox:start',
                                    '0 0.5 0 ! Y qbox:end'])
        self.assertEqual([row.split('!')[0].strip() for row in rows[1:]],
                         ['0 0 0', '0.5 0 0', '0 0 0', '0 0 0', '0 0.5 0'])

    def test_matdyn_labels_without_segments_remain_plain_external_style(self):
        path = {**PATH_DATA, 'labels': ['GAMMA', '', 'M']}
        text = generate_inputs(self.load(), PhononSettings(task='dispersion'), path)['actual.matdyn.in']
        self.assertTrue(text.endswith('/\n3\n0 0 0 ! GAMMA\n0.5 0 0\n0.5 0.5 0 ! M\n'))

    def test_matdyn_rejects_incomplete_annotation_metadata_and_multiline_labels(self):
        settings = PhononSettings(task='dispersion')
        for extra in ({'labels': ['GAMMA', 'X\n0 0 0', 'M']},
                      {'labels': ['GAMMA']},
                      {'guard_indices': [1]},
                      {'segments': [{'start': 0, 'end': 1}]},
                      {'segments': [{'start': 0, 'end': 2}], 'guard_indices': [1]},
                      {'segments': [{'start': 0, 'end': 2}], 'guard_indices': [3]}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                generate_inputs(self.load(), settings, {**PATH_DATA, **extra})

    def test_all_asr_pairs_long_range_and_zasr_is_independent(self):
        files = generate_inputs(self.load(), PhononSettings(system='polar', task='dispersion',
                                asr='all', zasr='simple', huang=False), PATH_DATA)
        self.assertIn("zasr = 'simple'", files['actual.q2r.in'])
        self.assertIn('write_lr = .true.', files['actual.q2r.in'])
        self.assertIn("asr = 'all'", files['actual.matdyn.in'])
        self.assertIn('read_lr = .true.', files['actual.matdyn.in'])
        self.assertIn('huang = .false.', files['actual.matdyn.in'])
        with self.assertRaisesRegex(ValueError, 'matdyn'):
            generate_inputs(self.load(), PhononSettings(asr='all'))

    def test_noncollinear_consumers_follow_xml_dynamical_files(self):
        for flags in ('noncolin=.true.', 'noncolin=.true., lspinorb=.true.'):
            with self.subTest(flags=flags):
                scf = self.load(SCF.replace('NAT=2', flags + ', NAT=2'))
                gamma = generate_inputs(scf, PhononSettings())
                self.assertIn("fildyn = 'actual.dynG.xml'", gamma['actual.ph.in'])
                self.assertIn("fildyn = 'actual.dynG.xml'", gamma['actual.dynmat.in'])
                dispersion = generate_inputs(scf, PhononSettings(task='dispersion'), PATH_DATA)
                self.assertIn("fildyn = 'actual.dyn.xml'", dispersion['actual.ph.in'])
                self.assertIn("fildyn = 'actual.dyn.xml'", dispersion['actual.q2r.in'])
                self.assertIn("flfrc = 'actual.fc'", dispersion['actual.q2r.in'])
                self.assertIn("flfrc = 'actual.fc.xml'", dispersion['actual.matdyn.in'])

    def test_polar_gamma_loto_direction_and_disable(self):
        files = generate_inputs(self.load(), PhononSettings(system='polar', q_direction=(0, 1, 0)))
        self.assertIn('epsil = .true.', files['actual.ph.in'])
        self.assertIn('q(2) = 1', files['actual.dynmat.in'])
        disabled = generate_inputs(self.load(), PhononSettings(system='polar', loto_disable=True))
        self.assertNotIn('q(1)', disabled['actual.dynmat.in'])
        self.assertNotIn('loto_disable', disabled['actual.dynmat.in'])  # dynmat has no such flag.

    def test_zeu_explicit_false_is_not_lost_to_qe_epsil_default(self):
        settings = PhononSettings(system='polar', zeu=False, q_direction=(0, 0, 0))
        ph = generate_inputs(self.load(), settings)['actual.ph.in']
        self.assertIn('epsil = .true.', ph)
        self.assertIn('zeu = .false.', ph)
        automatic = generate_inputs(self.load(), PhononSettings(system='polar'))
        self.assertIn('zeu = .true.', automatic['actual.ph.in'])
        with self.assertRaisesRegex(ValueError, 'LO.TO.*zeu|zeu.*LO.TO'):
            generate_inputs(self.load(), PhononSettings(system='polar', zeu=False))

    def test_2d_requires_explicit_geometry_and_scf_coulomb_cutoff_for_loto(self):
        scf = self.load()
        self.assertEqual(resolve_settings(scf, PhononSettings()).dimension, 3)
        two = resolve_settings(scf, PhononSettings(dimension=2, periodic_axis=3))
        self.assertEqual((two.asr, two.q_grid), ('crystal', (4, 4, 1)))
        with self.assertRaisesRegex(ValueError, 'assume_isolated'):
            generate_inputs(scf, replace(two, loto_2d=True))
        cutoff = self.load(SCF.replace("input_dft='LDA'", "assume_isolated='2D', input_dft='LDA'"))
        resolved = resolve_settings(cutoff, PhononSettings(system='polar', loto_2d=True))
        self.assertEqual(resolved.dimension, 2)
        self.assertIn('loto_2d = .true.', generate_inputs(cutoff, resolved)['actual.dynmat.in'])
        with self.assertRaisesRegex(ValueError, '同时'):
            resolve_settings(cutoff, replace(resolved, loto_disable=True))
        tilted = self.load(SCF.replace('0 0 20', '3 0 20'))
        with self.assertRaisesRegex(ValueError, '轴|垂直'):
            resolve_settings(tilted, PhononSettings(dimension=2, periodic_axis=3))

    def test_explicit_3d_grid_cannot_silently_become_a_2d_default(self):
        with self.assertRaisesRegex(ValueError, '非周期'):
            resolve_settings(self.load(), PhononSettings(dimension=2, q_grid=(4, 4, 4)))

    def test_2d_cutoff_defaults_loto_for_polar_gamma_and_insulating_dispersion(self):
        cutoff = self.load(SCF.replace("input_dft='LDA'", "assume_isolated='2D', input_dft='LDA'"))
        gamma = generate_inputs(cutoff, PhononSettings(system='polar'))
        self.assertIn('loto_2d = .true.', gamma['actual.dynmat.in'])
        dispersion = generate_inputs(cutoff, PhononSettings(task='dispersion'), PATH_DATA)
        self.assertIn('loto_2d = .true.', dispersion['actual.q2r.in'])
        self.assertIn('loto_2d = .true.', dispersion['actual.matdyn.in'])
        disabled = generate_inputs(cutoff, PhononSettings(system='polar', loto_2d=False))
        self.assertNotIn('loto_2d', disabled['actual.dynmat.in'])
        ordinary = generate_inputs(self.load(), PhononSettings(system='polar', dimension=2))
        self.assertNotIn('loto_2d', ordinary['actual.dynmat.in'])
        with self.assertRaisesRegex(ValueError, '同时'):
            generate_inputs(cutoff, PhononSettings(system='polar', loto_disable=True))

    def test_gamma_zero_direction_disables_nonanalytic_shift(self):
        files = generate_inputs(self.load(), PhononSettings(system='polar', q_direction=(0, 0, 0)))
        self.assertIn('q(1) = 0', files['actual.dynmat.in'])

    def test_path_metadata_preserves_breaks_guards_and_atom_count(self):
        path = {**PATH_DATA, 'segments': [{'start': 0, 'end': 2}], 'guard_indices': [],
                'distances': [0., 1., 2.], 'breaks': []}
        files = generate_inputs(self.load(), PhononSettings(task='dispersion'), path)
        metadata = json.loads(files['actual.path.json'])
        self.assertEqual(metadata['nat'], 2)
        self.assertEqual(metadata['segments'], [{'start': 0, 'end': 2}])
        self.assertEqual(metadata['guard_indices'], [])

    def test_one_dimensional_asr_checks_cartesian_axis(self):
        files = generate_inputs(self.load(), PhononSettings(dimension=1, periodic_axis=1))
        self.assertIn("asr = 'one-dim'", files['actual.dynmat.in'])
        self.assertIn('axis = 1', files['actual.dynmat.in'])
        tilted = self.load(SCF.replace('4 0 0', '4 1 0'))
        with self.assertRaisesRegex(ValueError, 'Cartesian|笛卡尔'):
            resolve_settings(tilted, PhononSettings(dimension=1, periodic_axis=1))

    def test_ir_has_electric_response_and_metal_is_rejected(self):
        files = generate_inputs(self.load(), PhononSettings(task='ir'))
        for field in ('trans', 'epsil', 'zeu'):
            self.assertIn(field + ' = .true.', files['actual.ph.in'])
        metal = self.load(SCF.replace("occupations='fixed'", "occupations='smearing'"))
        with self.assertRaisesRegex(ValueError, '绝缘体'):
            generate_inputs(metal, PhononSettings(task='ir'))

    def test_raman_requires_confirmed_nc_lda_and_scalar_insulator(self):
        with self.assertRaisesRegex(ValueError, '未知|无法核实'):
            generate_inputs(self.load(), PhononSettings(task='raman'))
        self.pseudo()
        files = generate_inputs(self.load(), PhononSettings(task='combined', eth_rps=1e-10))
        for flag in ('trans', 'epsil', 'lraman', 'zeu'):
            self.assertIn(flag + ' = .true.', files['actual.ph.in'])
        self.assertIn('eth_rps = 1e-10', files['actual.ph.in'])
        for replacement, expected in [("input_dft='PBE'", 'LDA'),
                                     ("input_dft='LDA', nspin=2", 'nspin'),
                                     ("input_dft='LDA', noncolin=.true., lspinorb=.true.", 'SOC|非共线'),
                                     ("input_dft='LDA', lda_plus_u=.true.", 'Hubbard|DFT.U')]:
            with self.subTest(replacement=replacement):
                with self.assertRaisesRegex(ValueError, expected):
                    generate_inputs(self.load(SCF.replace("input_dft='LDA'", replacement)), PhononSettings(task='raman'))
        self.pseudo('pseudo_type="PAW" functional="LDA"')
        with self.assertRaisesRegex(ValueError, 'NC'):
            generate_inputs(self.load(), PhononSettings(task='raman'))
        self.pseudo('pseudo_type="NC" functional="PBE"')
        with self.assertRaisesRegex(ValueError, 'LDA'):
            generate_inputs(self.load(), PhononSettings(task='raman'))

    def test_raman_uses_qe_default_pseudo_directory(self):
        default_dir = self.root / 'home' / 'espresso' / 'pseudo'
        default_dir.mkdir(parents=True)
        for label in ('C', 'O'):
            (default_dir / (label + '.upf')).write_text('<UPF><PP_HEADER pseudo_type="NC" functional="LDA"/></UPF>')
        scf = self.load(SCF.replace(", pseudo_dir='./pseudo'", ''))
        with patch.dict(os.environ, {}, clear=True), patch('pathlib.Path.home', return_value=self.root / 'home'):
            files = generate_inputs(scf, PhononSettings(task='raman'))
        self.assertIn('lraman = .true.', files['actual.ph.in'])

    def test_write_failure_restores_all_previous_contents(self):
        output = self.root / 'rollback'
        output.mkdir()
        (output / 'actual.ph.in').write_text('old ph\n')
        (output / 'actual.dynmat.in').write_text('old dynmat\n')
        actual_replace = os.replace
        calls = 0
        def interrupted(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('injected publication failure')
            return actual_replace(source, target)
        with patch('qbox.io.phonon_inputs.os.replace', side_effect=interrupted):
            with self.assertRaises(OSError):
                write_inputs(generate_inputs(self.load(), PhononSettings()), output, overwrite=True)
        self.assertEqual((output / 'actual.ph.in').read_text(), 'old ph\n')
        self.assertEqual((output / 'actual.dynmat.in').read_text(), 'old dynmat\n')

    def test_output_conflict_never_leaves_half_bundle(self):
        output = self.root / 'output'
        output.mkdir()
        (output / 'actual.dynmat.in').write_text('existing\n')
        files = generate_inputs(self.load(), PhononSettings())
        with self.assertRaisesRegex(ValueError, '已存在'):
            write_inputs(files, output)
        self.assertFalse((output / 'actual.ph.in').exists())
        self.assertEqual((output / 'actual.dynmat.in').read_text(), 'existing\n')
        written = write_inputs(files, output, overwrite=True)
        self.assertEqual({p.name for p in written}, set(files))
        self.assertEqual((output / 'actual.ph.in').read_text(), files['actual.ph.in'])


if __name__ == '__main__':
    unittest.main()
