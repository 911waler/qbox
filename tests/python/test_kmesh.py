"""The mesh must match QE and Wannier ordering, not reduced symmetry points."""
import unittest
from qbox.io.kmesh import generate_mesh, format_qe, format_wannier


class KmeshTests(unittest.TestCase):
    def test_full_mesh_has_z_fastest_and_normalized_weights(self):
        mesh = generate_mesh((2, 1, 2))
        self.assertEqual(mesh, [(0., 0., 0.), (0., 0., .5), (.5, 0., 0.), (.5, 0., .5)])
        qe = format_qe((2, 1, 2)).splitlines()
        self.assertEqual(qe[:2], ['K_POINTS crystal', '4'])
        self.assertEqual([list(map(float, line.split())) for line in qe[2:]],
                         [[0., 0., 0., .25], [0., 0., .5, .25], [.5, 0., 0., .25], [.5, 0., .5, .25]])
        self.assertEqual([list(map(float, line.split())) for line in format_wannier((1, 1, 1)).splitlines()], [[0., 0., 0.]])

    def test_mesh_rejects_non_integer_and_shift_like_inputs(self):
        for grid in [(0, 1, 1), (-1, 1, 1), (1.5, 1, 1), (True, 1, 1), (1, 1), (1, 1, 1, 0, 0, 0)]:
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                generate_mesh(grid)
