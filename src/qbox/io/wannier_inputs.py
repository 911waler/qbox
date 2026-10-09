"""Preserving QE parser and pure Wannier90 input-bundle generation.

``parse_qe(text)`` returns :class:`QEInput`. Its public structure uses row
lattice vectors in angstrom (``cell``), ordered ``(label, fractional_xyz)``
``atoms``, and ordered species labels (``species``). ``namelists`` maps
lower-case names and keys to decoded scalars; ``get`` also accepts mixed case.
``prefix``, ``outdir``, ``pseudo_dir``, ``wfcdir``, ``nbnd``, ``nat``, ``ntyp``
and ``spin_mode`` expose common values. Missing directory keys remain None
until bundle generation resolves QE's defaults against the explicit run root.

Parsing records source spans. Rewriting changes only requested values, adds
missing keys, and replaces precisely the old K_POINTS card, preserving other
cards (including trailing HUBBARD), comments, strings, and physical settings.
No operation in this module writes a file or starts a calculation.
"""
from dataclasses import dataclass, field
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re

from .kmesh import format_qe, format_wannier, validate_grid

BOHR_ANGSTROM = 0.529177210903
_NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$')
_ASSIGNMENT = re.compile(r'\b([A-Za-z][A-Za-z0-9_]*(?:\s*\([^()\n]*\))?)\s*=')
_CARDS = {'CELL_PARAMETERS', 'ATOMIC_SPECIES', 'ATOMIC_POSITIONS', 'K_POINTS',
          'HUBBARD', 'OCCUPATIONS', 'CONSTRAINTS', 'ATOMIC_FORCES', 'SOLVENTS',
          'ADDITIONAL_K_POINTS', 'CLIMBING_IMAGES', 'BEGIN_POSITIONS', 'END_POSITIONS'}


def _masked(text, strings=True):
    """Hide comments and optionally strings, retaining offsets and newlines."""
    result = list(text)
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if strings and char != '\n':
                result[index] = ' '
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    if strings:
                        result[index + 1] = ' '
                    index += 1
                else:
                    quote = None
        elif char in "'\"":
            quote = char
            if strings:
                result[index] = ' '
        elif char == '!':
            while index < len(text) and text[index] != '\n':
                result[index] = ' '
                index += 1
            continue
        index += 1
    if quote:
        raise ValueError('unterminated quoted string in QE input')
    return ''.join(result)


def _key(value):
    return re.sub(r'\s+', '', value).lower()


def _number(value, name='number'):
    if isinstance(value, bool) or not _NUMBER.fullmatch(str(value).strip()):
        raise ValueError(f'{name} must be a finite numeric literal (expressions are unsupported)')
    result = float(str(value).replace('D', 'e').replace('d', 'e'))
    if not math.isfinite(result):
        raise ValueError(f'{name} must be finite')
    return result


def _integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r'[+-]?\d+', str(value)):
        raise ValueError(f'{name} must be an integer >= {minimum}')
    result = int(value)
    if result < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return result


def _decode(value):
    value = value.strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return value[1:-1].replace(value[0] * 2, value[0])
    if value.lower() in ('.true.', 'true', '.t.'):
        return True
    if value.lower() in ('.false.', 'false', '.f.'):
        return False
    if re.fullmatch(r'[+-]?\d+', value):
        return int(value)
    if _NUMBER.fullmatch(value):
        return _number(value)
    return value


def _qe_value(value):
    if isinstance(value, bool):
        return '.true.' if value else '.false.'
    if isinstance(value, str):
        if '\n' in value or '\r' in value:
            raise ValueError('QE string values cannot contain newlines')
        return "'" + value.replace("'", "''") + "'"
    return str(value)


@dataclass
class _Namelist:
    start: int
    end: int
    close: int
    spans: dict = field(default_factory=dict)


