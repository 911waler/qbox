"""Run guides continue from verified QE progress and preserve input names."""
from pathlib import Path
import tempfile
import unittest
from qbox.io.wannier_inputs import parse_qe
from qbox.io.wannier_readme import new_model_lines
from test_wannier_inputs import SCF


class ReadmeProgressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='qbox progress ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def guide(self, scf_done=False, nscf_done=False, data=True):
        progress = {kind: dict(input=str(self.root / filename), run_root=str(self.root),
                    completed=done, data_present=data, output=str(self.root / (kind + '.out')) if done else None)
                    for kind, filename, done in [('scf', 'original.scf.in', scf_done),
                                                ('nscf', 'old mesh.in', nscf_done)]}
        return '\n'.join(new_model_lines(
            dict(tasks=['model'], parameters={}, qe_progress=progress),
            seed='newname', version='3.1.0', qe=parse_qe(SCF), source_path=self.root/'original.scf.in',
            run_root=self.root, output_dir=self.root, outdir='./tmp', bases=['newname'], files={'newname.win': ''}))

    def test_completed_qe_with_data_starts_at_wannier_preprocessing(self):
        text = self.guide(True, True)
        self.assertNotIn('pw.x -in', text)
        self.assertIn('wannier90.x -pp newname', text)
        self.assertIn('SCF', text)
        self.assertIn('NSCF', text)
        self.assertIn('已完成', text)

    def test_scf_done_runs_only_the_existing_nscf_filename(self):
        text = self.guide(True, False)
        self.assertNotIn('original.scf.in > scf.out', text)
        self.assertIn("pw.x -in 'old mesh.in' > nscf.out", text)
        self.assertNotIn('newname.nscf.in', text)

    def test_missing_data_is_not_presented_as_ready_for_interface(self):
        text = self.guide(True, True, False)
        self.assertIn('缺少', text)
        self.assertIn('pw.x -in', text)


if __name__ == '__main__':
    unittest.main()
