"""Output-derived values must not replace deliberate research choices."""
import importlib.util
import contextlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from qbox.io.wannier_workflow import _win_parts


def record(fermi=4.2, path='/work/scf.out'):
    return dict(path=path, kind='scf', sha256='digest', fermi_energy=fermi,
                nbnd=16, eigenvalue_min=-10., eigenvalue_max=12.,
                homo=4., lumo=5., notes=[])


def gap_record(path='/work/nscf.out'):
    result = record(None, path)
    result.update(kind='nscf', gap_reference=dict(value_eV=4.5, vbm=4., cbm=5., method='sampled_midgap'))
    return result


class OutputDefaultsTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.wannier_output_defaults'))
        from qbox.io import wannier_output_defaults
        return wannier_output_defaults

    def test_imports_real_fermi_without_changing_basis_or_research_range(self):
        api = self.api()
        cfg = {'nbnd': 40, 'num_wann': 32, 'parameters': {'kubo_freq_max': 3.}}
        api.apply_output(cfg, record())
        self.assertEqual(cfg['parameters'], {'kubo_freq_max': 3., 'fermi_energy': 4.2})
        self.assertEqual(cfg['nbnd'], 40)
        self.assertEqual(cfg['qe_output']['path'], '/work/scf.out')
        self.assertEqual(cfg['output_parameter_values'], {'fermi_energy': 4.2})

    def test_reselecting_output_refreshes_only_automatic_values(self):
        api = self.api()
        cfg = {'parameters': {}}
        api.apply_output(cfg, record())
        api.apply_output(cfg, record(4.3, '/work/nscf.out'))
        self.assertEqual(cfg['parameters']['fermi_energy'], 4.3)
        cfg['parameters']['fermi_energy'] = 6.
        api.apply_output(cfg, record(4.4))
        self.assertEqual(cfg['parameters']['fermi_energy'], 6.)

    def test_manual_fermi_and_deliberately_cleared_value_are_preserved(self):
        api = self.api()
        cfg = {'parameters': {'fermi_energy': 0.}}
        api.apply_output(cfg, record())
        self.assertEqual(cfg['parameters']['fermi_energy'], 0.)
        api.mark_manual(cfg, 'fermi_energy')
        cfg['parameters'].pop('fermi_energy')
        api.apply_output(cfg, record())
        self.assertNotIn('fermi_energy', cfg['parameters'])

    def test_manual_value_equal_to_imported_value_is_not_deleted(self):
        api = self.api()
        cfg = {'parameters': {}}
        api.apply_output(cfg, record())
        api.mark_manual(cfg, 'fermi_energy')
        api.clear_output(cfg, disable=True)
        self.assertEqual(cfg['parameters']['fermi_energy'], 4.2)
        self.assertEqual(cfg['source_output_mode'], 'off')

    def test_disabling_import_removes_derived_values_and_source(self):
        api = self.api()
        cfg = {'parameters': {}}
        api.apply_output(cfg, record())
        api.clear_output(cfg, disable=True)
        self.assertNotIn('fermi_energy', cfg['parameters'])
        self.assertNotIn('source_output', cfg)
        self.assertNotIn('qe_output', cfg)
        self.assertEqual(cfg['source_output_mode'], 'off')

    def test_band_edges_never_replace_missing_fermi_energy(self):
        api = self.api()
        cfg = {'parameters': {}}
        api.apply_output(cfg, record())
        api.apply_output(cfg, record(None, '/work/insulator.out'))
        self.assertNotIn('fermi_energy', cfg['parameters'])
        self.assertEqual(cfg['qe_output']['homo'], 4.)
        self.assertEqual(cfg['qe_output']['lumo'], 5.)

    def test_midgap_task_scope_and_defer_contract(self):
        api = self.api()
        for tasks, allowed in [(['shift_current'], True), (['shift_current', 'optical', 'bands'], True),
                               (['optical'], False), (['shift_current', 'ahc'], False),
                               (['shift_current', 'fermi_surface'], False)]:
            cfg = dict(mode='new', tasks=tasks, parameters={})
            self.assertEqual(api.midgap_allowed(cfg), allowed)
            self.assertEqual(api.can_defer_fermi(cfg), allowed)
            cfg['mode'] = 'existing'
            self.assertFalse(api.can_defer_fermi(cfg))
            cfg.update(mode='new', parameters={'fermi_energy': 0.})
            self.assertFalse(api.can_defer_fermi(cfg))

    def test_midgap_is_auto_occupation_reference_not_a_reported_fermi(self):
        api = self.api()
        cfg = dict(tasks=['shift_current'], parameters={})
        api.apply_output(cfg, gap_record())
        self.assertEqual(cfg['parameters']['fermi_energy'], 4.5)
        self.assertIsNone(cfg['qe_output']['fermi_energy'])
        self.assertEqual(cfg['fermi_source']['method'], 'sampled_midgap')
        cfg['tasks'] = ['ahc']
        api.apply_output(cfg, cfg['qe_output'])
        self.assertNotIn('fermi_energy', cfg['parameters'])
        cfg['tasks'] = ['shift_current']
        api.apply_output(cfg, cfg['qe_output'])
        self.assertEqual(cfg['parameters']['fermi_energy'], 4.5)
        api.apply_output(cfg, record())
        self.assertEqual(cfg['fermi_source']['method'], 'reported')

    def test_midgap_never_overrides_manual_or_explicitly_cleared_values(self):
        api = self.api()
        cfg = dict(tasks=['shift_current'], parameters={'fermi_energy': 0.})
        api.apply_output(cfg, gap_record())
        self.assertEqual(cfg['parameters']['fermi_energy'], 0.)
        api.mark_manual(cfg, 'fermi_energy')
        cfg['parameters'].pop('fermi_energy')
        api.apply_output(cfg, gap_record())
        self.assertNotIn('fermi_energy', cfg['parameters'])

    def test_only_one_usable_record_is_preferred_without_hiding_real_ambiguity(self):
        api = self.api()
        cfg = dict(tasks=['shift_current'], parameters={})
        self.assertEqual(api.preferred_records(cfg, [record(None), gap_record()]), [gap_record()])
        both = [record(), gap_record()]
        self.assertEqual(api.preferred_records(cfg, both), both)
        cfg['tasks'] = ['optical']
        both = [record(None), gap_record()]
        self.assertEqual(api.preferred_records(cfg, both), [gap_record()])
        api.apply_output(cfg, gap_record())
        self.assertNotIn('fermi_energy', cfg['parameters'])

    def test_pending_rescans_old_auto_record_and_preserves_manual_selection(self):
        api = self.api()
        cfg = dict(mode='new', tasks=['shift_current'], parameters={}, pending_fermi=True)
        api.apply_output(cfg, record(None))
        with patch.object(api, 'candidates', return_value=[record(None), gap_record()]) as scan:
            api.ensure_output(cfg)
        scan.assert_called_once()
        self.assertEqual(cfg['source_output'], '/work/nscf.out')
        self.assertEqual(cfg['parameters']['fermi_energy'], 4.5)
        cfg.update(source='/work/scf.in', source_output='/work/manual.out', source_output_mode='manual')
        with patch('qbox.io.wannier_outputs.read_output', return_value=record(None, '/work/manual.out')) as read:
            with patch.object(api, 'candidates') as scan:
                api.ensure_output(cfg)
        scan.assert_not_called()
        self.assertEqual(read.call_args.args[:2], ('/work/manual.out', '/work/scf.in'))
        self.assertEqual(cfg['source_output'], '/work/manual.out')

    def test_multiple_unusable_records_do_not_block_deferred_stage_but_usable_ambiguity_does(self):
        api = self.api()
        cfg = dict(mode='new', tasks=['shift_current'], parameters={})
        with patch.object(api, 'candidates', return_value=[record(None), record(None, '/other.out')]):
            api.ensure_output(cfg)
        self.assertNotIn('fermi_energy', cfg['parameters'])
        with patch.object(api, 'candidates', return_value=[record(), gap_record()]):
            with self.assertRaisesRegex(ValueError, '多份'):
                api.ensure_output(cfg)