@dataclass
class QEInput:
    text: str
    namelists: dict
    cell: list
    atoms: list
    species: list
    cards: dict
    _sections: dict = field(repr=False)

    def get(self, section, key, default=None):
        return self.namelists.get(section.lower(), {}).get(_key(key), default)

    @property
    def nat(self):
        return self.get('system', 'nat')

    @property
    def ntyp(self):
        return self.get('system', 'ntyp')

    @property
    def prefix(self):
        return self.get('control', 'prefix', 'pwscf')

    @property
    def outdir(self):
        return self.get('control', 'outdir')

    @property
    def pseudo_dir(self):
        return self.get('control', 'pseudo_dir')

    @property
    def wfcdir(self):
        return self.get('control', 'wfcdir')

    @property
    def nbnd(self):
        return self.get('system', 'nbnd')

    @property
    def spin_mode(self):
        if self.get('system', 'noncolin', False):
            return 'spinor'
        return 'collinear' if self.get('system', 'nspin', 1) == 2 else 'scalar'

    def rewrite(self, updates, kpoints=None):
        """Return edited text, retaining every byte outside targeted values/cards.

        ``updates`` is a mapping of namelist names to key/value mappings. Python
        strings are automatically quoted. ``kpoints`` is a full K_POINTS card.
        """
        edits = []
        for section_name, values in updates.items():
            section_name = section_name.lower()
            section = self._sections.get(section_name)
            missing = []
            for name, value in values.items():
                name = _key(name)
                if section and name in section.spans:
                    # Preserve even the spelling/quotes of unchanged values.
                    if self.get(section_name, name) != value:
                        start, end = section.spans[name]
                        edits.append((start, end, _qe_value(value)))
                else:
                    missing.append(f'  {name} = {_qe_value(value)},\n')
            if missing:
                if section:
                    edits.append((section.close, section.close, '\n' + ''.join(missing)))
                else:
                    edits.append((0, 0, f'&{section_name.upper()}\n' + ''.join(missing) + '/\n'))
        if kpoints is not None:
            if 'K_POINTS' in self.cards:
                start, end, _ = self.cards['K_POINTS']
                edits.append((start, end, kpoints.rstrip() + '\n'))
            else:
                edits.append((len(self.text), len(self.text), '\n' + kpoints.rstrip() + '\n'))
        text = self.text
        for start, end, replacement in sorted(edits, key=lambda item: (item[0], item[1]), reverse=True):
            text = text[:start] + replacement + text[end:]
        return text


def _parse_namelists(text):
    mask = _masked(text)
    clean = _masked(text, strings=False)
    sections, values = {}, {}
    position = 0
    while True:
        match = re.search(r'&([A-Za-z][A-Za-z0-9_]*)\b', mask[position:])
        if not match:
            break
        start, body = position + match.start(), position + match.end()
        name = match.group(1).lower()
        ending = re.search(r'/|&end\b', mask[body:], re.I)
        if not ending:
            raise ValueError(f'unterminated QE namelist &{name}')
        close, end = body + ending.start(), body + ending.end()
        if name in sections:
            raise ValueError(f'duplicate QE namelist &{name}')
        section = _Namelist(start, end, close)
        sections[name], values[name] = section, {}
        matches = list(_ASSIGNMENT.finditer(mask, body, close))
        for index, assignment in enumerate(matches):
            key = _key(assignment.group(1))
            if key in values[name]:
                raise ValueError(f'duplicate QE setting {name}.{key}')
            bound = matches[index + 1].start() if index + 1 < len(matches) else close
            value_start = assignment.end()
            while value_start < bound and clean[value_start].isspace():
                value_start += 1
            if value_start == bound:
                raise ValueError(f'missing QE value for {key}')
            if text[value_start] in "'\"":
                quote, value_end = text[value_start], value_start + 1
                while value_end < bound:
                    if text[value_end] == quote:
                        value_end += 1
                        if value_end < bound and text[value_end] == quote:
                            value_end += 1
                            continue
                        break
                    value_end += 1
            else:
                value_end = value_start
                while value_end < bound and clean[value_end] not in ',\n!':
                    value_end += 1
                while value_end > value_start and clean[value_end - 1].isspace():
                    value_end -= 1
            value = clean[value_start:value_end].strip()
            if not value:
                raise ValueError(f'missing QE value for {key}')
            values[name][key] = _decode(value)
            section.spans[key] = value_start, value_end
        position = end
    return sections, values, clean


def _determinant(cell):
    a, b, c = cell
    return (a[0] * (b[1]*c[2] - b[2]*c[1]) - a[1] * (b[0]*c[2] - b[2]*c[0])
            + a[2] * (b[0]*c[1] - b[1]*c[0]))


def rewrite_namelists(text, updates):
    """Edit namelists without requiring geometry (e.g. pw2wannier90 input).

    The same quoted-string/comment-aware source spans used for QE input keep
    prefix, directory, unrelated flags and comments byte-for-byte intact.
    """
    sections, values, _ = _parse_namelists(text)
    return QEInput(text, values, [], [], [], {}, sections).rewrite(updates)


def parse_namelists(text):
    """Return decoded scalar namelist values without requiring crystal cards."""
    return _parse_namelists(text)[1]


def _fractional(position, cell):
    determinant = _determinant(cell)
    return tuple(_determinant([position if j == i else cell[j] for j in range(3)]) / determinant for i in range(3))


