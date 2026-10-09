"""Existing QE inputs remain authoritative and completion needs matching evidence."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from test_wannier_outputs import SCF, UPF, output


POINTS = 'K_POINTS crystal\n2\n.5 0 0 1\n0 0 0 1\n'
NSCF = SCF.replace("calculation='scf'", "calculation='nscf'").replace(
    'K_POINTS automatic\n2 2 2 0 0 0\n', POINTS)


def nscf_output(name='nscf.in', points='.5 0 0|0 0 0'):
    text = output(kind='nscf', input_name=name, eigenvalues=False)
    rows = points.split('|')
    listing = '\n'.join(f'k({index}) = ({point}), wk = 1.0'
                        for index, point in enumerate(rows, 1))
    return text.replace('number of k points= 2',
                        f'number of k points= {len(rows)}\ncryst. coord.\n{listing}')


class QEReuseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='qe reuse ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)
        self.source = self.root / 'scf.in'
        self.source.write_text(SCF)
        (self.root / 'pseudo').mkdir()
        (self.root / 'pseudo/Si.UPF').write_text(UPF)
        self.config = dict(source=str(self.source), seed='silicon',
                           run_root=str(self.root), grid=[8, 8, 8], nbnd=32,
                           source_output_mode='off', parameters={})

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.wannier_qe_reuse'),
                             'read-only existing QE reuse helper must exist')
        from qbox.io import wannier_qe_reuse
        return wannier_qe_reuse

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def test_adopts_existing_grid_bands_and_original_point_order_without_writing(self):
        nscf = self.write('nscf.in', NSCF)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in (self.source, nscf)}
        progress = self.api().inspect_qe(self.config)
        stage = progress['nscf']
        self.assertEqual(stage['input'], str(nscf))
        self.assertEqual(stage['grid'], [2, 1, 1])
        self.assertEqual(stage['kpoints'], [[.5, 0., 0.], [0., 0., 0.]])
        self.assertEqual(stage['nbnd'], 4)
        self.assertTrue(stage['reusable'])
        self.assertEqual(stage['sha256'], hashlib.sha256(nscf.read_bytes()).hexdigest())
        self.assertFalse(stage['completed'])
        self.api().adopt_nscf(self.config, progress)
        self.assertEqual(self.config['grid'], [2, 1, 1])
        self.assertEqual(self.config['nbnd'], 4)
        self.assertEqual(self.config['source_nscf'], str(nscf))
        self.assertEqual(self.config['qe_progress'], progress)
        json.dumps(progress)
        for path, snapshot in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), snapshot)

    def test_progress_scans_both_outputs_even_with_energy_import_off(self):
        self.write('nscf.in', NSCF)
        self.write('scf.out', output())
        self.write('nscf.out', nscf_output())
        progress = self.api().inspect_qe(self.config)
        self.assertTrue(progress['scf']['completed'])
        self.assertTrue(progress['nscf']['completed'])
        self.assertEqual(progress['nscf']['output'], str(self.root / 'nscf.out'))
        self.assertEqual(progress['scf']['output'], str(self.root / 'scf.out'))
        self.assertNotIn('fermi_energy', self.config['parameters'])

    def test_job_done_alone_does_not_prove_scf_or_nscf_completion(self):
        self.write('nscf.in', NSCF)
        self.write('scf.out', 'JOB DONE.\n')
        self.write('nscf.out', 'JOB DONE.\n')
        progress = self.api().inspect_qe(self.config)
        self.assertFalse(progress['scf']['completed'])
        self.assertFalse(progress['nscf']['completed'])

    def test_nscf_completion_must_match_actual_mesh_bands_and_input_order(self):
        self.write('nscf.in', NSCF)
        for invalid in (nscf_output(points='0 0 0|.25 0 0'),
                        nscf_output(points='0 0 0|.5 0 0'),
                        nscf_output().replace('states= 4', 'states= 5'),
                        output(kind='nscf', input_name='nscf.in', eigenvalues=False)):
            with self.subTest(output=invalid):
                self.write('nscf.out', invalid)
                self.assertFalse(self.api().inspect_qe(self.config)['nscf']['completed'])

    def test_nscf_can_itself_be_source_with_completed_output(self):
        source = self.write('nscf.in', NSCF)
        self.config['source'] = str(source)
        self.write('nscf.out', nscf_output())
        progress = self.api().inspect_qe(self.config)
        self.assertEqual(progress['nscf']['input'], str(source))
        self.assertTrue(progress['nscf']['completed'])
        from qbox.io.wannier_outputs import read_output
        self.assertEqual(read_output(self.root / 'nscf.out', source)['kind'], 'nscf')

    def test_nscf_source_can_recover_completed_scf_without_original_scf_input(self):
        source = self.write('nscf.in', NSCF)
        self.source.unlink()
        self.config['source'] = str(source)
        self.write('scf.out', output())
        result = self.api().inspect_qe(self.config)['scf']
        self.assertIsNone(result['input'])
        self.assertEqual(result['output'], str(self.root / 'scf.out'))
        self.assertTrue(result['completed'])

    def test_output_directory_input_resolves_its_rebased_paths_from_that_directory(self):
        destination = self.root / 'wannier-files'
        destination.mkdir()
        nscf = destination / 'nscf.in'
        nscf.write_text(NSCF.replace("pseudo_dir='./pseudo'", "pseudo_dir='../pseudo', outdir='..'"))
        result = self.api().inspect_qe(self.config, output_dir=destination)['nscf']
        self.assertEqual(result['input'], str(nscf))
        self.assertEqual(result['run_root'], str(destination))
        self.assertEqual(result['outdir'], str(self.root))

    def test_source_directory_is_searched_when_cwd_is_elsewhere(self):
        nscf = self.write('nscf.in', NSCF)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        os.chdir(elsewhere)
        result = self.api().inspect_qe(self.config)['nscf']
        self.assertEqual(result['input'], str(nscf))
        self.assertEqual(result['run_root'], str(self.root))

    def test_cartesian_output_list_can_prove_order_and_mesh(self):
        self.write('nscf.in', NSCF)
        text = nscf_output().replace('cryst. coord.\nk(1)', 'cart. coord. in units 2pi/alat\nk(1)')
        self.write('nscf.out', text)
        self.assertTrue(self.api().inspect_qe(self.config)['nscf']['completed'])

    def test_completed_output_for_other_input_is_not_adopted_as_this_nscf(self):
        self.write('nscf.in', NSCF)
        self.write('else.in', NSCF)
        self.write('else.out', nscf_output(name='else.in'))
        self.assertFalse(self.api().inspect_qe(self.config)['nscf']['completed'])

    def test_renamed_nscf_input_can_prove_completion_from_matching_output(self):
        source = self.write('silicon.nscf.in', NSCF)
        path = self.write('nscf.out', nscf_output(name='previous-name.in'))
        result = self.api().inspect_qe(self.config)['nscf']
        self.assertTrue(result['completed'])
        self.assertEqual(result['output'], str(path))
        from qbox.io.wannier_outputs import read_output
        self.assertEqual(read_output(path, source)['kind'], 'nscf')

    def test_renamed_input_fallback_requires_actual_mesh_order_and_band_count(self):
        source = self.write('silicon.nscf.in', NSCF)
        from qbox.io.wannier_outputs import read_output
        for invalid in (nscf_output(name='gone.in', points='0 0 0|.5 0 0'),
                        nscf_output(name='gone.in', points='.25 0 0|0 0 0'),
                        nscf_output(name='gone.in').replace('states= 4', 'states= 5'),
                        output(kind='nscf', input_name='gone.in', eigenvalues=False)):
            with self.subTest(output=invalid):
                path = self.write('nscf.out', invalid)
                with self.assertRaises(ValueError):
                    read_output(path, source)

    def test_renamed_input_cannot_verify_unprinted_hamiltonian_settings(self):
        path = self.write('nscf.out', nscf_output(name='gone.in'))
        from qbox.io.wannier_outputs import read_output
        for text in (NSCF + '\nHUBBARD (ortho-atomic)\nU Si-3p 2.0\n',
                     NSCF.replace('ibrav=0', "assume_isolated='2D', ibrav=0"),
                     NSCF.replace('ibrav=0', 'starting_magnetization(1)=.5, ibrav=0')):
            with self.subTest(input=text):
                source = self.write('silicon.nscf.in', text)
                with self.assertRaises(ValueError):
                    read_output(path, source)

    def test_scf_source_does_not_guess_nscf_type_from_missing_companion(self):
        self.write('silicon.nscf.in', NSCF)
        path = self.write('nscf.out', nscf_output(name='gone.in'))
        from qbox.io.wannier_outputs import read_output
        with self.assertRaises(ValueError):
            read_output(path, self.source)

    def test_scf_output_with_same_mesh_is_not_misclassified_by_nscf_fallback(self):
        source = self.write('silicon.nscf.in', NSCF)
        self.source.unlink()
        text = nscf_output(name='gone.in').replace(
            'Band Structure Calculation\nEnd of band structure calculation',
            'Self-consistent Calculation\nEnd of self-consistent calculation')
        text = text.replace('JOB DONE.', 'convergence has been achieved in 6 iterations\nJOB DONE.')
        path = self.write('scf.out', text)
        from qbox.io.wannier_outputs import read_output
        self.assertEqual(read_output(path, source)['kind'], 'scf')

    def test_malformed_or_mismatched_preferred_input_is_preserved_and_reported(self):
        self.write('other.in', NSCF)
        for invalid in ('&SYSTEM broken /\n', NSCF.replace('ecutwfc=40', 'ecutwfc=50'),
                        NSCF.replace('Si .25 .25 .25', 'Si .2 .25 .25'),
                        NSCF.replace('ibrav=0', "input_dft='LDA', ibrav=0"),
                        NSCF.replace('Si.UPF', 'Other.UPF')):
            with self.subTest(input=invalid):
                path = self.write('silicon.nscf.in', invalid)
                with self.assertRaisesRegex(ValueError, 'silicon.nscf.in'):
                    self.api().inspect_qe(self.config)
                self.assertEqual(path.read_text(), invalid)

    def test_multiple_compatible_inputs_are_ambiguous(self):
        first = self.write('dense-a.in', NSCF)
        second = self.write('dense-b.in', NSCF)
        with self.assertRaises(ValueError) as raised:
            self.api().inspect_qe(self.config)
        self.assertIn(str(first), str(raised.exception))
        self.assertIn(str(second), str(raised.exception))

    def test_preferred_input_wins_over_other_compatible_nonpreferred_inputs(self):
        self.write('dense.in', NSCF)
        selected = self.write('silicon.nscf.in', NSCF)
        self.assertEqual(self.api().inspect_qe(self.config)['nscf']['input'], str(selected))

    def test_partial_shifted_or_unequal_weight_mesh_is_not_reusable(self):
        for card in ('K_POINTS crystal\n3\n0 0 0 1\n.5 0 0 1\n0 .5 0 1\n',
                     'K_POINTS crystal\n2\n.25 0 0 1\n.75 0 0 1\n',
                     'K_POINTS crystal\n2\n0 0 0 1\n.5 0 0 2\n'):
            with self.subTest(card=card):
                path = self.write('nscf.in', NSCF.replace(POINTS, card))
                with self.assertRaisesRegex(ValueError, 'nscf.in'):
                    self.api().inspect_qe(self.config)
                self.assertEqual(path.read_text(), NSCF.replace(POINTS, card))

    def test_automatic_mesh_needs_completed_output_order_and_never_rewrites_input(self):
        text = NSCF.replace(POINTS, 'K_POINTS automatic\n2 1 1 0 0 0\n')
        path = self.write('nscf.in', text)
        with self.assertRaisesRegex(ValueError, 'automatic|顺序'):
            self.api().inspect_qe(self.config)
        self.write('nscf.out', nscf_output())
        result = self.api().inspect_qe(self.config)['nscf']
        self.assertEqual(result['kpoints'], [[.5, 0., 0.], [0., 0., 0.]])
        self.assertTrue(result['completed'])
        self.assertEqual(path.read_text(), text)

    def test_restart_files_are_reported_separately_from_convergence(self):
        self.source.write_text(SCF.replace("calculation='scf'", "calculation='scf', prefix='si', outdir='./scratch'"))
        self.write('nscf.in', NSCF.replace("calculation='nscf'", "calculation='nscf', prefix='si', outdir='./scratch', wfcdir='./waves'"))
        (self.root / 'scratch/si.save').mkdir(parents=True)
        (self.root / 'scratch/si.save/data-file-schema.xml').write_text('<espresso/>')
        (self.root / 'scratch/si.save/charge-density.dat').write_bytes(b'density')
        (self.root / 'waves').mkdir()
        (self.root / 'waves/si.wfc1').write_bytes(b'waves')
        result = self.api().inspect_qe(self.config)
        self.assertTrue(result['scf']['data_present'])
        self.assertFalse(result['nscf']['data_present'])
        self.assertIn(str(self.root / 'waves/si.wfc1'), result['nscf']['data_files'])
        self.assertIn('完整性未确认', result['nscf']['data_note'])
        self.assertFalse(result['scf']['completed'])
        self.assertFalse(result['nscf']['completed'])
        self.assertEqual(result['nscf']['outdir'], str(self.root / 'scratch'))
        self.assertEqual(result['nscf']['wfcdir'], str(self.root / 'waves'))

    def test_nscf_data_needs_nonempty_xml_and_all_collected_wavefunctions(self):
        self.write('nscf.in', NSCF)
        save = self.root / 'pwscf.save'
        save.mkdir()
        xml = save / 'data-file-schema.xml'
        xml.write_text('<espresso/>')
        (save / 'wfc1.dat').write_bytes(b'first wave')
        self.assertFalse(self.api().inspect_qe(self.config)['nscf']['data_present'])
        (save / 'wfc2.dat').write_bytes(b'')
        self.assertFalse(self.api().inspect_qe(self.config)['nscf']['data_present'])
        (save / 'wfc2.dat').write_bytes(b'second wave')
        self.assertTrue(self.api().inspect_qe(self.config)['nscf']['data_present'])
        xml.write_text('')
        self.assertFalse(self.api().inspect_qe(self.config)['nscf']['data_present'])

    def test_collinear_data_needs_complete_up_and_down_channel_wavefunctions(self):
        self.source.write_text(SCF.replace('ibrav=0', 'nspin=2, ibrav=0'))
        self.write('nscf.in', NSCF.replace('ibrav=0', 'nspin=2, ibrav=0'))
        save = self.root / 'pwscf.save'
        save.mkdir()
        (save / 'data-file-schema.xml').write_text('<espresso/>')
        for name in ('wfcup1.dat', 'wfcup2.dat', 'wfcdw1.dat'):
            (save / name).write_bytes(b'wave')
        self.assertFalse(self.api().inspect_qe(self.config)['nscf']['data_present'])
        (save / 'wfcdw2.dat').write_bytes(b'wave')
        self.assertTrue(self.api().inspect_qe(self.config)['nscf']['data_present'])

    def test_no_existing_nscf_leaves_basis_choices_unchanged(self):
        progress = self.api().inspect_qe(self.config)
        self.assertIsNone(progress['nscf']['input'])
        self.assertFalse(progress['nscf']['reusable'])
        self.api().adopt_nscf(self.config, progress)
        self.assertEqual((self.config['grid'], self.config['nbnd']), ([8, 8, 8], 32))


if __name__ == '__main__':
    unittest.main()
