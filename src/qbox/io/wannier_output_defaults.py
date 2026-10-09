"""Use verified QE output without replacing deliberate parameter choices."""
import copy
from pathlib import Path
from types import SimpleNamespace


def midgap_allowed(config):
    """Allow a sampled-gap occupation reference only for shift-current workflows."""
    from .wannier_profiles import fields_for_tasks
    tasks = config.get('tasks') or []
    return ('shift_current' in tasks and all(
        task in ('shift_current', 'optical') or 'fermi_energy' not in fields_for_tasks([task])
        for task in tasks))


def can_defer_fermi(config):
    """Whether a new shift-current model may be built before its EF is known."""
    return (config.get('mode', 'new') == 'new' and midgap_allowed(config)
            and (config.get('parameters') or {}).get('fermi_energy') is None)


def _reference(config, record):
    if record.get('fermi_energy') is not None:
        return record['fermi_energy'], 'reported'
    gap = record.get('gap_reference') or {}
    if midgap_allowed(config) and gap.get('method') == 'sampled_midgap':
        return gap.get('value_eV'), 'sampled_midgap'
    return None, None


def preferred_records(config, records):
    """Prefer one uniquely usable EF record; never pick among competing values."""
    records = list(records)
    usable = [record for record in records if _reference(config, record)[0] is not None]
    if len(usable) == 1:
        return usable
    if not usable:
        # A complete fixed-occupation NSCF contains both sides of the gap.
        # Prefer that energy reference before the user selects SC, without
        # turning its band edges into a reported Fermi energy.
        complete_gap = [record for record in records if record.get('kind') == 'nscf'
                        and (record.get('gap_reference') or {}).get('method') == 'sampled_midgap']
        if len(complete_gap) == 1:
            return complete_gap
    return records


def _source(config):
    if config.get('mode') == 'existing':
        return config.get('reference_source')
    nscf = (config.get('qe_progress') or {}).get('nscf') or {}
    return nscf.get('input') if nscf.get('reusable') else config.get('source')


def _validate_reference(config):
    if config.get('mode') != 'existing':
        return
    from .wannier_inputs import parse_qe
    from .wannier_outputs import _same_geometry
    from .wannier_workflow import _existing_basis, _win_geometry
    original = Path(config['source']).expanduser().read_text(encoding='utf-8')
    reference = parse_qe(Path(_source(config)).expanduser().read_text(encoding='utf-8'))
    cell, atoms = _win_geometry(original)
    if (reference.spin_mode != _existing_basis(original)['spin_mode'] or
            not _same_geometry(reference, SimpleNamespace(cell=cell, atoms=atoms))):
        raise ValueError('原 SCF 与已有 Wannier 模型的结构或自旋不匹配，不能用于读取费米能。')


def candidates(config):
    if config.get('source_output_mode') == 'off' or not _source(config):
        return []
    source = Path(_source(config)).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() == '.cif':
        return []
    try:
        _validate_reference(config)
    except (OSError, ValueError, KeyError):
        return []
    from .wannier_outputs import discover_outputs
    run_root = Path(config.get('run_root') or Path.cwd()).expanduser().resolve()
    return discover_outputs(source, [Path.cwd(), source.parent, run_root], run_root=run_root)


def mark_manual(config, key):
    if key == 'windows.fermi_energy':
        config.pop('output_window_fermi_value', None)
    config.setdefault('output_parameter_values', {}).pop(key, None)
    config.get('response_parameter_defaults', {}).pop(key, None)
    fields = config.setdefault('output_manual_fields', [])
    if key not in fields:
        fields.append(key)


def clear_output(config, disable=False):
    from .wannier_window_defaults import clear_window_defaults
    clear_window_defaults(config)
    parameters = config.setdefault('parameters', {})
    for key, value in config.get('output_parameter_values', {}).items():
        if parameters.get(key) == value:
            parameters.pop(key, None)
    windows = config.get('windows', {})
    if ('output_window_fermi_value' in config and
            windows.get('fermi_energy') == config['output_window_fermi_value']):
        windows.pop('fermi_energy', None)
    for key in ('qe_output', 'source_output', 'fermi_source',
                'output_parameter_values', 'output_window_fermi_value', '_output_scan_key'):
        config.pop(key, None)
    config['source_output_mode'] = 'off' if disable else 'auto'
    from .wannier_response_defaults import refresh_response_defaults
    refresh_response_defaults(config)


def apply_output(config, record, mode='auto'):
    clear_output(config)
    config.update(qe_output=copy.deepcopy(record), source_output=record['path'],
                  source_output_mode=mode)
    fermi, method = _reference(config, record)
    parameters = config.setdefault('parameters', {})
    if (fermi is not None and parameters.get('fermi_energy') is None
            and 'fermi_energy' not in config.get('output_manual_fields', [])):
        parameters['fermi_energy'] = fermi
        config['output_parameter_values'] = {'fermi_energy': fermi}
        config['fermi_source'] = {'path': record['path'], 'value_eV': fermi,
                                  'sha256': record['sha256'], 'kind': record['kind'], 'method': method}
        if method == 'sampled_midgap':
            config['fermi_source']['gap_reference'] = copy.deepcopy(record['gap_reference'])
    from .wannier_window_defaults import initialize_window_defaults
    initialize_window_defaults(config)
    from .wannier_response_defaults import refresh_response_defaults
    refresh_response_defaults(config)


def ensure_output(config):
    """Revalidate selected output, or discover a unique output for JSON callers."""
    if config.get('source_output_mode') == 'off':
        return
    if config.get('pending_fermi') and config.get('source_output_mode') == 'auto':
        # A saved first-stage config must notice the subsequently created NSCF.
        # Explicit/manual selection remains strict and is never silently moved.
        clear_output(config)
    path = config.get('source_output')
    if path:
        source = _source(config)
        if not source:
            raise ValueError('读取 QE 输出需要原 SCF 输入；已有模型请指定 reference_source。')
        _validate_reference(config)
        from .wannier_outputs import read_output
        record = read_output(path, source, run_root=config.get('run_root') or Path.cwd())
        apply_output(config, record, mode=config.get('source_output_mode', 'manual'))
    else:
        records = preferred_records(config, candidates(config))
        if len(records) == 1:
            apply_output(config, records[0])
        elif len(records) > 1:
            from .wannier_profiles import fields_for_tasks
            requires_fermi = ('fermi_energy' in fields_for_tasks(config['tasks'])
                              if config.get('tasks') else False)
            unavailable_but_deferred = can_defer_fermi(config) and all(
                _reference(config, record)[0] is None for record in records)
            if (requires_fermi and config.get('parameters', {}).get('fermi_energy') is None
                    and not unavailable_but_deferred):
                raise ValueError('找到多份匹配的 SCF/NSCF 输出，请在菜单 2 选择，或在 JSON 中指定 source_output：'
                                 + '、'.join(record['path'] for record in records))
    info = config.get('fermi_source')
    windows = config.get('windows', {})
    if (info and windows.get('reference') == 'fermi' and windows.get('fermi_energy') is None
            and windows.get('reference_energy') is None
            and 'windows.fermi_energy' not in config.get('output_manual_fields', [])):
        windows['fermi_energy'] = info['value_eV']
        config['output_window_fermi_value'] = info['value_eV']
    from .wannier_response_defaults import refresh_response_defaults
    refresh_response_defaults(config)