def parse_qe(text):
    """Parse the supported explicit-cell QE subset, rejecting ambiguous inputs."""
    if not isinstance(text, str):
        raise ValueError('QE source must be text')
    sections, values, clean = _parse_namelists(text)
    if 'system' not in sections:
        raise ValueError('QE input requires &SYSTEM')
    system = values['system']
    if type(system.get('ibrav', 0)) is not int or system.get('ibrav', 0) != 0:
        raise ValueError('only explicit cells with ibrav=0 are supported')
    nat = _integer(system.get('nat'), 'nat')
    ntyp = _integer(system.get('ntyp'), 'ntyp')
    if type(system.get('nspin', 1)) is not int or system.get('nspin', 1) not in (1, 2, 4):
        raise ValueError('unsupported nspin')
    for key in ('prefix', 'outdir', 'pseudo_dir', 'wfcdir'):
        value = values.get('control', {}).get(key)
        if value is not None and (not isinstance(value, str) or not value or
                                  any(char in value for char in '\r\n\0')):
            raise ValueError(f'{key} must be a nonempty QE string')
    for key in ('noncolin', 'lspinorb'):
        if key in system and not isinstance(system[key], bool):
            raise ValueError(f'{key} must be a logical value')
    if system.get('noncolin', False) and system.get('nspin') == 2:
        raise ValueError('nspin=2 conflicts with noncolin=true')
    if system.get('nspin') == 4 and not system.get('noncolin', False):
        raise ValueError('nspin=4 requires noncolin=true')
    if system.get('lspinorb', False) and not system.get('noncolin', False):
        raise ValueError('lspinorb=true requires noncolin=true')
    outside = list(clean)
    for section in sections.values():
        outside[section.start:section.end] = ['\n' if char == '\n' else ' ' for char in clean[section.start:section.end]]
    lines = ''.join(outside).splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    headers = []
    for index, line in enumerate(lines):
        match = re.match(r'^\s*([A-Za-z_]+)\b(.*)$', line.rstrip('\r\n'))
        if match and match.group(1).upper() in _CARDS:
            headers.append((index, match.group(1).upper(), match.group(2).strip().strip('{}()').strip().lower()))
    cards, data = {}, {}
    for entry, (index, name, unit) in enumerate(headers):
        if name in cards:
            raise ValueError(f'duplicate QE card {name}')
        limit = headers[entry + 1][0] if entry + 1 < len(headers) else len(lines)
        content = [(i, lines[i].strip()) for i in range(index + 1, limit) if lines[i].strip()]
        required = {'CELL_PARAMETERS': 3, 'ATOMIC_SPECIES': ntyp, 'ATOMIC_POSITIONS': nat}.get(name)
        if name == 'K_POINTS':
            if unit == 'gamma':
                required = 0
            elif unit == 'automatic':
                required = 1
            elif unit in ('crystal', 'tpiba', 'crystal_b', 'tpiba_b', 'crystal_c', 'tpiba_c', ''):
                if not content:
                    raise ValueError('K_POINTS is missing point count')
                required = _integer(content[0][1], 'K_POINTS count') + 1
            else:
                raise ValueError(f'unsupported K_POINTS format {unit!r}')
        if required is not None:
            if len(content) != required:
                raise ValueError(f'{name} expected {required} data lines, found {len(content)}')
            last = content[-1][0] if required else index
        else:
            last = limit - 1
        cards[name] = offsets[index], offsets[last] + len(lines[last]), unit
        data[name] = [row for _, row in content]
    for name in ('CELL_PARAMETERS', 'ATOMIC_SPECIES', 'ATOMIC_POSITIONS'):
        if name not in cards:
            raise ValueError(f'QE input is missing {name}')
    cell_unit = cards['CELL_PARAMETERS'][2]
    if cell_unit not in ('angstrom', 'bohr'):
        raise ValueError('CELL_PARAMETERS supports only angstrom or bohr; alat is unsupported')
    cell = []
    for row in data['CELL_PARAMETERS']:
        tokens = row.split()
        if len(tokens) != 3:
            raise ValueError('CELL_PARAMETERS requires three numeric coordinates per row')
        scale = BOHR_ANGSTROM if cell_unit == 'bohr' else 1.
        cell.append(tuple(_number(x, 'cell coordinate') * scale for x in tokens))
    lengths = [math.sqrt(sum(x*x for x in vector)) for vector in cell]
    if (not all(lengths) or not all(math.isfinite(length) for length in lengths)
            or not math.isfinite(_determinant(cell))
            or abs(_determinant(cell)) <= 1e-12 * math.prod(lengths)):
        raise ValueError('CELL_PARAMETERS cell is singular')
    species = []
    for row in data['ATOMIC_SPECIES']:
        tokens = row.split()
        if len(tokens) < 3 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', tokens[0]):
            raise ValueError('invalid ATOMIC_SPECIES entry')
        if _number(tokens[1], 'atomic mass') <= 0:
            raise ValueError('atomic mass must be positive')
        if tokens[0] in species:
            raise ValueError(f'duplicate species label {tokens[0]}')
        species.append(tokens[0])
    unit = cards['ATOMIC_POSITIONS'][2]
    if unit not in ('crystal', 'angstrom', 'bohr'):
        raise ValueError('ATOMIC_POSITIONS supports only crystal, angstrom or bohr')
    atoms = []
    for row in data['ATOMIC_POSITIONS']:
        tokens = row.split()
        if len(tokens) not in (4, 7) or tokens[0] not in species:
            raise ValueError('invalid atom row or species mapping in ATOMIC_POSITIONS')
        if len(tokens) == 7 and any(value not in ('0', '1') for value in tokens[4:]):
            raise ValueError('ATOMIC_POSITIONS movement flags must be 0 or 1')
        position = tuple(_number(x, 'atom coordinate') for x in tokens[1:4])
        if unit != 'crystal':
            scale = BOHR_ANGSTROM if unit == 'bohr' else 1.
            position = _fractional(tuple(x * scale for x in position), cell)
        if not all(math.isfinite(value) for value in position):
            raise ValueError('converted fractional atom coordinates must be finite')
        atoms.append((tokens[0], position))
    if set(species) != {label for label, _ in atoms}:
        raise ValueError('every ATOMIC_SPECIES label must occur in ATOMIC_POSITIONS')
    return QEInput(text, values, cell, atoms, species, cards, sections)


