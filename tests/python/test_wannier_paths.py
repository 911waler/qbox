"""Paths retain the input reciprocal basis and disconnected branches."""
from pathlib import Path
import importlib.util
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from qbox.io.wannier_paths import normalize_path, qe_path_card, read_band_kpt, qe_band_kpt_card, automatic_path

class PathTests(unittest.TestCase):
    def test_path_break_is_not_joined(self):
        path = ['G 0 0 0 X .5 0 0','L .5 .5 .5 W .5 .25 .75']
        card = qe_path_card(path,20)
        rows = card.splitlines()
        self.assertEqual(rows[:2], ['K_POINTS crystal_b','4'])
        self.assertEqual([row.split()[3] for row in rows[2:]], ['20','0','20','1'])

    def test_structured_path_and_bad_coordinates(self):
        segments = normalize_path([dict(start_label='G',start=[0,0,0],end_label='X',end=[.5,0,0])])
        self.assertEqual(segments[0].end,(.5,0.,0.))
        for path in [[], ['G 0 0 nan X .5 0 0'], ['G 0 0 0 X 0 0 0'], ['bad']]:
            with self.subTest(path=path), self.assertRaises(ValueError): normalize_path(path)

    def test_actual_wannier_kpoint_list_is_not_resampled(self):
        text = '3\n 0 0 0 1\n .123456 0 0 1\n .5 0 0 1\n'
        self.assertEqual(read_band_kpt(text),((0.,0.,0.),(.123456,0.,0.),(.5,0.,0.)))
        card = qe_band_kpt_card(text)
        self.assertIn('0.123456 0 0 1',card)
        self.assertEqual(card.splitlines()[:2],['K_POINTS crystal','3'])
        for invalid in ['4\n0 0 0 1\n', '1\n0 nan 0 1\n','1\n0 0 0 -1\n']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): read_band_kpt(invalid)

    def test_distinct_equivalent_boundary_points_can_share_a_label(self):
        path = ['G 0 0 0 X .5 0 .5', 'X .5 -.5 0 G 0 0 0']
        self.assertEqual(len(normalize_path(path)),2)
        self.assertIn('0.5 0 0.5 0 ! X',qe_path_card(path))

    def test_seekpath_time_reversal_partner_labels_are_supported(self):
        path = ["GAMMA 0 0 0 X' -.5 0 0"]
        self.assertEqual(normalize_path(path)[0].end_label,"X'")

    @unittest.skipUnless(importlib.util.find_spec('seekpath'),'optional seekpath is absent')
    def test_automatic_nonstandard_cell_keeps_cartesian_path(self):
        import numpy as np
        # Unequal, permuted axes catch mistakenly returning standardized-cell coordinates.
        cell = np.array([[0,4,0],[3,0,0],[0,0,5.]])
        result = automatic_path(cell,[[0,0,0]],['Fe1'],magnetic=True)
        import seekpath
        expected = seekpath.get_path_orig_cell((cell,[[0,0,0]],[1]), with_time_reversal=False)
        for segment,(a,b) in zip(result.segments,expected['path']):
            for actual,label in [(segment.start,a),(segment.end,b)]:
                np.testing.assert_allclose(np.array(actual) @ np.linalg.inv(cell).T,
                                           np.array(expected['point_coords'][label]) @ np.linalg.inv(cell).T)
        self.assertTrue(any('magnetic' in warning for warning in result.warnings))

if __name__ == '__main__': unittest.main()
