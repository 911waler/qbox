"""Readable layout for newly generated Wannier90 inputs.

Scalar values and projection expressions keep their validated spelling. Only
coordinate tables are rounded (10 decimal places, maximum error 5e-11); their
labels, coordinate conventions and row order are preserved.
"""
import re


def _coordinate(value):
    rendered = f'{float(value):.10f}'
    return '0.0000000000' if rendered == '-0.0000000000' else rendered


def _table(name, rows):
    """Align coordinate columns without wrapping atoms or sorting k points."""
    if name not in ('unit_cell_cart', 'atoms_frac', 'atoms_cart', 'kpoints', 'kpoint_path'):
        return ['  ' + row for row in rows]
    prefix = []
    rows = list(rows)
    if rows and rows[0].lower() in ('ang', 'angstrom', 'bohr'):
        prefix.append(rows.pop(0))
    tokens = [row.split() for row in rows]
    path = name == 'kpoint_path'
    labelled = name in ('atoms_frac', 'atoms_cart') or path
    numeric_indices = (1, 2, 3, 5, 6, 7) if path else ((1, 2, 3) if labelled else (0, 1, 2))
    labels = (0, 4) if path else ((0,) if labelled else ())
    for row in tokens:
        for index in numeric_indices:
            row[index] = _coordinate(row[index])
    numeric_width = max([13, *(len(row[index]) for row in tokens for index in numeric_indices)])
    label_width = max([2, *(len(row[index]) for row in tokens for index in labels)])
    result = list(prefix)
    for row in tokens:
        if path:
            start = row[0].ljust(label_width) + '  ' + '  '.join(row[i].rjust(numeric_width) for i in (1, 2, 3))
            end = row[4].ljust(label_width) + '  ' + '  '.join(row[i].rjust(numeric_width) for i in (5, 6, 7))
            result.append('  ' + start + '    ' + end)
        elif labelled:
            result.append('  ' + row[0].ljust(label_width) + '  ' +
                          '  '.join(value.rjust(numeric_width) for value in row[1:]))
        else:
            result.append('  ' + '  '.join(value.rjust(numeric_width) for value in row))
    return result


def format_new_win(model_lines, profile_lines=()):
    """Keep related settings together in clearly separated, nonempty sections."""
    from .wannier_workflow import _win_parts
    text = '\n'.join([*model_lines, *profile_lines])
    values, blocks = _win_parts(text)
    width = max(20, *(len(key) for key in values))
    lines = [line.strip() for line in text.splitlines() if re.match(r'^\s*[!#]', line)]
    if lines:
        lines.append('')

    separator = '#' * 80

    def section(title, keys=(), block_names=()):
        keys = [key for key in keys if key in values]
        block_names = [name for name in block_names if name in blocks]
        if not keys and not block_names:
            return
        lines.extend(['# ' + title, separator])
        lines.extend(f'{key:<{width}} = {values.pop(key)}' for key in keys)
        for index, name in enumerate(block_names):
            if keys or index:
                lines.append('')
            lines.extend(['begin ' + name, *_table(name, blocks.pop(name)), 'end ' + name])
        lines.extend([separator, ''])

    def matching(title, prefixes, first=(), block_names=()):
        keys = list(first) + [key for key in values if key.startswith(prefixes) and key not in first]
        section(title, keys, block_names)

    berry_prefixes = ('berry', 'kubo_', 'sc_', 'shc_', 'kpath', 'kslice')
    has_berry = any(key.startswith(berry_prefixes) for key in values)
    has_bands = any(key.startswith(('bands_', 'fermi_surface')) for key in values)
    # Shared EF/path settings appear once, beside a calculation that uses them.
    fermi_section = ('BERRY' if has_berry else 'GYROTROPIC'
                     if any(key.startswith('gyrotropic') for key in values) else
                     'BANDS' if has_bands else 'WANNIER90')
    path_section = 'BANDS' if has_bands else 'BERRY' if has_berry else 'K-POINT PATH'

    def reference(title):
        return ('fermi_energy',) if title == fermi_section else ()

    matching('BERRY', berry_prefixes,
             ('berry', 'berry_task', 'berry_kmesh', 'fermi_energy',
              'kubo_freq_min', 'kubo_freq_max', 'kubo_freq_step') if has_berry else (),
             ('kpoint_path',) if path_section == 'BERRY' else ())
    matching('GYROTROPIC', ('gyrotropic',),
             ('gyrotropic', 'gyrotropic_task', 'gyrotropic_kmesh') + reference('GYROTROPIC'))
    section('WANNIER90', ('num_bands', 'num_wann', 'exclude_bands', 'select_projections',
                         'spinors', 'spin', 'num_elec_per_state', 'num_iter', 'num_print_cycles',
                         'conv_tol', 'conv_window', 'restart') + reference('WANNIER90'),
            ('projections',))
    matching('DISENTANGLEMENT', ('dis_',),
             ('dis_win_min', 'dis_win_max', 'dis_froz_min', 'dis_froz_max',
              'dis_num_iter', 'dis_mix_ratio', 'dis_conv_tol', 'dis_conv_window'))
    matching('BANDS', ('bands_', 'fermi_surface'), reference('BANDS'),
             ('kpoint_path',) if path_section == 'BANDS' else ())
    matching('DOS', ('dos',))
    matching('TRANSPORT', ('boltz',))
    matching('OUTPUT', ('wannier_plot', 'write_'))
    section('OTHER SETTINGS', [key for key in values if key != 'mp_grid'])
    section('STRUCTURE', block_names=('unit_cell_cart', 'atoms_frac', 'atoms_cart'))
    section('K-POINT PATH', block_names=('kpoint_path',))
    for name in list(blocks):
        if name != 'kpoints':
            section(name.upper(), block_names=(name,))
    section('KPOINTS', ('mp_grid',), ('kpoints',))
    return '\n'.join(lines).rstrip() + '\n'