def _indices(value, maximum, name):
    if value is None or value == '' or value == []:
        return []
    if isinstance(value, str):
        items = re.split(r'[\s,;]+', value.strip())
    elif isinstance(value, (tuple, list)):
        items = value
    else:
        raise ValueError(f'{name} requires integer indices or ranges')
    result = set()
    for item in items:
        interval = re.fullmatch(r'(\d+)\s*[-:]\s*(\d+)', str(item))
        if interval:
            first, last = map(int, interval.groups())
            if first > last or first < 1 or last > maximum:
                raise ValueError(f'{name} range must lie within 1..{maximum}')
            result.update(range(first, last + 1))
        else:
            number = _integer(item, name)
            if number > maximum:
                raise ValueError(f'{name} index {number} exceeds {maximum}')
            result.add(number)
    return sorted(result)


_ORBITALS = {'s': 1, 'p': 3, 'd': 5, 'f': 7, 'sp': 2, 'sp2': 3, 'sp3': 4, 'sp3d': 5, 'sp3d2': 6,
             'px': 1, 'py': 1, 'pz': 1, 'dz2': 1, 'dxz': 1, 'dyz': 1, 'dx2-y2': 1, 'dxy': 1,
             'fz3': 1, 'fxz2': 1, 'fyz2': 1, 'fz(x2-y2)': 1, 'fxyz': 1, 'fx(x2-3y2)': 1, 'fy(3x2-y2)': 1}
_L_COUNTS = {0: 1, 1: 3, 2: 5, 3: 7, -1: 2, -2: 3, -3: 4, -4: 5, -5: 6}


def _orbital_count(expression):
    total = 0
    for group in expression.lower().split(';'):
        group = group.strip()
        quantum = re.fullmatch(r'l\s*=\s*(-?\d+)(?:\s*,\s*mr\s*=\s*([\d,\s]+))?', group)
        if quantum:
            angular = int(quantum.group(1))
            if angular not in _L_COUNTS:
                raise ValueError('projection l must be -5..3')
            count = _L_COUNTS[angular]
            if quantum.group(2):
                raw = [item.strip() for item in quantum.group(2).split(',')]
                selected = _indices(raw, count, 'projection mr')
                if len(raw) != len(selected):
                    raise ValueError('duplicate projection mr indices are unsupported')
                total += len(selected)
            else:
                total += count
        else:
            for orbital in group.split(','):
                orbital = orbital.strip()
                if orbital in _ORBITALS:
                    total += _ORBITALS[orbital]
                    continue
                hybrid = re.fullmatch(r'(sp|sp2|sp3|sp3d|sp3d2)-(\d+)', orbital)
                if hybrid and 1 <= int(hybrid.group(2)) <= _ORBITALS[hybrid.group(1)]:
                    total += 1
                else:
                    raise ValueError(f'unsupported projection orbital {orbital!r}')
    return total


