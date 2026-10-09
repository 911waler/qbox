"""Presentation changes retain the generated Wannier model and point order."""
import hashlib
import json
import re
import unittest

from qbox.io.wannier_inputs import build_bundle, _win_model, parse_qe
from qbox.io.wannier_profiles import render_profile
from qbox.io.wannier_workflow import _win_parts, _basis
from test_wannier_inputs import SCF, config


class WannierFormatTests(unittest.TestCase):
    def test_new_model_has_aligned_parameters_and_keeps_long_mesh_last(self):
        cfg = config(tasks=['shift_current'], windows={'dis_win_min': -6., 'dis_win_max': 30.,
                      'dis_froz_min': 5., 'dis_froz_max': 15.},
                     parameters={'fermi_energy': 10.4551, 'kubo_freq_max': 8., 'kubo_eigval_max': 25.,
                                 'kpoint_path': ['GAMMA 0 0 0 M .499999999936 8.51590174581e-11 0']})
        files = build_bundle(SCF, cfg)
        win = files['iron.win']
        assignments = [line for line in win.splitlines() if re.match(r'^\w+\s*=', line)]
        self.assertEqual(len({line.index('=') for line in assignments}), 1)
        content = [line for line in win.splitlines() if line.strip() and not line.startswith('#')]
        self.assertEqual(content[-1], 'end kpoints')
        self.assertLess(win.index('berry_task'), win.index('begin unit_cell_cart'))
        self.assertLess(win.index('begin kpoint_path'), win.index('begin kpoints'))
        self.assertLess(win.index('dis_win_min'), win.index('dis_win_max'))
        self.assertLess(win.index('dis_froz_min'), win.index('dis_froz_max'))
        self.assertIn('# BERRY\n' + '#' * 80 + '\n', win)
        record = json.loads(files['iron.qbox.json'])
        self.assertEqual(record['model_sha256']['iron'], hashlib.sha256(_basis(win).encode()).hexdigest())

    def test_scalar_parameters_and_all_model_rows_survive_formatting(self):
        cfg = config(grid=[3, 1, 2], tasks=['shift_current'],
                     parameters={'fermi_energy': 3.5, 'kubo_freq_max': 8., 'kubo_eigval_max': 12.,
                                 'kpoint_path': ['GAMMA 0 0 0 K .333333333333 .666666666667 0']})
        source = SCF.replace('Fe1 0 0 0 1 1 1', 'Fe1 -3.7309351099113e-08 .9999999253813 .000449555616 1 1 1')
        qe = parse_qe(source)
        original = '\n'.join(_win_model(qe, cfg, tuple(cfg['grid']), cfg['nbnd'], None)
                             + list(render_profile(cfg['tasks'], cfg['parameters'], 'scalar').win_lines))
        formatted = build_bundle(source, cfg)['iron.win']
        before, old_blocks = _win_parts(original)
        after, new_blocks = _win_parts(formatted)
        self.assertEqual(before, after)
        self.assertEqual(set(old_blocks), set(new_blocks))
        for block, old_rows in old_blocks.items():
            self.assertEqual(len(old_rows), len(new_blocks[block]))
            for old, new in zip(old_rows, new_blocks[block]):
                for old_token, new_token in zip(old.split(), new.split(), strict=True):
                    try:
                        old_number = float(old_token)
                    except ValueError:
                        self.assertEqual(old_token, new_token)
                    else:
                        self.assertAlmostEqual(old_number, float(new_token), delta=5.01e-11)
        for block in ('unit_cell_cart', 'atoms_frac', 'kpoints', 'kpoint_path'):
            for row in new_blocks[block]:
                for token in row.split():
                    try:
                        float(token)
                    except ValueError:
                        continue
                    self.assertRegex(token, r'^-?\d+\.\d{10}$')
        self.assertIn('-0.0000000373', formatted)

    def test_deferred_response_notice_is_preserved_before_geometry(self):
        files = build_bundle(SCF, config(tasks=['shift_current'],
                                        parameters={'kpoint_path': ['G 0 0 0 X .5 0 0']}))
        win = files['iron.win']
        self.assertLess(win.index('occupation reference pending'), win.index('begin unit_cell_cart'))
        self.assertEqual(_win_parts(win)[0]['berry_task'], 'sc')


if __name__ == '__main__':
    unittest.main()
