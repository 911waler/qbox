"""Existing QE inputs remain authoritative and are never publication targets."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from qbox.io.wannier_workflow import initial_config, prepare, _win_parts
from qbox.io.wannier_publish import publish
from test_wannier_inputs import SCF, config


class QEReuseIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='qbox reused QE ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scf = self.root / 'iron.scf.in'
        self.nscf = self.root / 'iron.nscf.in'
        self.scf.write_text(SCF)
        self.nscf_text = SCF.replace("calculation = 'scf'", "calculation = 'nscf'").replace(
            'K_POINTS automatic\n4 4 4 0 0 0',
            'K_POINTS crystal\n4\n0.5 0 0.5 0.25\n0 0 0 0.25\n0.5 0 0 0.25\n0 0 0.5 0.25')
        self.nscf.write_text(self.nscf_text)
        self.cfg = config(source=str(self.scf), run_root=str(self.root), source_output_mode='off')

    def test_existing_nscf_is_reused_without_write_or_backup_and_keeps_point_order(self):
        files = prepare(self.cfg, self.root)
        self.assertNotIn('iron.nscf.in', files)
        _, blocks = _win_parts(files['iron.win'])
        points = [list(map(float, line.split())) for line in blocks['kpoints']]
        self.assertEqual(points, [[.5, 0, .5], [0, 0, 0], [.5, 0, 0], [0, 0, .5]])
        publish(files, self.root)
        self.assertEqual(self.scf.read_text(), SCF)
        self.assertEqual(self.nscf.read_text(), self.nscf_text)
        self.assertFalse((self.root / 'bak').exists())

    def test_startup_adopts_the_existing_mesh_and_band_count(self):
        self.nscf.write_text(self.nscf_text.replace('nbnd=12', 'nbnd=16'))
        cfg = initial_config(self.scf)
        self.assertEqual(cfg['grid'], [2, 1, 2])
        self.assertEqual(cfg['nbnd'], 16)
        self.assertEqual(cfg['qe_progress']['nscf']['input'], str(self.nscf))

    def test_manual_mesh_or_band_changes_do_not_rewrite_existing_qe(self):
        for changes in ({'grid': [4, 1, 2]}, {'nbnd': 16}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'NSCF|nscf'):
                prepare({**self.cfg, **changes}, self.root)
        self.assertEqual(self.nscf.read_text(), self.nscf_text)

    def test_nscf_can_be_the_source_without_generating_scf_or_nscf(self):
        self.scf.unlink()
        self.cfg['source'] = str(self.nscf)
        files = prepare(self.cfg, self.root)
        self.assertFalse(any(name.endswith(('.scf.in', '.nscf.in')) for name in files))
        guide = files['iron.README.txt']
        self.assertNotIn('iron.nscf.in > scf.out', guide)
        self.assertIn('iron.nscf.in', guide)

    def test_missing_nscf_is_generated_only_once(self):
        self.nscf.unlink()
        first = prepare(self.cfg, self.root)
        self.assertIn('iron.nscf.in', first)
        self.nscf.write_text(first['iron.nscf.in'])
        self.assertNotIn('iron.nscf.in', prepare(self.cfg, self.root))

    def test_publication_rejects_changed_reused_input(self):
        record = {'config': {'qe_progress': {'nscf': {
            'input': str(self.nscf),
            'sha256': hashlib.sha256(self.nscf.read_bytes()).hexdigest()}}}}
        files = {'iron.win': 'model', 'iron.qbox.json': json.dumps(record)}
        self.nscf.write_text(self.nscf_text + '\n! changed after preparation\n')
        with self.assertRaisesRegex(ValueError, '变化|改动|changed'):
            publish(files, self.root)
        self.assertFalse((self.root / 'iron.win').exists())

    def test_fixed_occupation_nscf_is_the_richer_energy_reference_before_task_selection(self):
        from qbox.io.wannier_output_defaults import preferred_records
        scf = dict(path='scf.out', kind='scf', fermi_energy=None, homo=1.)
        nscf = dict(path='nscf.out', kind='nscf', fermi_energy=None, homo=1., lumo=3.,
                    gap_reference=dict(method='sampled_midgap', value_eV=2.))
        self.assertEqual(preferred_records({'tasks': ['optical']}, [scf, nscf]), [nscf])


if __name__ == '__main__':
    unittest.main()