def projection_lines(value, qe, spin_mode=None):
    """Normalize validated projection lines and return (lines, expanded_count).

    Support labelled species, ``atom:N`` (converted to an original-cell ``f=``
    centre), explicit ``f=``/``c=`` centres, s/p/d/f and hybrids, l/mr subsets,
    and spinor ``(u)``, ``(d)``, ``(u,d)`` with optional quantization direction.
    Axes/radial/zona extensions are explicitly rejected until validated.
    """
    mode = spin_mode or qe.spin_mode
    if isinstance(value, str):
        values = value.splitlines()
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise ValueError('projections must be a list of projection strings')
    result, count = [], 0
    for entry in values:
        if not isinstance(entry, str):
            raise ValueError('each projection must be a string')
        line = entry.strip()
        if not line:
            continue
        atom = re.fullmatch(r'atom:(\d+):(.*)', line, re.I)
        if atom:
            index = _integer(atom.group(1), 'projection atom')
            if index > qe.nat:
                raise ValueError('projection atom index exceeds nat')
            line = 'f=' + ','.join(f'{x:.14g}' for x in qe.atoms[index - 1][1]) + ':' + atom.group(2)
        if line.count(':') != 1:
            raise ValueError('projection requires site:orbitals; axes/radial extensions are unsupported')
        site, orbitals = line.split(':')
        site = site.strip()
        if site in qe.species:
            multiplicity = sum(label == site for label, _ in qe.atoms)
        elif re.match(r'^[fc]\s*=', site, re.I):
            coords = site.split('=', 1)[1].split(',')
            if len(coords) != 3:
                raise ValueError('projection centre requires three coordinates')
            for coord in coords:
                _number(coord, 'projection centre')
            multiplicity = 1
        else:
            raise ValueError(f'unknown projection site {site!r}')
        spin = re.search(r'\(\s*([ud](?:\s*,\s*[ud])?)\s*\)(?:\s*\[([^\]]+)\])?\s*$', orbitals, re.I)
        components = 2 if mode == 'spinor' else 1
        if spin:
            if mode != 'spinor':
                raise ValueError('spin-component projections require noncolin spinors')
            parts = [part.strip().lower() for part in spin.group(1).split(',')]
            if len(parts) != len(set(parts)):
                raise ValueError('duplicate projection spin component')
            components = len(parts)
            if spin.group(2):
                axis = [_number(item, 'spin quantization axis') for item in spin.group(2).split(',')]
                if len(axis) != 3 or sum(x*x for x in axis) == 0:
                    raise ValueError('spin quantization axis requires three nonzero-vector components')
            orbitals = orbitals[:spin.start()]
        count += multiplicity * components * _orbital_count(orbitals)
        result.append(line)
    if not result:
        raise ValueError('explicit projections are required; random padding is not supported')
    return result, count


def _windows(config):
    windows = config.get('windows') or {}
    if not isinstance(windows, dict):
        raise ValueError('windows must be a mapping with energies in eV')
    allowed = {'dis_win_min', 'dis_win_max', 'dis_froz_min', 'dis_froz_max', 'reference', 'fermi_energy', 'reference_energy'}
    if set(windows) - allowed:
        raise ValueError('unknown energy window fields: ' + ', '.join(sorted(set(windows) - allowed)))
    reference = windows.get('reference', 'absolute')
    if reference not in ('absolute', 'qe', 'fermi'):
        raise ValueError('window reference must be absolute (QE zero) or fermi')
    shift = 0.
    if reference == 'fermi':
        energy = windows.get('fermi_energy', windows.get('reference_energy'))
        if energy is None:
            raise ValueError('relative Fermi windows require an explicit fermi_energy in eV')
        shift = _number(energy, 'fermi_energy')
    energies = {key: _number(windows[key], key) + shift for key in allowed if key.startswith('dis_') and windows.get(key) is not None}
    if not all(math.isfinite(value) for value in energies.values()):
        raise ValueError('reference-shifted energy windows must remain finite')
    for kind in ('win', 'froz'):
        lower, upper = f'dis_{kind}_min', f'dis_{kind}_max'
        if (lower in energies) != (upper in energies):
            raise ValueError(f'{kind} window requires both min and max')
        if lower in energies and energies[lower] > energies[upper]:
            raise ValueError(f'{kind} window min must not exceed max')
    if 'dis_froz_min' in energies:
        if 'dis_win_min' not in energies:
            raise ValueError('a frozen window requires an explicit outer window')
        if energies['dis_froz_min'] < energies['dis_win_min'] or energies['dis_froz_max'] > energies['dis_win_max']:
            raise ValueError('frozen window must lie within the outer window')
    return energies


def _resolved_path(value, fallback, run_root, output_dir):
    original = str(fallback if value is None else value)
    if not original or any(char in original for char in '\n\r\0'):
        raise ValueError('QE directory must be a nonempty path without control characters')
    expanded = os.path.expanduser(os.path.expandvars(original))
    if re.search(r'\$[A-Za-z_{]', expanded):
        raise ValueError(f'unresolved environment variable in QE directory {original!r}')
    target = Path(expanded)
    if not target.is_absolute():
        target = run_root / target
    if value is not None and expanded == original and run_root == output_dir:
        return original
    return os.path.relpath(os.path.normpath(target), output_dir)


def _safe_seed(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value) or value in ('.', '..'):
        raise ValueError('seed must be a safe filename basename (letters, digits, _, -, .)')
    return value


