"""Recover dispersion paths from native MATDYN data without guessing labels."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


class PhononPlotDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.gp = self.root / 'sample.freq.gp'

    def prepare(self, **kwargs):
        self.assertIsNotNone(importlib.util.find_spec('qbox.postprocess.phonon_plot_data'),
                             'native MATDYN plotting needs safe metadata recovery')
        from qbox.postprocess.phonon_plot_data import prepare_plot
        return prepare_plot(self.gp, **kwargs)

    def table(self, x, modes=None):
        modes = modes if modes is not None else [[-10 + i, 20 + i, 100 + i] for i in range(len(x))]
        self.gp.write_text('\n'.join(' '.join(f'{v:.8f}' for v in (coordinate, *values))
                                   for coordinate, values in zip(x, modes)) + '\n')
        return np.asarray(modes)

    def metadata(self):
        points = np.asarray([[0, 0, 0], [.5, 0, 0], [.1, .1, .1], [0, .5, 0], [0, 0, 0]])
        x = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        modes = self.table(x, [[-20, 0, 100], [-10, 50, 120], [999, 999, 999],
                             [-5, 60, 130], [-20, 0, 100]])
        metadata = {'nat': 1, 'qpoints_matdyn': points.tolist(),
                    'distances': [0, 1, None, 1, 2], 'guard_indices': [2],
                    'segments': [{'start': 0, 'end': 1, 'start_label': 'GAMMA', 'end_label': 'X'},
                                 {'start': 3, 'end': 4, 'start_label': 'Y', 'end_label': 'GAMMA'}]}
        path = self.root / 'sample.path.json'
        path.write_text(json.dumps(metadata))
        return metadata, path, points, modes

    def frequency_file(self, points, modes):
        path = self.root / 'sample.freq'
        lines = [f' &plot nbnd={len(modes[0])}, nks={len(points)} /']
        for point, values in zip(points, modes):
            lines.extend((' '.join(str(v) for v in point), ' '.join(str(v) for v in values)))
        path.write_text('\n'.join(lines) + '\n')
        return path

    def matdyn(self, rows, *, band=True, crystal=False, filename='sample.matdyn.in', output='sample.freq'):
        path = self.root / filename
        path.write_text("&input\n flfrq='%s', q_in_band_form=%s, q_in_cryst_coord=%s,\n/\n%d\n%s\n" % (
            output, '.true.' if band else '.false.', '.true.' if crystal else '.false.',
            len(rows), '\n'.join(rows)))
        return path

    def test_gp_only_preserves_negative_modes_and_numeric_axis(self):
        self.gp.write_text('# frequencies in cm^-1\n0 -2D1 0 100\n0.5 -10 50 120\n')
        segments, ticks, notes = self.prepare()
        self.assertEqual(ticks, [])
        self.assertEqual(segments[0][0].tolist(), [0, .5])
        self.assertEqual(segments[0][1][0].tolist(), [-20, 0, 100])
        self.assertTrue(any('标签' in note for note in notes))

    def test_blank_blocks_repeated_and_decreasing_x_are_breaks(self):
        self.gp.write_text('0 -1 2 3\n1 -2 2 3\n\n4 -3 2 3\n5 -4 2 3\n'
                           '5 -5 2 3\n6 -6 2 3\n0 -7 2 3\n1 -8 2 3\n')
        segments, ticks, _ = self.prepare()
        self.assertEqual([len(x) for x, _ in segments], [2, 2, 2, 2])
        self.assertEqual([x.tolist() for x, _ in segments], [[0, 1], [1, 2], [2, 3], [3, 4]])
        self.assertEqual(ticks, [])

    def test_large_positive_spacing_does_not_invent_breaks(self):
        self.table([0, .01, 100, 100.1])
        self.assertEqual(len(self.prepare()[0]), 1)

    def test_invalid_or_point_only_gp_is_rejected(self):
        for text in ('', '0 1 2 3\n', '0 1 2\n1 1 2\n', '0 1 2 3\n1 1 2\n',
                     '0 1 2 3\n1 nan 2 3\n', '0 1 2 3\n1 text 2 3\n', '0 1 2 3\n0 2 3 4\n'):
            self.gp.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.prepare()

    def test_qbox_metadata_excludes_guards_and_merges_boundary_labels(self):
        self.metadata()
        segments, ticks, _ = self.prepare()
        self.assertEqual([x.tolist() for x, _ in segments], [[0, 1], [1, 2]])
        self.assertEqual(ticks, [(0., 'Γ'), (1., 'X|Y'), (2., 'Γ')])
        self.assertFalse(any(np.any(values == 999) for _, values in segments))

    def test_mismatched_qbox_gp_axis_falls_back_without_labels(self):
        self.metadata()
        self.table([0, .5, .9, 1.4, 2])
        segments, ticks, notes = self.prepare()
        self.assertEqual(ticks, [])
        self.assertEqual(sum(len(x) for x, _ in segments), 5)
        self.assertTrue(any('不匹配' in note for note in notes))

    def test_explicit_invalid_path_is_an_error(self):
        _, path, _, _ = self.metadata()
        self.table([0, 1, 2, 3, 4])
        with self.assertRaisesRegex(ValueError, '不匹配'):
            self.prepare(path_file=path)

    def test_companion_frequency_coordinates_and_modes_must_match(self):
        metadata, _, points, modes = self.metadata()
        self.frequency_file(points, modes)
        self.assertTrue(self.prepare()[1])
        for wrong_points, wrong_modes in ((points + .1, modes), (points, modes + 1)):
            self.frequency_file(wrong_points, wrong_modes)
            with self.subTest(coords=wrong_points.tolist()):
                self.assertEqual(self.prepare()[1], [])

    def test_wrong_count_or_mode_count_in_metadata_falls_back(self):
        metadata, path, _, _ = self.metadata()
        for invalid in ({**metadata, 'nat': 2},
                        {**metadata, 'qpoints_matdyn': metadata['qpoints_matdyn'][:-1]}):
            path.write_text(json.dumps(invalid))
            self.assertEqual(self.prepare()[1], [])

    def test_band_form_recovers_counts_comment_labels_and_disconnected_path(self):
        self.table([0, .25, .5, .5 + 2**-.5, .75 + 2**-.5, 1 + 2**-.5])
        self.matdyn(['0 0 0 2 ! Gamma', '.5 0 0 0 ! X',
                     '0 .5 0 2 ! Y', '.5 .5 0 999 ! M'])
        segments, ticks, _ = self.prepare()
        self.assertEqual([len(x) for x, _ in segments], [3, 3])
        np.testing.assert_allclose(segments[1][0], [.5, .75, 1])
        self.assertEqual(ticks, [(0., 'Γ'), (.5, 'X|Y'), (1., 'M')])

    def test_final_band_count_is_ignored(self):
        self.table([0, .25, .5])
        self.matdyn(['0 0 0 2 ! G', '.5 0 0 0 ! X'])
        self.assertEqual(self.prepare()[1], [(0., 'G'), (.5, 'X')])

    def test_input_without_labels_does_not_guess_high_symmetry_names(self):
        self.table([0, .25, .5])
        self.matdyn(['0 0 0 2', '.5 0 0 1'])
        self.assertEqual(self.prepare()[1], [])

    def test_comment_labels_use_first_token_like_electronic_band_plotting(self):
        self.table([0, .25, .5])
        self.matdyn(['0 0 0 2 ! \\Gamma start of path', '.5 0 0 1 ! X endpoint'])
        self.assertEqual(self.prepare()[1], [(0., 'Γ'), (.5, 'X')])

    def test_named_qe_vertices_keep_supplied_labels(self):
        self.table([0, .25, .5])
        self.matdyn(['gG 2', 'X 1'], crystal=True)
        self.assertEqual(self.prepare()[1], [(0., 'Γ'), (.5, 'X')])

    def test_mismatched_band_count_and_cartesian_distances_fall_back(self):
        self.table([0, .25, .5])
        for rows in (['0 0 0 3 ! GAMMA', '.5 0 0 1 ! X'],
                     ['0 0 0 2 ! GAMMA', '1 0 0 1 ! X']):
            self.matdyn(rows)
            with self.subTest(rows=rows):
                self.assertEqual(self.prepare()[1], [])

    def test_explicit_q_rows_use_only_supplied_row_labels(self):
        self.table([0, .25, .5])
        self.matdyn(['0 0 0 ! Gamma', '.25 0 0', '.5 0 0 ! X'], band=False)
        self.assertEqual(self.prepare()[1], [(0., 'Γ'), (.5, 'X')])

    def test_unrelated_or_ambiguous_input_is_not_silently_adopted(self):
        self.table([0, .25, .5])
        rows = ['0 0 0 2 ! Gamma', '.5 0 0 1 ! X']
        wrong = self.matdyn(rows, output='different.freq')
        self.assertEqual(self.prepare()[1], [])
        with self.assertRaises(ValueError):
            self.prepare(matdyn_file=wrong)
        self.matdyn(rows)
        self.matdyn(rows, filename='another.in')
        self.assertEqual(self.prepare()[1], [])

    def test_scan_input_with_arbitrary_name_and_matching_flfrq(self):
        self.table([0, .25, .5])
        self.matdyn(['0 0 0 2 ! Gamma', '.5 0 0 1 ! X'], filename='custom interpolation.in')
        self.assertEqual(self.prepare()[1], [(0., 'Γ'), (.5, 'X')])

    def test_crystalline_numeric_vertices_map_by_counts_without_assuming_metric(self):
        self.table([0, .3, .6])
        self.matdyn(['0 0 0 2 ! Gamma', '.5 0 0 1 ! X'], crystal=True)
        self.assertEqual(self.prepare()[1], [(0., 'Γ'), (.6, 'X')])

    def test_quoted_flfrq_with_spaces_resolves_from_input_directory(self):
        self.gp = self.root / 'path with spaces.freq.gp'
        self.table([0, .25, .5])
        self.matdyn(['0 0 0 2 ! Gamma', '.5 0 0 1 ! X'], output='path with spaces.freq')
        self.assertEqual(self.prepare()[1], [(0., 'Γ'), (.5, 'X')])

    def test_readtau_or_dos_inputs_do_not_get_misread_as_path_vertices(self):
        self.table([0, .25, .5])
        path = self.matdyn(['0 0 0 2 ! Gamma', '.5 0 0 1 ! X'])
        original = path.read_text()
        for setting in ('readtau=.true.', 'dos=.true.'):
            path.write_text(original.replace('&input', '&input\n ' + setting + ','))
            with self.subTest(setting=setting):
                segments, ticks, notes = self.prepare()
                self.assertEqual(ticks, [])
                self.assertEqual(len(segments), 1)
                self.assertTrue(any(setting in note for note in notes))

    def test_invalid_json_uses_matching_matdyn_instead(self):
        self.table([0, .25, .5])
        (self.root / 'sample.path.json').write_text('{ not JSON }')
        self.matdyn(['0 0 0 2 ! Gamma', '.5 0 0 1 ! X'])
        segments, ticks, notes = self.prepare()
        self.assertEqual(ticks, [(0., 'Γ'), (.5, 'X')])
        self.assertTrue(any('未采用' in note for note in notes))

    def test_explicit_matdyn_overrides_automatic_json(self):
        metadata, _, _, _ = self.metadata()
        path = self.matdyn(['0 0 0 ! A', '.5 0 0 ! B', '.1 .1 .1 ! C',
                            '0 .5 0 ! D', '0 0 0 ! E'], band=False)
        segments, ticks, notes = self.prepare(matdyn_file=path)
        self.assertEqual(sum(len(x) for x, _ in segments), 5)
        self.assertEqual([label for _, label in ticks], ['A', 'B', 'C', 'D', 'E'])
        self.assertTrue(any(path.name in note and '来源' in note for note in notes))

    def test_json_success_names_path_source(self):
        _, path, _, _ = self.metadata()
        self.assertTrue(any(path.name in note and '来源' in note for note in self.prepare()[2]))

    def test_companion_axis_is_checked_for_crystal_and_named_vertices(self):
        modes = self.table([0, .25, .5])
        self.frequency_file([[0, 0, 0], [.3, 0, 0], [.6, 0, 0]], modes)
        for rows in (['0 0 0 2 ! Gamma', '.5 0 0 1 ! X'], ['gG 2', 'X 1']):
            self.matdyn(rows, crystal=True)
            with self.subTest(rows=rows):
                self.assertEqual(self.prepare()[1], [])

    def test_freq_input_retains_existing_metadata_behavior(self):
        _, path, points, modes = self.metadata()
        freq = self.frequency_file(points, modes)
        from qbox.postprocess.phonon_plot_data import prepare_plot
        segments, ticks, _ = prepare_plot(freq, path_file=path)
        self.assertEqual(ticks, [(0., 'Γ'), (1., 'X|Y'), (2., 'Γ')])
        self.assertEqual([len(x) for x, _ in segments], [2, 2])

    def test_manual_rows_override_auto_metadata_and_retain_every_original_row(self):
        self.metadata()
        segments, ticks, notes = self.prepare(tick_rows={1: 'Gamma', 3: 'Q', 5: 'Z'}, break_rows=[3])
        self.assertEqual([len(x) for x, _ in segments], [2, 3])
        self.assertEqual(ticks[0], (0, 'Γ'))
        self.assertEqual(ticks[1], (.5, 'Q'))
        self.assertTrue(any(np.any(values == 999) for _, values in segments))
        self.assertTrue(any('手动' in note for note in notes))

    def test_manual_rows_validate_original_one_based_indices(self):
        self.table([0, .25, .5])
        for options in ({'tick_rows': {0: 'X'}}, {'break_rows': [4]}, {'break_rows': [1]},
                        {'tick_rows': {True: 'X'}}, {'tick_rows': {2: ''}}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.prepare(**options)

    def annotated_matdyn(self, rows, *, band=False, header='qbox:path-v1'):
        path = self.matdyn(rows, band=band)
        path.write_text(path.read_text().replace(f'\n{len(rows)}\n', f'\n{len(rows)} ! {header}\n'))
        return path

    def test_explicit_path_annotations_recover_disconnected_segments_without_json(self):
        self.table([0, .25, .5, .5 + 2**-.5, .75 + 2**-.5, 1 + 2**-.5])
        self.annotated_matdyn(['0 0 0 ! Gamma qbox:start', '.25 0 0', '.5 0 0 ! X qbox:end',
                               '0 .5 0 ! Y qbox:start', '.25 .5 0', '.5 .5 0 ! M qbox:end'])
        segments, ticks, _ = self.prepare()
        self.assertEqual([len(x) for x, _ in segments], [3, 3])
        np.testing.assert_allclose(segments[1][0], [.5, .75, 1])
        self.assertEqual(ticks, [(0., 'Γ'), (.5, 'X|Y'), (1., 'M')])

    def test_annotated_guard_is_removed_before_plotting_without_deduplicating_gamma(self):
        points = [[0, 0, 0], [.25, 0, 0], [0, 0, 0], [0, 0, 0], [0, .5, 0]]
        modes = self.table([0, .25, .5, .5, 1], [[1, 2, 3], [2, 3, 4], [999, 999, 999],
                                                [10, 20, 30], [40, 50, 60]])
        self.frequency_file(points, modes)
        self.annotated_matdyn(['0 0 0 ! Gamma qbox:start', '.25 0 0 ! X qbox:end',
                               '0 0 0 ! qbox:guard', '0 0 0 ! Gamma qbox:start',
                               '0 .5 0 ! Y qbox:end'])
        segments, ticks, _ = self.prepare()
        self.assertEqual([x.tolist() for x, _ in segments], [[0., .25], [.25, .75]])
        self.assertEqual([values[0, 0] for _, values in segments], [1, 10])
        self.assertFalse(any(np.any(values == 999) for _, values in segments))
        self.assertEqual(ticks, [(0., 'Γ'), (.25, 'X|Γ'), (.75, 'Y')])

    def test_annotation_endpoints_allow_empty_labels(self):
        self.table([0, .25, .5])
        self.annotated_matdyn(['0 0 0 ! qbox:start', '.25 0 0', '.5 0 0 ! qbox:end'])
        segments, ticks, _ = self.prepare()
        self.assertEqual(len(segments), 1)
        self.assertEqual(ticks, [])

    def test_two_gamma_limits_at_one_boundary_keep_distinct_mode_values(self):
        self.table([0, .5, .5, 1], [[1, 2, 3], [10, 20, 30], [40, 50, 60], [7, 8, 9]])
        self.annotated_matdyn(['.5 0 0 ! X qbox:start', '0 0 0 ! Gamma qbox:end',
                               '0 0 0 ! Gamma qbox:start', '0 .5 0 ! Y qbox:end'])
        segments, ticks, _ = self.prepare()
        self.assertEqual(segments[0][1][-1].tolist(), [10, 20, 30])
        self.assertEqual(segments[1][1][0].tolist(), [40, 50, 60])
        self.assertEqual(ticks, [(0., 'X'), (.5, 'Γ'), (1., 'Y')])

    def test_ambiguous_protocol_input_requires_selection_to_avoid_plotting_guards(self):
        self.table([0, .25, .5])
        path = self.annotated_matdyn(['0 0 0 ! qbox:start', '.25 0 0', '.5 0 0 ! qbox:end'])
        self.matdyn(['0 0 0', '.25 0 0', '.5 0 0'], band=False, filename='another.in')
        with self.assertRaisesRegex(ValueError, '明确选择'):
            self.prepare()
        self.assertEqual(len(self.prepare(matdyn_file=path)[0]), 1)

    def test_annotations_validate_raw_row_count_before_removing_guard(self):
        self.table([0, .25, .5, 1])
        self.annotated_matdyn(['0 0 0 ! Gamma qbox:start', '.25 0 0 ! X qbox:end',
                               '0 0 0 ! qbox:guard', '0 0 0 ! Gamma qbox:start',
                               '0 .5 0 ! Y qbox:end'])
        with self.assertRaisesRegex(ValueError, 'q 点数与频率文件不匹配'):
            self.prepare()

    def test_bad_reserved_protocol_cannot_fall_back_and_plot_guard_rows(self):
        self.table([0, .25, .5])
        cases = [(['0 0 0 ! Gamma qbox:start', '.25 0 0', '.5 0 0 ! X'], 'qbox:path-v1'),
                 (['0 0 0 ! Gamma', '.25 0 0', '.5 0 0 ! X qbox:end'], 'qbox:path-v1'),
                 (['0 0 0 ! qbox:start qbox:end', '.25 0 0', '.5 0 0 ! X qbox:end'], 'qbox:path-v1'),
                 (['0 0 0 ! qbox:start', '.25 0 0 ! qbox:guard', '.5 0 0 ! qbox:end'], 'qbox:path-v1'),
                 (['0 0 0 ! qbox:start', '.25 0 0 ! qbox:end', '.5 0 0'], 'qbox:path-v1'),
                 (['0 0 0 ! qbox:start', '.25 0 0', '.5 0 0 ! qbox:end'], ''),
                 (['0 0 0 ! qbox:start', '.25 0 0', '.5 0 0 ! qbox:end'], 'qbox:path-v2'),
                 (['0 0 0 ! qbox:start', '.25 0 0 ! qbox:unknown', '.5 0 0 ! qbox:end'], 'qbox:path-v1')]
        for rows, header in cases:
            path = self.annotated_matdyn(rows, header=header)
            for kwargs in ({}, {'matdyn_file': path}):
                with self.subTest(rows=rows, header=header, kwargs=kwargs), self.assertRaises(ValueError):
                    self.prepare(**kwargs)

    def test_annotation_protocol_cannot_be_used_for_band_interpolation(self):
        self.table([0, .25, .5])
        self.annotated_matdyn(['0 0 0 2 ! Gamma qbox:start', '.5 0 0 1 ! X qbox:end'], band=True)
        with self.assertRaises(ValueError):
            self.prepare()

    def test_entire_raw_frequency_data_is_validated_before_guard_removal(self):
        modes = self.table([0, .25, .5, .5, 1], [[1, 2, 3], [2, 3, 4], [999, 999, 999],
                                                [10, 20, 30], [40, 50, 60]])
        companion_modes = modes.copy()
        companion_modes[2, 0] = 888
        self.frequency_file([[0, 0, 0], [.25, 0, 0], [0, 0, 0], [0, 0, 0], [0, .5, 0]], companion_modes)
        self.annotated_matdyn(['0 0 0 ! Gamma qbox:start', '.25 0 0 ! X qbox:end',
                               '0 0 0 ! qbox:guard', '0 0 0 ! Gamma qbox:start',
                               '0 .5 0 ! Y qbox:end'])
        with self.assertRaisesRegex(ValueError, '频率数据不匹配'):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
