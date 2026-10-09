"""Every editable Wannier field has usable help, without implying defaults."""
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from qbox.io.wannier_profiles import FIELDS


COMMON_FIELDS = {
    'nbnd', 'num_wann', 'exclude_bands', 'select_projections', 'num_iter',
    'dis_num_iter', 'conv_tol', 'conv_window', 'dis_mix_ratio', 'dis_conv_tol',
    'dis_conv_window', 'seed', 'grid', 'source_output', 'run_root',
    'reference_source', 'band_kpt', 'dis_win_min', 'dis_win_max',
    'dis_froz_min', 'dis_froz_max', 'windows_fermi_energy',
}


class WannierHelpTests(unittest.TestCase):
    def help_entries(self):
        name = 'qbox.io.wannier_help'
        self.assertIsNotNone(importlib.util.find_spec(name),
                             'The interactive field help catalog is missing')
        return importlib.import_module(name).FIELD_HELP

    def test_every_editable_profile_and_common_field_has_help(self):
        entries = self.help_entries()
        self.assertFalse((set(FIELDS) | COMMON_FIELDS) - entries.keys(),
                         'New fields must not silently lose inline guidance')
        for key, item in entries.items():
            with self.subTest(key=key):
                for attribute in ('help', 'example', 'clear_effect', 'label'):
                    self.assertIsInstance(item[attribute], str)
                    self.assertTrue(item[attribute].strip())

    def test_all_examples_are_explicitly_format_only_and_not_defaults(self):
        for key, item in self.help_entries().items():
            with self.subTest(key=key):
                self.assertIn('格式示例', item['example'])
                self.assertIn('非默认值', item['example'])
                self.assertIn('非材料参数推荐', item['example'])


if __name__ == '__main__':
    unittest.main()