def _win_model(qe, config, grid, nbnd, channel):
    excluded = _indices(config.get('exclude_bands'), nbnd, 'exclude_bands')
    num_bands = nbnd - len(excluded)
    num_wann = _integer(config.get('num_wann'), 'num_wann')
    if num_wann > num_bands:
        raise ValueError('num_wann must not exceed nbnd minus excluded bands')
    projections, projection_count = projection_lines(config.get('projections'), qe)
    selected = _indices(config.get('select_projections'), projection_count, 'select_projections')
    if selected:
        if len(selected) != num_wann:
            raise ValueError('select_projections must select exactly num_wann projections')
    elif projection_count != num_wann:
        raise ValueError(f'expanded projection count {projection_count} must equal num_wann {num_wann}; supply explicit select_projections')
    lines = [f'num_bands = {num_bands}', f'num_wann = {num_wann}',
             'mp_grid = ' + ' '.join(map(str, grid)),
             'spinors = ' + ('true' if qe.spin_mode == 'spinor' else 'false')]
    from .wannier_sc import model_settings
    sc_equal = 'shift_current' in config.get('tasks', []) and num_wann == num_bands
    for key, value in model_settings(config).items():
        if key.startswith('dis_') and sc_equal:
            continue
        if key in ('num_iter', 'dis_num_iter', 'conv_window', 'dis_conv_window'):
            minimum = -1 if key == 'conv_window' else (0 if key == 'dis_conv_window' else 1)
            value = _integer(value, key, minimum=minimum)
        else:
            value = _number(value, key)
            if value < 0 or key == 'dis_mix_ratio' and not 0 < value <= 1:
                raise ValueError(f'{key} is outside its allowed range')
        lines.append(f'{key} = {value:.14g}')
    if channel:
        lines.append('spin = ' + channel)
    if excluded:
        lines.append('exclude_bands = ' + ', '.join(map(str, excluded)))
    if selected:
        lines.append('select_projections = ' + ', '.join(map(str, selected)))
    if not sc_equal:
        lines.extend(f'{key} = {value:.14g}' for key, value in sorted(_windows(config).items()))
    lines += ['', 'begin unit_cell_cart', 'angstrom']
    lines += [' '.join(f'{x:.14g}' for x in row) for row in qe.cell]
    lines += ['end unit_cell_cart', '', 'begin atoms_frac']
    lines += [label + ' ' + ' '.join(f'{x:.14g}' for x in point) for label, point in qe.atoms]
    lines += ['end atoms_frac', '', 'begin projections', 'angstrom', *projections, 'end projections', '', 'begin kpoints']
    points = config.get('_qe_kpoints')
    lines += ([' '.join(f'{x:.14g}' for x in point) for point in points]
              if points is not None else format_wannier(grid).rstrip().splitlines())
    lines += ['end kpoints', '']
    return lines


def render_pw2wan(prefix, outdir, seed, spin_component='none', flags=None):
    """Render the interface input; shared by new and existing workflows."""
    values = dict(prefix=prefix, outdir=outdir, seedname=seed, spin_component=spin_component,
                  write_amn=True, write_mmn=True)
    values.update(flags or {})
    return '&inputpp\n' + ''.join(f'  {key} = {_qe_value(value)},\n' for key, value in values.items()) + '/\n'


def _control_paths(qe, run_root, output_dir):
    outdir = _resolved_path(qe.outdir, os.environ.get('ESPRESSO_TMPDIR') or '.', run_root, output_dir)
    pseudo_dir = _resolved_path(qe.pseudo_dir, os.environ.get('ESPRESSO_PSEUDO') or str(Path.home() / 'espresso/pseudo'), run_root, output_dir)
    control = dict(restart_mode='from_scratch', disk_io='low', outdir=outdir, pseudo_dir=pseudo_dir)
    if qe.wfcdir is not None:
        control['wfcdir'] = _resolved_path(qe.wfcdir, outdir, run_root, output_dir)
    return control


def build_reference(qe, seed, parameters, run_root=None, output_dir=None, spin_channel=None):
    """Generate QE reference bands without constructing or altering a model.

    ``band_kpt_text`` supplies actual Wannier output coordinates, otherwise
    ``kpoint_path`` supplies labelled original-cell segments. ``nbnd`` can
    override the source value. An explicit ``spin_channel`` of up/down emits
    only that bands.x input under the given (already channel-specific) seed;
    omission emits both for a collinear source and one otherwise.
    """
    from .wannier_paths import qe_path_card, qe_band_kpt_card
    seed = _safe_seed(seed)
    run_root = Path(run_root or Path.cwd()).absolute()
    output_dir = Path(output_dir or Path.cwd()).absolute()
    if spin_channel not in (None, 'up', 'down') or (spin_channel and qe.spin_mode != 'collinear'):
        raise ValueError('spin_channel must match the collinear source')
    nbnd = _integer(parameters.get('nbnd', qe.nbnd), 'reference nbnd')
    if parameters.get('band_kpt_text') is not None:
        card = qe_band_kpt_card(parameters['band_kpt_text'])
    else:
        card = qe_path_card(parameters.get('kpoint_path'), parameters.get('bands_num_points', 100))
    control = {**_control_paths(qe, run_root, output_dir), 'calculation': 'bands'}
    files = {f'{seed}.bands.in': qe.rewrite({'control': control, 'system': {'nbnd': nbnd}}, card)}
    channels = (spin_channel,) if spin_channel else (('up', 'down') if qe.spin_mode == 'collinear' else (None,))
    for channel in channels:
        basename = f'{seed}_{channel}' if channel and spin_channel is None else seed
        fields = dict(prefix=qe.prefix, outdir=control['outdir'], filband=f'{basename}.qe.bands.dat')
        if channel:
            fields['spin_component'] = 1 if channel == 'up' else 2
        files[f'{basename}.bands.pp.in'] = '&bands\n' + ''.join(f'  {key} = {_qe_value(value)},\n' for key, value in fields.items()) + '/\n'
    return files


