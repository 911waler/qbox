"""Phonon plots preserve units, unstable modes, and disconnected q paths."""
import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


FREQUENCIES = ''' &plot nbnd= 3, nks= 5 /
 0.0 0.0 0.0
 -20.0  0.0  100.0
 0.5 0.0 0.0
 -10.0  50.0  120.0
 0.1 0.1 0.1
 999.0 999.0 999.0
 0.0 0.5 0.0
 -5.0  60.0  130.0
 0.0 0.0 0.0
 -20.0 0.0 100.0
'''
PATH = {'nat': 1, 'qpoints': [[0, 0, 0], [.5, 0, 0], [.1, .1, .1], [0, .5, 0], [0, 0, 0]],
        'labels': ['GAMMA', 'X', '', 'Y', 'GAMMA'],
        'distances': [0, 1, None, 1, 2], 'guard_indices': [2], 'breaks': [3],
        'segments': [{'start': 0, 'end': 1, 'start_label': 'GAMMA', 'end_label': 'X'},
                     {'start': 3, 'end': 4, 'start_label': 'Y', 'end_label': 'GAMMA'}]}
GP = '0 -20 0 100\n0.25 -10 50 120\n0.5 -5 60 130\n1.5 -2 70 140\n1.75 -1 80 150\n'


class PhononPlotTests(unittest.TestCase):
    def plot(self):
        self.assertIsNotNone(importlib.util.find_spec('qbox.postprocess.phonon_plot'),
                             'phonons require a frequency plotter independent of electronic energies')
        from qbox.postprocess import phonon_plot
        return phonon_plot

    def test_frequency_reader_keeps_negative_modes_and_fortran_exponents(self):
        plot = self.plot()
        points, modes = plot.read_frequencies(FREQUENCIES.replace('-20.0', '-2.0D1'))
        self.assertEqual(points.shape, (5, 3))
        self.assertEqual(modes.shape, (5, 3))
        self.assertEqual(modes[0].tolist(), [-20., 0., 100.])

    def test_native_matdyn_four_column_cartesian_q_rows_match_transformed_metadata(self):
        # QE 7.5 native Si smoke output: crystal (0,.125,.125) becomes Cartesian (0,.25,0).
        native = ''' &plot nbnd=   6, nks=  2 /
            0.000000  0.000000  0.000000  0.000000
   -0.0000   -0.0000    0.0000  588.0509  588.0509  588.0509
            0.000000  0.250000  0.000000  0.000000
  114.7230  114.7230  114.7230  576.7517  576.7517  576.7517
'''
        metadata = {'nat': 2, 'qpoints': [[0, 0, 0], [0, .125, .125]],
                    'qpoints_matdyn': [[0, 0, 0], [0, .25, 0]], 'distances': [0, .3],
                    'segments': [{'start': 0, 'end': 1, 'start_label': 'GAMMA', 'end_label': 'X'}]}
        plot = self.plot()
        points, modes = plot.read_frequencies(native)
        self.assertEqual(points[1].tolist(), [0., .25, 0.])
        self.assertEqual(modes.shape, (2, 6))
        segments, _ = plot.prepare_segments(points, modes, metadata)
        self.assertEqual(segments[0][1][1, 3], 576.7517)
        with self.assertRaises(ValueError):
            plot.prepare_segments(points, modes, {**metadata, 'qpoints_matdyn': [[0, 0, 0], [0, .2, 0]]})

    def test_truncated_or_extra_mode_data_is_rejected(self):
        plot = self.plot()
        for text in (FREQUENCIES.replace('-20.0 0.0 100.0', '-20.0 0.0'),
                     FREQUENCIES.replace('nbnd= 3', 'nbnd= 2'),
                     FREQUENCIES.replace('nks= 5', 'nks= 6'),
                     FREQUENCIES + '\n1 2 3\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                plot.read_frequencies(text)

    def test_segments_exclude_guard_point_and_do_not_bridge_disconnected_path(self):
        plot = self.plot()
        points, modes = plot.read_frequencies(FREQUENCIES)
        segments, ticks = plot.prepare_segments(points, modes, PATH)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0][0].tolist(), [0., 1.])
        self.assertEqual(segments[1][1][:, 0].tolist(), [-5., -20.])
        self.assertNotIn(999., [v for _, values in segments for v in values.flatten()])
        self.assertEqual(ticks, [(0., 'Γ'), (1., 'X|Y'), (2., 'Γ')])

    def test_metadata_count_modes_and_coordinates_must_match(self):
        plot = self.plot()
        points, modes = plot.read_frequencies(FREQUENCIES)
        for data in ({**PATH, 'qpoints': PATH['qpoints'][:-1]},
                     {**PATH, 'nat': 2},
                     {**PATH, 'qpoints': [[.2, 0, 0], *PATH['qpoints'][1:]]},
                     {**PATH, 'segments': [{'start': 0, 'end': 4}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                plot.prepare_segments(points, modes, data)

    def test_cli_renders_png_and_svg_with_frequency_units(self):
        plot = self.plot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'sample.freq').write_text(FREQUENCIES)
            (path / 'sample.path.json').write_text(json.dumps(PATH))
            self.assertEqual(plot.main(['-i', str(path / 'sample.freq'), '--path',
                                       str(path / 'sample.path.json'), '-o', str(path / 'phonon')]), 0)
            self.assertGreater((path / 'phonon.png').stat().st_size, 1000)
            svg = (path / 'phonon.svg').read_text()
            self.assertIn('Frequency', svg)
            self.assertIn('cm', svg)

    def test_cli_output_accepts_an_image_suffix_without_doubling_it(self):
        plot = self.plot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'sample.freq').write_text(FREQUENCIES)
            (path / 'sample.path.json').write_text(json.dumps(PATH))
            self.assertEqual(plot.main(['-i', str(path / 'sample.freq'), '--path',
                                       str(path / 'sample.path.json'), '-o', str(path / 'phonon.png')]), 0)
            self.assertTrue((path / 'phonon.png').exists())
            self.assertTrue((path / 'phonon.svg').exists())
            self.assertFalse((path / 'phonon.png.png').exists())

    def test_batch_draws_external_gp_files_and_continues_after_a_bad_file(self):
        plot = self.plot()
        with tempfile.TemporaryDirectory(prefix="phonon plots ' ") as directory:
            path = Path(directory)
            for name in ('a sample', 'b'):
                (path / (name + '.freq.gp')).write_text(GP)
            (path / 'bad.freq.gp').write_text('0 NaN 1 2\n1 2 3 4\n')
            output = StringIO()
            with redirect_stdout(output):
                status = plot.main(['--directory', str(path)])
            self.assertEqual(status, 1)
            self.assertIn('成功 2，失败 1', output.getvalue())
            for name in ('a sample', 'b'):
                self.assertGreater((path / (name + '_phonon.png')).stat().st_size, 1000)
                self.assertIn('Frequency', (path / (name + '_phonon.svg')).read_text())
                self.assertEqual((path / (name + '.freq.gp')).read_text(), GP)
            self.assertFalse((path / 'bad_phonon.png').exists())

    def test_manual_path_uses_original_numeric_row_numbers_and_breaks(self):
        plot = self.plot()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'outside.freq.gp'
            source.write_text(GP)
            with patch.object(plot, 'render_plot') as render:
                status = plot.main(['-i', str(source), '--ticks', '1:Gamma,3:X,4:Y,5:M',
                                    '--breaks', '4'])
            self.assertEqual(status, 0)
            segments, ticks, _ = render.call_args.args
            self.assertEqual([len(values) for _, values in segments], [3, 2])
            self.assertEqual(ticks, [(0., 'Γ'), (.5, 'X|Y'), (.75, 'M')])
            self.assertEqual(segments[0][1][0, 0], -20.)

    def test_malformed_json_segments_fall_back_and_do_not_abort_batch(self):
        plot = self.plot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            metadata = {'qpoints': [[0, 0, 0], [.25, 0, 0], [.5, 0, 0],
                                    [1.5, 0, 0], [1.75, 0, 0]],
                        'distances': [0, .25, .5, 1.5, 1.75], 'segments': [1]}
            for name in ('a', 'b'):
                (path / (name + '.freq.gp')).write_text(GP)
            companion = path / 'a.path.json'
            companion.write_text(json.dumps(metadata))
            output = StringIO()
            with redirect_stdout(output), patch.object(plot, 'render_plot') as render:
                self.assertEqual(plot.main(['--directory', str(path)]), 0)
            self.assertEqual(render.call_count, 2)
            self.assertIn('未采用 a.path.json', output.getvalue())
            with redirect_stdout(output), patch.object(plot, 'render_plot') as render:
                self.assertEqual(plot.main(['-i', str(path / 'a.freq.gp'),
                                           '--path', str(companion)]), 1)
            render.assert_not_called()

    def test_interactive_path_edit_and_cancel(self):
        plot = self.plot()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'sample.freq.gp'
            source.write_text(GP)
            answers = iter(['1', '1', '2', '1:Gamma,3:X,4:Y,5:M', '4', '0', ''])
            output = []
            with patch.object(plot, 'render_plot') as render:
                status = plot.run_interactive([source], input_fn=lambda _: next(answers), output=output.append)
            self.assertEqual(status, 0, output)
            self.assertEqual(len(render.call_args.args[0]), 2)
            self.assertIn('路径设置已保存。', output)
            self.assertEqual(plot.run_interactive([source], input_fn=lambda _: '2', output=output.append), 0)
            self.assertFalse((Path(directory) / 'sample_phonon.png').exists())

    def test_public_menu_39_plots_all_gp_files_without_path_json(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix='qbox external phonons ') as directory:
            path = Path(directory)
            for name in ('silicon', 'sic'):
                (path / (name + '.freq.gp')).write_text(GP)
            env = os.environ.copy()
            for key in ('QBOX_TEST_MODE', 'QE_DIRECT_ACTION', 'QBOX_TASK_ID', 'BASH_FUNC_module%%', 'BASH_FUNC_ml%%'):
                env.pop(key, None)
            env.update(QBOX_PYTHON=sys.executable, PYTHONPATH=str(root / 'src'))
            result = subprocess.run([str(root / 'qbox')], cwd=path, env=env,
                                    input='39\n\n', text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('39) 绘制 QE 声子谱图', result.stdout)
            self.assertEqual(result.stdout.count('请输入功能编号。'), 1)
            for name in ('silicon', 'sic'):
                self.assertTrue((path / (name + '_phonon.png')).is_file())
                self.assertTrue((path / (name + '_phonon.svg')).is_file())


if __name__ == '__main__':
    unittest.main()
