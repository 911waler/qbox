"""The emitted command sequence must keep model construction separate from SC readiness."""
from pathlib import Path
import shlex
import tempfile
import unittest

from qbox.io.wannier_inputs import parse_qe
from qbox.io.wannier_readme import new_model_lines
from qbox.io.wannier_workflow import _win_parts
from test_wannier_inputs import SCF


class ShiftCurrentReadmeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='qbox SC guide ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def guide(self, **updates):
        config = dict(tasks=['shift_current'], parameters={})
        config.update(updates)
        lines = new_model_lines(
            config, seed='sample', version='3.1.0', qe=parse_qe(SCF),
            source_path=self.root / 'sample.scf.in', run_root=self.root,
            output_dir=self.root, outdir='./tmp', bases=['sample'],
            files={'sample.nscf.in': '', 'sample.win': '', 'sample.pw2wan': ''})
        return [shlex.split(line) for line in lines
                if line.startswith(('mpirun ', 'wannier90.x ')) or '--task wannier-input' in line]

    def test_missing_occupation_reference_allows_full_model_but_blocks_response(self):
        commands = self.guide(pending_fermi=True)
        programs = [line[3] if line[:2] == ['mpirun', '-np'] else line[0]
                    for line in commands]
        self.assertEqual(programs[:5], ['pw.x', 'pw.x', 'wannier90.x',
                                       'pw2wannier90.x', 'wannier90.x'])
        self.assertIn('--task', commands[5])
        self.assertIn('--interactive', commands[5])
        self.assertNotIn('postw90.x', programs)
        self.assertIn(['wannier90.x', '-pp', 'sample'], commands)

    def test_known_fermi_does_not_enable_response_with_unset_spectral_limits(self):
        commands = self.guide(
            parameters={'fermi_energy': 3.5},
            pending_response_parameters=['kubo_freq_max', 'kubo_eigval_max'])
        self.assertTrue(any(command[:5] == ['mpirun', '-np', '4', 'wannier90.x', 'sample']
                            for command in commands))
        self.assertFalse(any('postw90.x' in command for command in commands))
        self.assertIn('--interactive', commands[-1])
        self.assertEqual(commands[-1][commands[-1].index('--config') + 1], 'sample.qbox.json')

    def test_complete_response_runs_after_the_matching_model(self):
        commands = self.guide(parameters=dict(fermi_energy=3.5, kubo_freq_max=6.,
                                             kubo_eigval_max=10.))
        self.assertEqual(commands[-2], ['mpirun', '-np', '4', 'wannier90.x', 'sample'])
        self.assertEqual(commands[-1], ['mpirun', '-np', '4', 'postw90.x', 'sample'])
        self.assertFalse(any('--task' in command for command in commands))

    def test_readme_accepts_the_numeric_string_values_supported_by_profiles(self):
        commands = self.guide(parameters=dict(fermi_energy='3.5', kubo_freq_max='6',
                                             kubo_eigval_max='10'))
        self.assertEqual(commands[-1], ['mpirun', '-np', '4', 'postw90.x', 'sample'])

    def test_existing_shift_model_exports_interpolated_bands_before_response(self):
        from qbox.io.wannier_workflow import initial_config, prepare
        from test_wannier_workflow import WIN
        source = self.root / 'sample.win'
        source.write_text(WIN)
        config = initial_config(source)
        config.update(tasks=['shift_current'], parameters={
            'fermi_energy': 0., 'kubo_freq_max': 3., 'kubo_eigval_max': 4.,
            'kpoint_path': ['G 0 0 0 X 0.5 0 0']})
        guide = prepare(config, self.root)['sample.README.txt']
        commands = [shlex.split(line) for line in guide.splitlines() if line.startswith('mpirun ')]
        self.assertEqual(commands[-2:], [
            ['mpirun', '-np', '4', 'wannier90.x', 'sample'],
            ['mpirun', '-np', '4', 'postw90.x', 'sample']])

    def test_bundle_readme_keeps_explicit_fortran_exponent_energy_values(self):
        from qbox.io.wannier_inputs import build_bundle
        from test_wannier_inputs import config
        files = build_bundle(SCF, config(tasks=['shift_current'], parameters={
            'fermi_energy': '3.5D0', 'kubo_freq_min': '1d0', 'kubo_freq_max': '8d0',
            'kubo_eigval_max': '12D0', 'kpoint_path': ['G 0 0 0 X 0.5 0 0']}))
        values, _ = _win_parts(files['iron.win'])
        self.assertEqual(values['kubo_freq_max'], '8')
        self.assertEqual(values['kubo_eigval_max'], '12')
        self.assertIn('Photon energy: 1–8 eV', files['iron.README.txt'])
        self.assertIn('Initial/final-state cutoff: 12 eV', files['iron.README.txt'])


if __name__ == '__main__':
    unittest.main()