def build_bundle(source_text, config, source_path=None, run_root=None, output_dir=None):
    """Validate an SCF source and return ``{relative_filename: text}``.

    Required choices are seed, grid, nbnd, num_wann, projections and tasks.
    Optional num_iter and dis_num_iter are positive integer model iteration
    limits; omission preserves the native Wannier90 defaults.
    Optional channels.up/down overrides affect only the model (num_wann,
    projections, select_projections, exclude_bands, windows). Directory paths
    use the original QE working directory, defaulting to the current directory.
    Input contents and existing files are never modified by this pure generator.
    """
    from .wannier_profiles import render_profile

    if not isinstance(config, dict):
        raise ValueError('config must be a dictionary')
    config = copy.deepcopy(config)
    if config.get('mode', 'new') != 'new':
        raise ValueError('build_bundle is for new models; use the existing-result workflow')
    qe = parse_qe(source_text)
    # The QE source determines which spin channels the bundle will contain.
    # Refreshing with that mode also retracts an earlier automatic common limit.
    config['spin_mode'] = qe.spin_mode
    from .wannier_response_defaults import refresh_response_defaults
    refresh_response_defaults(config)
    from .wannier_output_defaults import can_defer_fermi
    from .wannier_sc import pending_response_parameters
    pending_fermi = can_defer_fermi(config)
    pending_response = pending_response_parameters(config)
    if pending_response:
        config['pending_response_parameters'] = pending_response
    else:
        config.pop('pending_response_parameters', None)
    if pending_fermi:
        config['pending_fermi'] = True
    else:
        config.pop('pending_fermi', None)
    calculation = str(qe.get('control', 'calculation', 'scf')).lower()
    reused_nscf = (config.get('qe_progress') or {}).get('nscf') or {}
    if calculation not in ('scf', 'nscf'):
        raise ValueError('new Wannier input requires an SCF source; relax/vc-relax initial geometry is not a final SCF structure')
    if calculation == 'nscf' and not reused_nscf.get('input'):
        raise ValueError('NSCF 来源须先通过现有网格与计算状态检查。')
    if 'OCCUPATIONS' in qe.cards or qe.get('system', 'occupations') == 'from_input':
        raise ValueError('explicit OCCUPATIONS depend on the old k mesh and cannot be transferred')
    if 'ADDITIONAL_K_POINTS' in qe.cards:
        raise ValueError('ADDITIONAL_K_POINTS is unsupported for a full Wannier mesh')
    for key in ('lelfield', 'lberry', 'lfcp', 'lrism'):
        if qe.get('control', key, False):
            raise ValueError(f'{key} special SCF mode is unsupported for Wannier NSCF conversion')
    seed = _safe_seed(config.get('seed'))
    grid = validate_grid(config.get('grid'))
    nbnd = _integer(config.get('nbnd'), 'nbnd')
    version = config.get('version', '3.1.0')
    tasks = config.get('tasks') or []
    parameters = dict(config.get('parameters') or {})
    if 'shift_current' in tasks:
        parameters.setdefault('kpoint_path', 'auto')
    run_root = Path(run_root or config.get('run_root') or Path.cwd()).absolute()
    output_dir = Path(output_dir or Path.cwd()).absolute()
    if source_path:
        config.setdefault('source', str(Path(source_path).absolute()))
    config.setdefault('run_root', str(run_root))
    qe_run_root = run_root
    if reused_nscf.get('input'):
        if list(grid) != list(reused_nscf['grid']) or nbnd != reused_nscf['nbnd']:
            raise ValueError('当前网格或能带数与已有 NSCF 不一致：'
                             + str(reused_nscf['input'])
                             + f'（网格 {reused_nscf["grid"]}，nbnd={reused_nscf["nbnd"]}）。'
                             + '请在菜单 4、5 沿用已有设置或选择其他来源；不会重写已有 NSCF。')
        qe = parse_qe(Path(reused_nscf['input']).read_text(encoding='utf-8'))
        qe_run_root = Path(reused_nscf['run_root'])
        config['_qe_kpoints'] = reused_nscf['kpoints']
    else:
        config.pop('_qe_kpoints', None)
    control = {**_control_paths(qe, qe_run_root, output_dir), 'calculation': 'nscf'}
    if 'shift_current' in tasks and qe.spin_mode == 'scalar' and qe.get('system', 'occupations', 'fixed') == 'fixed':
        control['verbosity'] = 'high'
    outdir = control['outdir']
    updates = {'control': control, 'system': dict(nbnd=nbnd, nosym=True, noinv=True)}
    if 'shift_current' in tasks:
        updates['electrons'] = {'diago_full_acc': True}
    warnings = ['Inputs generated; material properties and convergence have not been calculated.',
                'Energy windows use the original QE eigenvalue zero. Validate outer/frozen band counts at every k point after .eig exists.',
                'Suggested interpolation grids and broadenings require convergence tests.']
    if not source_path:
        warnings.append('Source path is unspecified; the supplied source text digest is recorded.')
    if qe.spin_mode == 'spinor':
        warnings.append('Spinor orbitals represent spinor amplitudes/components; scalar-orbital sign interpretations do not apply.')
    if parameters.get('path_mode') == 'automatic' or parameters.get('kpoint_path') == 'auto':
        from .wannier_paths import automatic_path
        path_result = automatic_path(qe.cell, [position for _, position in qe.atoms], [label for label, _ in qe.atoms], magnetic=qe.spin_mode != 'scalar')
        parameters['kpoint_path'] = path_result.segments
        warnings.extend(path_result.warnings)
    bundle = ({} if reused_nscf.get('input') else
              {f'{seed}.nscf.in': qe.rewrite(updates, format_qe(grid))})
    channels = ('up', 'down') if qe.spin_mode == 'collinear' else (None,)
    overrides = config.get('channels') or {}
    if not isinstance(overrides, dict) or set(overrides) - {'up', 'down'}:
        raise ValueError('channels may contain only up and down mappings')
    if overrides and qe.spin_mode != 'collinear':
        raise ValueError('channel overrides require nspin=2')
    bases, model_hashes, profiles = [], {}, []
    for channel in channels:
        model = dict(config)
        channel_config = overrides.get(channel, {}) if channel else {}
        if not isinstance(channel_config, dict) or set(channel_config) - {'num_wann', 'projections', 'select_projections', 'exclude_bands', 'windows'}:
            raise ValueError('channel overrides support num_wann/projections/select_projections/exclude_bands/windows only')
        model.update(channel_config)
        basename = f'{seed}_{channel}' if channel else seed
        bases.append(basename)
        lines = _win_model(qe, model, grid, nbnd, channel)
        profile_parameters = {key: value for key, value in parameters.items()
                              if key not in ('path_mode', 'band_kpt_text')}
        profile_parameters['num_wann'] = model['num_wann']
        profile = render_profile(tasks, profile_parameters, qe.spin_mode, version,
                                 defer_fermi=pending_fermi,
                                 defer_response=[key for key in pending_response if key != 'fermi_energy'])
        profiles.append(profile)
        warnings.extend(profile.warnings)
        from .wannier_format import format_new_win
        from .wannier_workflow import _basis
        bundle[f'{basename}.win'] = format_new_win(lines, profile.win_lines)
        model_hashes[basename] = hashlib.sha256(_basis(bundle[f'{basename}.win']).encode()).hexdigest()
        bundle[f'{basename}.pw2wan'] = render_pw2wan(qe.prefix, outdir, basename, channel or 'none', profile.pw2_flags)
    if 'qe_bands' in tasks:
        actual_kpoints = parameters.get('band_kpt_text')
        if actual_kpoints is not None:
            warnings.append('QE reference uses the actual Wannier band.kpt point list.')
        else:
            warnings.append('QE crystal_b and Wannier sample common endpoints independently. For pointwise errors, regenerate from actual seed_band.kpt.')
        bundle.update(build_reference(qe, seed, {**parameters, 'nbnd': nbnd}, qe_run_root, output_dir))
    warnings = list(dict.fromkeys(warnings))
    from .wannier_readme import new_model_lines
    readme = new_model_lines(config, seed=seed, version=version, qe=qe,
                             source_path=source_path, run_root=run_root,
                             output_dir=output_dir, outdir=outdir, bases=bases,
                             files=bundle)
    bundle[f'{seed}.README.txt'] = '\n'.join(readme) + '\n'
    metadata_name = f'{seed}.qbox.json'
    status = ('pending_occupation_reference' if pending_fermi else
              'pending_response_parameters' if pending_response else 'inputs_generated')
    metadata = dict(schema_version=1, status=status, seed=seed, version=version,
                    spin_mode=qe.spin_mode, prefix=qe.prefix, outdir=outdir, run_root=str(run_root),
                    output_dir=str(output_dir), source={'path': str(source_path) if source_path else None,
                    'sha256': hashlib.sha256(source_text.encode()).hexdigest()},
                    config=config, seeds=bases, model_sha256=model_hashes, warnings=warnings,
                    files=sorted([*bundle, metadata_name]))
    bundle[metadata_name] = json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    return bundle
