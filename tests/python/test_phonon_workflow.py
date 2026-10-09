"""The phonon execution workspace owns only its files and validates real products."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qbox.io import phonon_workflow as workflow
from qbox.io.phonon_inputs import load_scf


SCF = """&CONTROL calculation='scf', prefix='silicon', outdir='../old-tmp',
 pseudo_dir='./pseudo', wfcdir='../old-wfc' /
&SYSTEM ibrav=0, nat=2, ntyp=1, ecutwfc=20, occupations='fixed' /
&ELECTRONS conv_thr=1d-10 /
ATOMIC_SPECIES
Si 28.085 Si.upf
CELL_PARAMETERS angstrom
0 2.7 2.7
2.7 0 2.7
2.7 2.7 0
ATOMIC_POSITIONS crystal
Si 0 0 0
Si .25 .25 .25
K_POINTS automatic
2 2 2 0 0 0
"""
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD1sAAAAASUVORK5CYII=')


class PhononWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.original = self.root / 'source'
        self.original.mkdir()
        (self.original / 'pseudo').mkdir()
        (self.original / 'pseudo' / 'Si.upf').write_text('<UPF><PP_HEADER pseudo_type="NC" functional="PBE"/></UPF>')
        self.source = self.original / 'structure.scf.in'
        self.source.write_text(SCF)
        self.directory = self.root / 'PHONON'

    def prepare(self, answers=('3', ''), source=None):
        iterator = iter(answers)
        output = []
        result = workflow.prepare(self.directory, self.source if source is None else source,
                                  input_fn=lambda _: next(iterator), output=output.append)
        self.assertEqual(result, 0, '\n'.join(output))
        return json.loads((self.directory / '.qbox-phonon.json').read_text())

    def manifest(self):
        return json.loads((self.directory / '.qbox-phonon.json').read_text())

    def products(self, stage):
        (self.directory / (stage + '.out')).write_text(
            ('convergence has been achieved in 8 iterations\n' if stage == 'scf' else '') + 'JOB DONE.\n')
        if stage == 'scf':
            saved = self.directory / 'tmp' / 'silicon.save'
            saved.mkdir(parents=True, exist_ok=True)
            (saved / 'data-file-schema.xml').write_text('<espresso><output/></espresso>')
            (saved / 'charge-density.dat').write_bytes(b'charge data')
            (saved / 'wfc1.dat').write_bytes(b'wave function data')
        elif stage == 'ph':
            (self.directory / 'silicon.dyn0').write_text('4 4 4\n1\n0 0 0\n')
            (self.directory / 'silicon.dyn1').write_text('Dynamical matrix file\nforce constants\n')
        elif stage == 'q2r':
            (self.directory / 'silicon.fc').write_text('interatomic force constants\n')
        elif stage == 'matdyn':
            meta = json.loads((self.directory / 'silicon.path.json').read_text())
            rows = meta['qpoints_matdyn']
            text = f'&plot nbnd=6, nks={len(rows)} /\n'
            for row in rows:
                text += ' '.join(f'{v:.8f}' for v in row) + '\n-1 0 1 2 3 4\n'
            (self.directory / 'silicon.freq').write_text(text)
            (self.directory / 'silicon.freq.gp').write_text(''.join(f'{i} -1 0 1 2 3 4\n' for i in range(len(rows))))
        elif stage == 'plot':
            (self.directory / 'silicon_phonon.png').write_bytes(PNG)
            (self.directory / 'silicon_phonon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

    def complete(self, stage):
        workflow.begin(self.directory, stage)
        self.products(stage)
        workflow.finish(self.directory, stage)
        self.assertTrue(workflow.check(self.directory, stage))

    def test_prepare_moves_runtime_paths_but_never_changes_source(self):
        manifest = self.prepare()
        self.assertEqual(self.source.read_text(), SCF)
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'source', 'PHONON'})
        copied = load_scf(self.directory / 'silicon.scf.in')
        self.assertEqual(copied.outdir, str(self.directory / 'tmp'))
        self.assertEqual(copied.get('control', 'wfcdir'), str(self.directory / 'tmp'))
        self.assertEqual(copied.get('control', 'pseudo_dir'), str(self.original / 'pseudo'))
        self.assertIn("outdir = '" + str(self.directory / 'tmp') + "'", (self.directory / 'silicon.ph.in').read_text())
        self.assertEqual(manifest['file_prefix'], 'silicon')
        self.assertFalse(workflow.check(self.directory, 'scf'))

    def test_prepare_cancellation_has_distinct_status_and_no_files(self):
        result = workflow.prepare(self.directory, self.source,
                                  input_fn=lambda _: '5', output=lambda _: None)
        self.assertEqual(result, 10)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.source.read_text(), SCF)

    def test_isolated_copy_starts_fresh_and_preserves_ph_wavefunctions(self):
        original = SCF.replace("calculation='scf',", "calculation='scf', restart_mode='restart', disk_io='none',")
        original = original.replace('conv_thr=1d-10', "conv_thr=1d-10, startingpot='file', startingwfc='file'")
        self.source.write_text(original)
        self.prepare()
        copied = load_scf(self.directory / 'silicon.scf.in')
        self.assertEqual(copied.get('control', 'restart_mode'), 'from_scratch')
        self.assertEqual(copied.get('control', 'disk_io'), 'low')
        self.assertEqual(copied.get('electrons', 'startingpot'), 'atomic')
        self.assertEqual(copied.get('electrons', 'startingwfc'), 'atomic+random')
        self.assertEqual(self.source.read_text(), original)

    def test_cif_wizard_cancel_and_failure_do_not_publish_partial_workflow(self):
        cif = self.original / 'structure.cif'
        cif.write_text('data_test\n')
        # No candidate is available, so exercise the external wizard boundary.
        with patch('qbox.io.phonon_menu._scf_candidates', return_value=[]):
            with patch('qbox.io.wannier_cif.generate_scf_from_cif', return_value=None):
                self.assertEqual(workflow.prepare(self.directory, cif, output=lambda _: None), 10)
            with patch('qbox.io.wannier_cif.generate_scf_from_cif', side_effect=ValueError('wizard failed')):
                self.assertEqual(workflow.prepare(self.directory, cif, output=lambda _: None), 1)
        self.assertFalse(self.directory.exists())

    def test_existing_foreign_directory_is_not_overwritten(self):
        self.directory.mkdir()
        user_file = self.directory / 'silicon.scf.in'
        user_file.write_text('foreign data')
        self.assertEqual(workflow.prepare(self.directory, self.source, output=lambda _: None), 1)
        self.assertEqual(user_file.read_text(), 'foreign data')
        self.assertFalse((self.directory / '.qbox-phonon.json').exists())

    def test_manifest_reuse_and_reconfigure_cancel_keep_inputs(self):
        self.prepare()
        original = (self.directory / 'silicon.ph.in').read_bytes()
        self.prepare(answers=('0',))
        iterator = iter(('1', '5'))
        self.assertEqual(workflow.prepare(self.directory, self.source,
                         input_fn=lambda _: next(iterator), output=lambda _: None), 10)
        self.assertEqual((self.directory / 'silicon.ph.in').read_bytes(), original)

    def test_new_or_changed_explicit_source_cannot_silently_reuse_old_system(self):
        self.prepare()
        old_manifest = (self.directory / '.qbox-phonon.json').read_bytes()
        other = self.original / 'other.scf.in'
        other.write_text(SCF)
        for source in (other, self.source):
            if source == self.source:
                source.write_text(SCF.replace('ecutwfc=20', 'ecutwfc=30'))
            answers = iter(('0', '2'))
            output = []
            result = workflow.prepare(self.directory, source, input_fn=lambda _: next(answers), output=output.append)
            self.assertEqual(result, 10)
            self.assertTrue(any('来源' in line for line in output))
            self.assertEqual((self.directory / '.qbox-phonon.json').read_bytes(), old_manifest)

    def write_cif(self):
        from pymatgen.core import Structure
        scf = load_scf(self.source)
        cif = self.original / 'structure.cif'
        Structure(scf.cell, [label for label, _ in scf.atoms],
                  [position for _, position in scf.atoms]).to(filename=str(cif))
        return cif

    def test_cif_external_scf_changes_require_reconfiguration(self):
        cif = self.write_cif()
        self.prepare(answers=('', '3', ''), source=cif)
        original_manifest = (self.directory / '.qbox-phonon.json').read_bytes()
        self.assertFalse(self.manifest()['source']['generated_from_cif'])
        self.prepare(answers=('0',), source=cif)
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    self.source.unlink()
                else:
                    self.source.write_text(SCF.replace('ecutwfc=20', 'ecutwfc=30'))
                answers = iter(('0', '2'))
                output = []
                result = workflow.prepare(self.directory, cif, input_fn=lambda _: next(answers), output=output.append)
                self.assertEqual(result, 10)
                self.assertTrue(any('SCF' in line and '来源' in line for line in output))
                self.assertEqual((self.directory / '.qbox-phonon.json').read_bytes(), original_manifest)

    def test_cif_generated_scf_does_not_compare_pre_relocation_hash_to_working_copy(self):
        cif = self.write_cif()

        def generate(_cif, *, output_dir, **_kwargs):
            generated = Path(output_dir) / 'generated.scf.in'
            generated.write_text(SCF.replace("'./pseudo'", repr(str(self.original / 'pseudo'))))
            return generated

        with patch('qbox.io.phonon_menu._scf_candidates', return_value=[]), \
                patch('qbox.io.wannier_cif.generate_scf_from_cif', side_effect=generate):
            self.prepare(source=cif)
        self.assertTrue(self.manifest()['source']['generated_from_cif'])
        working = self.directory / 'silicon.scf.in'
        working.write_text(working.read_text().replace('ecutwfc=20', 'ecutwfc=30'))
        self.assertEqual(load_scf(working).get('system', 'ecutwfc'), 30)
        self.prepare(answers=('0',), source=cif)

    def test_spin_polarized_collected_wavefunctions_require_both_channels(self):
        self.source.write_text(SCF.replace('ntyp=1,', 'ntyp=1, nspin=2,'))
        self.prepare()
        workflow.begin(self.directory, 'scf')
        self.products('scf')
        saved = self.directory / 'tmp' / 'silicon.save'
        (saved / 'wfc1.dat').rename(saved / 'wfcup1.dat')
        with self.assertRaises(ValueError):
            workflow.finish(self.directory, 'scf')
        (saved / 'wfcdw1.dat').write_bytes(b'down spin wavefunction')
        workflow.finish(self.directory, 'scf')
        self.assertTrue(workflow.check(self.directory, 'scf'))

    def test_changed_pseudopotential_invalidates_scf_and_downstream(self):
        self.prepare()
        self.complete('scf')
        self.complete('ph')
        (self.original / 'pseudo' / 'Si.upf').write_text('<UPF>different pseudo</UPF>')
        self.assertFalse(workflow.check(self.directory, 'scf'))
        self.assertFalse(workflow.check(self.directory, 'ph'))

    def test_finish_needs_begin_success_log_and_actual_scf_data(self):
        self.prepare()
        self.products('scf')
        with self.assertRaises(ValueError):
            workflow.finish(self.directory, 'scf')
        workflow.begin(self.directory, 'scf')
        self.assertFalse((self.directory / 'scf.out').exists())
        with self.assertRaises(ValueError):
            workflow.finish(self.directory, 'scf')
        self.products('scf')
        (self.directory / 'tmp' / 'silicon.save' / 'charge-density.dat').unlink()
        with self.assertRaises(ValueError):
            workflow.finish(self.directory, 'scf')
        self.assertFalse(workflow.check(self.directory, 'scf'))
        self.assertNotEqual(self.manifest()['stages']['scf']['status'], 'complete')

    def test_changed_input_invalidates_its_stage_and_all_downstream_cache(self):
        self.prepare()
        for stage in workflow.STAGES:
            self.complete(stage)
        ph = self.directory / 'silicon.ph.in'
        ph.write_text(ph.read_text().replace('1d-12', '2d-12'))
        self.assertTrue(workflow.check(self.directory, 'scf'))
        self.assertFalse(workflow.check(self.directory, 'ph'))
        self.assertFalse(workflow.check(self.directory, 'matdyn'))
        self.assertFalse(workflow.check(self.directory, 'plot'))

    def test_begin_recalculation_cleans_owned_outputs_and_keeps_other_files(self):
        self.prepare()
        for stage in workflow.STAGES:
            self.complete(stage)
        keep = self.directory / 'notes.txt'
        keep.write_text('keep this note')
        workflow.begin(self.directory, 'ph')
        for name in ('ph.out', 'silicon.dyn0', 'silicon.dyn1', 'silicon.fc',
                     'silicon.freq', 'silicon.freq.gp', 'silicon_phonon.png'):
            self.assertFalse((self.directory / name).exists(), name)
        self.assertTrue((self.directory / 'tmp' / 'silicon.save').is_dir())
        self.assertEqual(keep.read_text(), 'keep this note')

    def test_missing_or_changed_upstream_products_prevent_downstream_skip(self):
        self.prepare()
        self.complete('scf')
        self.complete('ph')
        (self.directory / 'silicon.dyn1').unlink()
        self.assertFalse(workflow.check(self.directory, 'ph'))
        with self.assertRaises(ValueError):
            workflow.begin(self.directory, 'q2r')

    def test_ph_runtime_wavefunction_copy_does_not_change_saved_scf_products(self):
        self.prepare()
        self.complete('scf')
        workflow.begin(self.directory, 'ph')
        # Native ph.x reconstructs this scratch file from the collected save data.
        (self.directory / 'tmp' / 'silicon.wfc1').write_bytes(b'PH runtime copy')
        self.products('ph')
        workflow.finish(self.directory, 'ph')
        self.assertTrue(workflow.check(self.directory, 'scf'))
        self.assertTrue(workflow.check(self.directory, 'ph'))
        (self.directory / 'tmp' / 'silicon.save' / 'wfc1.dat').write_bytes(b'changed SCF wavefunction')
        self.assertFalse(workflow.check(self.directory, 'scf'))
        self.assertFalse(workflow.check(self.directory, 'ph'))

    def test_incomplete_ph_grid_and_matdyn_data_never_record_success(self):
        self.prepare()
        self.complete('scf')
        workflow.begin(self.directory, 'ph')
        self.products('ph')
        (self.directory / 'silicon.dyn0').write_text('4 4 4\n2\n0 0 0\n0.5 0 0\n')
        with self.assertRaises(ValueError):
            workflow.finish(self.directory, 'ph')
        self.products('ph')
        workflow.finish(self.directory, 'ph')
        self.complete('q2r')
        workflow.begin(self.directory, 'matdyn')
        self.products('matdyn')
        (self.directory / 'silicon.freq.gp').write_text('0 1\n')
        with self.assertRaises(ValueError):
            workflow.finish(self.directory, 'matdyn')

    def test_symlinks_and_manifest_path_escape_are_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.directory.symlink_to(outside, target_is_directory=True)
        self.assertEqual(workflow.prepare(self.directory, self.source, output=lambda _: None), 1)
        self.directory.unlink()
        self.prepare()
        sentinel = outside / 'sentinel'
        sentinel.write_text('safe')
        (self.directory / 'scf.out').symlink_to(sentinel)
        with self.assertRaises(ValueError):
            workflow.begin(self.directory, 'scf')
        self.assertEqual(sentinel.read_text(), 'safe')
        manifest = self.manifest()
        manifest['file_prefix'] = '../outside/sentinel'
        (self.directory / '.qbox-phonon.json').write_text(json.dumps(manifest))
        self.assertFalse(workflow.check(self.directory, 'scf'))


if __name__ == '__main__':
    unittest.main()