class WorkflowOutputImportTests(unittest.TestCase):
    def setUp(self):
        from test_wannier_outputs import SCF, UPF, output
        temporary = tempfile.TemporaryDirectory(prefix='qbox output import ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(contextlib.chdir(self.root))
        (self.root / 'pseudo').mkdir()
        (self.root / 'pseudo/Si.UPF').write_text(UPF)
        self.source = self.root / 'scf.in'
        self.source.write_text(SCF)
        self.output = self.root / 'scf.out'
        self.output.write_text(output())
        self.config = dict(source=str(self.source), run_root=str(self.root), seed='si',
                           mode='new', tasks=['optical'], grid=[2, 2, 2], nbnd=4,
                           num_wann=2, projections=['Si:s'], parameters={})

    def prepare(self):
        from qbox.io.wannier_workflow import prepare
        return prepare(self.config, self.root)

    def test_automatic_output_completes_optical_input_and_records_provenance(self):
        files = self.prepare()
        values, _ = _win_parts(files['si.win'])
        self.assertEqual(values['fermi_energy'], '2.5')
        self.assertNotIn('kubo_freq_max', values)
        self.assertNotIn('kubo_eigval_max', values)
        metadata = json.loads(files['si.qbox.json'])
        self.assertEqual(metadata['config']['qe_output']['path'], str(self.output))
        self.assertEqual(metadata['config']['fermi_source']['value_eV'], 2.5)
        self.assertIn('Imported QE output: scf.out (SCF', files['si.README.txt'])
        self.assertNotIn('fermi_energy', self.config['parameters'])

    def test_manual_fermi_wins_and_off_mode_never_reads_output(self):
        self.config['parameters']['fermi_energy'] = 0.
        self.assertEqual(_win_parts(self.prepare()['si.win'])[0]['fermi_energy'], '0')
        self.config.update(source_output_mode='off', source_output='/missing/output')
        files = self.prepare()
        self.assertEqual(_win_parts(files['si.win'])[0]['fermi_energy'], '0')
        self.assertNotIn('qe_output', json.loads(files['si.qbox.json'])['config'])

    def test_multiple_outputs_require_selection_for_missing_fermi(self):
        from test_wannier_outputs import SCF, output
        (self.root / 'nscf.in').write_text(SCF.replace("calculation='scf'", "calculation='nscf'").replace(
            'K_POINTS automatic\n2 2 2 0 0 0',
            'K_POINTS crystal\n2\n0 0 0 .5\n.5 0 0 .5'))
        self.config['grid'] = [2, 1, 1]
        (self.root / 'nscf.out').write_text(output(kind='nscf', input_name='nscf.in',
                                                fermi='the Fermi energy is 2.6000 ev'))
        with self.assertRaisesRegex(ValueError, '多份'):
            self.prepare()
        self.config['source_output'] = str(self.root / 'nscf.out')
        self.assertEqual(_win_parts(self.prepare()['si.win'])[0]['fermi_energy'], '2.6')

    def test_selected_output_is_revalidated_before_generation(self):
        from qbox.io.wannier_output_defaults import apply_output, candidates
        apply_output(self.config, candidates(self.config)[0])
        self.output.write_text(self.output.read_text().replace('JOB DONE.', ''))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_existing_model_reference_must_match_the_wannier_geometry(self):
        from test_wannier_workflow import WIN
        from qbox.io.wannier_output_defaults import candidates, ensure_output
        win = self.root / 'other.win'
        win.write_text(WIN)
        cfg = dict(mode='existing', source=str(win), reference_source=str(self.source),
                   run_root=str(self.root), parameters={})
        self.assertEqual(candidates(cfg), [])
        cfg['source_output'] = str(self.output)
        with self.assertRaisesRegex(ValueError, '模型|结构'):
            ensure_output(cfg)

    def test_automatic_window_reference_refreshes_with_output_and_can_be_disabled(self):
        from qbox.io.wannier_output_defaults import ensure_output, clear_output
        self.config['windows'] = {'reference': 'fermi', 'dis_win_min': -1., 'dis_win_max': 8.}
        ensure_output(self.config)
        self.assertEqual(self.config['windows']['fermi_energy'], 2.5)
        self.output.write_text(self.output.read_text().replace('2.5000 ev', '4.0000 ev'))
        ensure_output(self.config)
        self.assertEqual(self.config['parameters']['fermi_energy'], 4.)
        self.assertEqual(self.config['windows']['fermi_energy'], 4.)
        clear_output(self.config, disable=True)
        self.assertNotIn('fermi_energy', self.config['windows'])

    def test_manual_window_reference_is_not_replaced_or_cleared(self):
        from qbox.io.wannier_output_defaults import ensure_output, clear_output, mark_manual
        self.config['windows'] = {'reference': 'fermi', 'dis_win_min': -1., 'dis_win_max': 8.}
        ensure_output(self.config)
        mark_manual(self.config, 'windows.fermi_energy')
        clear_output(self.config, disable=True)
        self.assertEqual(self.config['windows']['fermi_energy'], 2.5)
