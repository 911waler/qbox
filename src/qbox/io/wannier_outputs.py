"""Read-only, conservative QE SCF/NSCF output discovery.

``read_output(path, source, *, run_root=None)`` validates a single completed
PWSCF run against an SCF/NSCF input; ``discover_outputs`` returns every valid output
in the supplied directories (nonrecursive). Relative source UPF paths use
``run_root``, defaulting to the source input's parent. No executable is run.

Energy fields are in eV, on the output's unchanged QE energy reference. Fermi
energy is only an explicitly printed common Fermi energy in the final result;
HOMO/LUMO never substitute for it. Eigenvalue bounds cover the final printed
band blocks, not a validated Wannier interpolation interval. ``nbnd`` is the
reported number of Kohn-Sham states (per spin channel for collinear runs).
``gap_reference`` is a separate sampled-gap occupation reference, available
only for neutral, scalar, fixed-occupation NSCF with complete uniform-grid
eigenvalues and empty bands; it never replaces ``fermi_energy``. A finite
sampling gap is not proof of a gap throughout the interpolated Brillouin zone.

QE prints the same calculation heading for NSCF and bands. NSCF therefore
requires a readable accompanying input to establish its calculation type.
For matching, actual UPFs and their output MD5 checksums must be available;
older/stripped output without sufficient provenance is rejected, not guessed.
Input-file checks cannot prove that a subsequently edited input was the one
used historically; output geometry, cutoffs, spin, electrons, XC and UPF
checksums are independently checked wherever QE prints them.
"""
from collections import Counter
import hashlib
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace

from .wannier_basis_help import _path, _valence
from .wannier_inputs import BOHR_ANGSTROM, _fractional, parse_qe


_NUM = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?'
_FLAGS = re.I | re.M


def _float(value):
    result = float(str(value).replace('D', 'e').replace('d', 'e'))
    if not math.isfinite(result):
        raise ValueError('输出含非有限数值。')
    return result


def _value(text, expression, description):
    match = re.search(expression, text, _FLAGS)
    if match is None:
        raise ValueError(f'输出缺少{description}，无法可靠核对。')
    return _float(match[1])


def _absolute(path):
    return Path(os.path.abspath(Path(path).expanduser()))


def _input(path):
    try:
        return parse_qe(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f'无法读取并解析 QE 输入 {path}：{error}') from error


def _source(path, run_root):
    path = _absolute(path)
    qe = _input(path)
    if str(qe.get('control', 'calculation', 'scf')).lower() not in ('scf', 'nscf'):
        raise ValueError('核对来源必须是 calculation=scf 或 nscf 的 QE 输入。')
    return path, qe, _absolute(run_root) if run_root is not None else path.parent


def _companion(path, text, run_root):
    reference = re.search(r'^\s*Reading input from\s+(.+?)\s*$', text, _FLAGS)
    if reference and reference[1].strip().lower() not in ('stdin', 'standard input'):
        name = Path(reference[1].strip().strip('\'"')).expanduser()
        choices = [name] if name.is_absolute() else [path.parent / name, run_root / name]
        for candidate in choices:
            if candidate.exists() or candidate.is_symlink():
                return _absolute(candidate), _input(candidate)
    # Redirected stdin has no recorded input name. The sibling is supporting
    # evidence only; it never replaces the independent output checks below.
    sibling = path.with_suffix('.in')
    if sibling.exists() or sibling.is_symlink():
        return sibling, _input(sibling)
    return None, None


def _same_geometry(first, second):
    # Output uses 6 decimals for lattice vectors and 7 for fractional positions.
    # Permit only that printed precision; no basis/cell/supercell transforms.
    tolerance = max(1e-5, max(math.hypot(*row) for row in first.cell) * 2e-6)
    if len(first.atoms) != len(second.atoms) or any(
            math.dist(a, b) > tolerance for a, b in zip(first.cell, second.cell)):
        return False
    edges = []
    for label, point in first.atoms:
        matches = []
        for index, (other, position) in enumerate(second.atoms):
            if label != other:  # Keep magnetic species (Fe1/Fe2) distinct.
                continue
            delta = [a - b - round(a - b) for a, b in zip(point, position)]
            cartesian = [sum(delta[i] * first.cell[i][j] for i in range(3)) for j in range(3)]
            if math.hypot(*cartesian) <= tolerance:
                matches.append(index)
        if not matches:
            return False
        edges.append(matches)
    used = {}

    def assign(index, seen):
        for target in edges[index]:
            if target not in seen:
                seen.add(target)
                if target not in used or assign(used[target], seen):
                    used[target] = index
                    return True
        return False
    return all(assign(index, set()) for index in range(len(edges)))


def _geometry(text):
    nat = _value(text, r'number of atoms/cell\s*=\s*(\d+)', '原子数')
    if not nat.is_integer() or nat < 1:
        raise ValueError('输出原子数无效。')
    alat = re.search(r'celldm\(1\)\s*=\s*(' + _NUM + ')', text, re.I)
    alat = (_float(alat[1]) if alat else _value(
        text, r'lattice parameter \(alat\)\s*=\s*(' + _NUM + r')\s*a\.u\.', '晶格尺度')) * BOHR_ANGSTROM
    heading = re.search(r'crystal axes:\s*\(cart\. coord\. in units of alat\)', text, re.I)
    if heading is None or alat <= 0:
        raise ValueError('输出缺少可靠的晶胞矢量。')
    triples = r'\s*(' + _NUM + r')\s+(' + _NUM + r')\s+(' + _NUM + r')\s*'
    vectors = re.findall(r'^\s*a\(\s*([123])\s*\)\s*=\s*\(' + triples + r'\)',
                         text[heading.end():], _FLAGS)[:3]
    if len(vectors) != 3 or [row[0] for row in vectors] != ['1', '2', '3']:
        raise ValueError('输出晶胞矢量不完整。')
    cell = [tuple(_float(value) * alat for value in row[1:]) for row in vectors]
    headings = list(re.finditer(r'site n\.\s+atom\s+positions\s*\((cryst\. coord\.|alat units)\)', text, re.I))
    if not headings:
        raise ValueError('输出缺少原子坐标。')
    heading = next((item for item in headings if item[1].lower() == 'cryst. coord.'), headings[0])
    rows = re.findall(r'^\s*\d+\s+(\S+)\s+tau\(\s*\d+\s*\)\s*=\s*\(' + triples + r'\)',
                      text[heading.end():], _FLAGS)[:int(nat)]
    if len(rows) != int(nat):
        raise ValueError('输出原子坐标不完整。')
    atoms = [(row[0], tuple(_float(value) for value in row[1:])) for row in rows]
    if heading[1].lower() == 'alat units':
        atoms = [(label, _fractional(tuple(value * alat for value in point), cell)) for label, point in atoms]
    return SimpleNamespace(cell=cell, atoms=atoms)


def _xc(value):
    value = re.sub(r'[^a-z0-9]', '', str(value).lower())
    return {'slapwpbxpbc': 'pbe', 'slapz': 'pz', 'slapznogxnogc': 'pz',
            'slapwpbesolxpbesc': 'pbesol', 'slapwpsxpsc': 'pbesol'}.get(value, value)


def _upfs(qe, root, text):
    directory = _path(qe.pseudo_dir or os.environ.get('ESPRESSO_PSEUDO')
                      or Path.home() / 'espresso/pseudo', root)
    begin, end, _ = qe.cards['ATOMIC_SPECIES']
    rows = [line.split('!', 1)[0].split() for line in qe.text[begin:end].splitlines()[1:]]
    species = {row[0]: row[2] for row in rows if row}
    blocks = list(re.finditer(r'PseudoPot\.\s*#\s*\d+\s+for\s+(\S+)\s+read from file:\s*\n\s*([^\n]+)', text, re.I))
    if len(blocks) != len(species) or {block[1] for block in blocks} != set(species):
        raise ValueError('输出赝势物种记录与来源不一致或不完整。')
    valences = {}
    functionals = set()
    for index, block in enumerate(blocks):
        label = block[1]
        path = _path(species[label], directory)
        try:
            payload = path.read_bytes()
            valences[label] = float(_valence(path))
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError(f'无法读取来源 UPF {path}，无法核对赝势及电子数。') from error
        section = text[block.end():blocks[index + 1].start() if index + 1 < len(blocks) else len(text)]
        digest = re.search(r'MD5 check sum:\s*([0-9a-f]{32})\b', section, re.I)
        if digest is None or digest[1].lower() != hashlib.md5(payload).hexdigest():
            raise ValueError(f'输出赝势 {label} 的 MD5 与来源 UPF 不符，或缺少可核对的校验值。')
        header = re.search(r'<PP_HEADER\b([^>]*)>', payload.decode('utf-8'), re.I | re.S)
        functional = re.search(r'\bfunctional\s*=\s*([\'"])(.*?)\1', header[1], re.I | re.S) if header else None
        if functional:
            functionals.add(_xc(functional[2]))
    electrons = sum(Counter(label for label, _ in qe.atoms)[label] * value for label, value in valences.items())
    electrons -= _float(qe.get('system', 'tot_charge', 0))
    reported = _value(text, r'number of electrons\s*=\s*(' + _NUM + ')', '电子数')
    if abs(reported - electrons) > 0.0051:  # QE prints two decimal places.
        raise ValueError('输出电子数与来源 UPF 价电子及 tot_charge 不一致。')
    functional = qe.get('system', 'input_dft')
    if functional is not None:
        functionals = {_xc(functional)}
    match = re.search(r'Exchange-correlation\s*=\s*([^\n]+)', text, re.I)
    if not match or len(functionals) != 1 or _xc(match[1].strip()) not in functionals:
        raise ValueError('无法确认输出交换关联泛函与来源一致；请核对 input_dft 和 UPF 泛函记录。')
    return electrons


def _spin(text):
    if re.search(r'non[ -]?collinear|(?:non\s+)?magnetic calculation with spin.orbit', text, re.I):
        return 'spinor'
    if re.search(r'SPIN\s+UP|SPIN\s+DOWN|Starting magnetic structure|total magnetization', text, re.I):
        return 'collinear'
    return 'scalar'


def _card(qe, key):
    if key not in qe.cards:
        return ''
    start, end, _ = qe.cards[key]
    return '\n'.join(' '.join(line.split('!', 1)[0].lower().split())
                     for line in qe.text[start:end].splitlines() if line.split('!', 1)[0].strip())


# Both companion comparison and missing-companion protection use this single
# inventory. Mesh, band count, occupations/smearing and iterative numerical
# settings may legitimately differ between SCF and NSCF and are excluded.
_SYSTEM_DEFAULTS = {'tot_charge': 0, 'lspinorb': False, 'lda_plus_u': False,
                    'assume_isolated': 'none', 'tot_magnetization': -1,
                    'constrained_magnetization': 'none', 'vdw_corr': 'none',
                    'london': False, 'ts_vdw': False, 'xdm': False}
_SYSTEM_PHYSICAL = {'input_dft', 'exx_fraction', 'screening_parameter', 'ecutfock',
                    'esm_bc', 'esm_w', 'esm_efield', 'block', 'block_1', 'block_2',
                    'block_height', 'zgate', 'relaxz', 'edir', 'emaxpos',
                    'eopreg', 'eamp', 'lforcet'} | set(_SYSTEM_DEFAULTS)
_CONTROL_PHYSICAL = {'tefield', 'dipfield', 'lelfield', 'lfcp', 'gate'}
_MAGNETIC_PREFIXES = ('starting_magnetization(', 'angle1(', 'angle2(')
_SYSTEM_PREFIXES = ('hubbard_', 'starting_ns_eigenvalue', 'fixed_magnetization') + _MAGNETIC_PREFIXES
_OUTPUT_VERIFIED = {('system', key) for key in ('tot_charge', 'lspinorb', 'input_dft')}


def _physical_default(section, key):
    if section == 'control':
        return False
    if key.startswith(_MAGNETIC_PREFIXES):
        return 0
    return _SYSTEM_DEFAULTS.get(key)


def _physical_settings(qe):
    keys = _SYSTEM_PHYSICAL | {key for key in qe.namelists.get('system', {})
                               if key.startswith(_SYSTEM_PREFIXES)}
    settings = {('system', key): qe.get('system', key, _physical_default('system', key)) for key in keys}
    settings.update({('control', key): qe.get('control', key, False) for key in _CONTROL_PHYSICAL})
    if settings[('system', 'input_dft')] is not None:
        settings[('system', 'input_dft')] = _xc(settings[('system', 'input_dft')])
    return settings


def _requires_companion(qe):
    # Charge, SOC and XC are independently checked above. Every other explicit
    # nondefault value needs the input because the output parser cannot confirm
    # it. Unknown conditional defaults stay conservative rather than guessed.
    return bool(_card(qe, 'HUBBARD')) or any(
        (section, key) not in _OUTPUT_VERIFIED and value != _physical_default(section, key)
        for (section, key), value in _physical_settings(qe).items())


def _check_companion(source, companion):
    if not _same_geometry(source, companion) or source.spin_mode != companion.spin_mode:
        raise ValueError('对应输入的结构或自旋模式与来源 SCF 不一致。')
    first, second = _physical_settings(source), _physical_settings(companion)
    for section, key in first.keys() | second.keys():
        default = _physical_default(section, key)
        if first.get((section, key), default) != second.get((section, key), default):
            raise ValueError(f'对应输入的物理设置 {key} 与来源 SCF 不一致。')
    if _card(source, 'HUBBARD') != _card(companion, 'HUBBARD'):
        raise ValueError('对应输入的 HUBBARD 设置与来源 SCF 不一致。')


def _kind(text, companion):
    if len(re.findall(r'^\s*Program PWSCF\b', text, _FLAGS)) != 1 or len(re.findall(r'^\s*JOB DONE\.', text, _FLAGS)) != 1:
        raise ValueError('需要单次完整且以 JOB DONE 结束的 PWSCF 输出。')
    if re.search(r'Error in routine|convergence\s+NOT\s+achieved|maximum\s+(?:cpu|wall)\s+time|\bstopping\s+run|stopped by user', text, re.I):
        raise ValueError('输出报告错误、未收敛或提前终止，不能提供后处理参考。')
    if re.search(r'BFGS|Begin final coordinates|End final coordinates|Entering Dynamics|Car-Parrinello|Wentzcovitch', text, re.I):
        raise ValueError('弛豫或动力学输出不能作为所选 SCF 的能量参考。')
    scf_end = list(re.finditer(r'End of self-consistent calculation', text, re.I))
    band_end = list(re.finditer(r'End of band structure calculation', text, re.I))
    kind = str(companion.get('control', 'calculation', 'scf')).lower() if companion else None
    if kind not in (None, 'scf', 'nscf'):
        raise ValueError('对应输入不是 SCF/NSCF（bands、relax 等不接纳）。')
    if len(scf_end) == 1 and not band_end:
        if kind not in (None, 'scf') or not re.search(r'convergence has been achieved', text[scf_end[0].end():], re.I):
            raise ValueError('SCF 完成类型或电子收敛证据不足。')
        return 'scf', text[scf_end[0].end():]
    if len(band_end) == 1 and not scf_end:
        if kind != 'nscf':
            raise ValueError('无法区分 NSCF 与 bands；需要可核对的对应 NSCF 输入。')
        if re.search(r'\d+\s+eigenvalues?\s+not converged', text, re.I):
            raise ValueError('NSCF 本征值未收敛。')
        return 'nscf', text[band_end[0].end():]
    raise ValueError('输出缺少唯一完整的 SCF/NSCF 结束段。')


def _band_blocks(final, nbnd):
    """Keep final band order and Cartesian k coordinates, not occupation rows."""
    result = []
    headers = re.finditer(r'^\s*k\s*=.*?bands\s*\(ev\)\s*:\s*$', final, _FLAGS)
    for block in headers:
        coordinates = re.search(r'k\s*=\s*(.*?)\s*\(', block[0], re.I)
        point = None
        if coordinates:
            numbers = re.findall(_NUM, coordinates[1])
            if len(numbers) == 3 and not re.sub(_NUM, '', coordinates[1]).strip():
                # QE's fixed-width output may join a negative coordinate to
                # the preceding number, e.g. "0.0000-0.5774 0.1018".
                point = tuple(map(_float, numbers))
        values = []
        started = False
        for line in final[block.end():].splitlines():
            if not line.strip():
                if started:
                    break
                continue
            tokens = line.split()
            if not all(re.fullmatch(_NUM, token) for token in tokens):
                break
            values.extend(_float(token) for token in tokens)
            started = True
        if len(values) != nbnd:
            raise ValueError('输出打印的能带本征值行不完整或与 nbnd 不一致。')
        # Unrecognized coordinates prevent a gap proof, not extraction of the
        # independently printed EF/HOMO/eigenvalue range from a valid output.
        result.append((point, values))
    return result


def _energies(final, blocks, notes):
    dual = bool(re.search(r'Fermi energ(?:y|ies).*?(?:up|down|dw)|(?:up|down|dw).*?Fermi energ(?:y|ies)', final, re.I))
    values = re.findall(r'the Fermi energy is\s*(' + _NUM + r')\s*ev\b', final, re.I)
    fermi = _float(values[-1]) if values and not dual else None
    if dual:
        notes.append('输出分别报告自旋双费米能，未提供可用的共同费米能。')
    elif fermi is None:
        notes.append('输出未明确报告共同费米能；HOMO、LUMO 或中隙估计不会冒充 QE 报告值。')
    homo = lumo = None
    pairs = re.findall(r'highest occupied,\s*lowest unoccupied level\s*\(ev\)\s*:\s*(' + _NUM + r')\s+(' + _NUM + ')', final, re.I)
    if pairs:
        homo, lumo = map(_float, pairs[-1])
    else:
        occupied = re.findall(r'highest occupied level\s*\(ev\)\s*:\s*(' + _NUM + ')', final, re.I)
        if occupied:
            homo = _float(occupied[-1])
    eigenvalues = [value for _, values in blocks for value in values]
    notes.append('能量范围仅为最终打印的 QE 本征值范围，不是 Wannier 模型的可信能窗。'
                 if eigenvalues else '输出未打印最终能带本征值；无法提供能量范围参考。')
    return dict(fermi_energy=fermi, homo=homo, lumo=lumo,
                eigenvalue_min=min(eigenvalues) if eigenvalues else None,
                eigenvalue_max=max(eigenvalues) if eigenvalues else None)


def _periodic_point(point):
    values = [value % 1 for value in point]
    return tuple(0.0 if min(value, 1 - value) < 1e-8 else round(value, 8) for value in values)


def _mesh(qe):
    """Read an actual full tensor-product input mesh, never a path or Gamma hint."""
    if 'K_POINTS' not in qe.cards:
        return None
    start, end, unit = qe.cards['K_POINTS']
    lines = [line.split('!', 1)[0].split() for line in qe.text[start:end].splitlines()]
    lines = [line for line in lines if line]
    if unit == 'automatic':
        if len(lines) != 2 or len(lines[1]) != 6:
            return None
        values = [int(value) for value in lines[1]]
        grid, shift = values[:3], values[3:]
        if min(grid) < 1 or any(value not in (0, 1) for value in shift):
            return None
        from .kmesh import generate_mesh
        points = [tuple(x + offset / (2 * size) for x, offset, size in zip(point, shift, grid))
                  for point in generate_mesh(grid)]
    elif unit == 'crystal':
        count = int(lines[1][0])
        if count < 1 or len(lines) != count + 2 or any(len(line) != 4 for line in lines[2:]):
            return None
        rows = [list(map(_float, line)) for line in lines[2:]]
        if any(row[3] <= 0 or abs(row[3] - rows[0][3]) > 1e-8 * max(1, rows[0][3]) for row in rows):
            return None
        points = [row[:3] for row in rows]
    else:
        return None
    points = [_periodic_point(point) for point in points]
    axes = [sorted({point[index] for point in points}) for index in range(3)]
    grid = [len(axis) for axis in axes]
    if len(set(points)) != len(points) or math.prod(grid) != len(points):
        return None
    for axis in axes:
        gaps = [axis[index + 1] - axis[index] for index in range(len(axis) - 1)]
        gaps.append(axis[0] + 1 - axis[-1])
        if any(abs(gap - 1 / len(axis)) > 2e-8 for gap in gaps):
            return None
    return grid, points


def _klist(text, unit, count):
    heading = re.search(r'^\s*' + unit + r'\s*$', text, _FLAGS)
    if heading is None:
        return None
    rows = []
    expression = (r'^\s*k\(\s*(\d+)\s*\)\s*=\s*\(\s*(' + _NUM + r')\s+(' + _NUM +
                  r')\s+(' + _NUM + r')\s*\)\s*,\s*wk\s*=\s*(' + _NUM + r')\s*$')
    for line in text[heading.end():].splitlines():
        if not line.strip() and not rows:
            continue
        match = re.fullmatch(expression, line, re.I)
        if match is None:
            break
        rows.append((int(match[1]), tuple(_float(value) for value in match.groups()[1:4]), _float(match[5])))
    if len(rows) != count or [row[0] for row in rows] != list(range(1, count + 1)):
        return None
    if any(row[2] <= 0 or abs(row[2] - rows[0][2]) > 1e-7 for row in rows):
        return None
    return [row[1] for row in rows]


def _points_match(first, second, tolerance, periodic=False):
    if len(first) != len(second):
        return False
    assigned = set()
    for point in first:
        matches = []
        for index, other in enumerate(second):
            delta = [a - b for a, b in zip(point, other)]
            if periodic:
                delta = [value - round(value) for value in delta]
            if math.hypot(*delta) <= tolerance:
                matches.append(index)
        # Ambiguous rounded coordinates cannot prove a complete band sample.
        if len(matches) != 1 or matches[0] in assigned:
            return False
        assigned.add(matches[0])
    return True


def _same_kpoint_order(first, second):
    return len(first) == len(second) and all(
        math.hypot(*(a-b-round(a-b) for a, b in zip(point, other))) <= 2e-6
        for point, other in zip(first, second))


def _ordered_kpoints(text, qe, count):
    """Read actual QE crystal order, accounting for collinear duplication."""
    marker = re.search(r'number of k points\s*=\s*(\d+)', text, re.I)
    if marker is None:
        return None
    listed_count = int(marker[1])
    spin_count = 2 if qe.spin_mode == 'collinear' else 1
    if listed_count != count * spin_count:
        return None
    listed = text[marker.end():]
    points = _klist(listed, r'cryst\. coord\.', listed_count)
    if points is None:
        cartesian = _klist(listed, r'cart\. coord\. in units 2\s*pi/alat', listed_count)
        if cartesian is None:
            return None
        try:
            alat = _value(text, r'lattice parameter \(alat\)\s*=\s*(' + _NUM + r')\s*a\.u\.', '晶格尺度') * BOHR_ANGSTROM
            points = [tuple(sum(a*b for a, b in zip(point, row)) / alat
                            for row in qe.cell) for point in cartesian]
        except (ValueError, ZeroDivisionError):
            return None
    if spin_count == 2:
        if not _same_kpoint_order(points[:count], points[count:]):
            return None
        points = points[:count]
    return [list(point) for point in points]


def _nscf_input_matches_output(text, qe):
    """A renamed NSCF needs independent band-count and complete mesh evidence."""
    try:
        if type(qe.nbnd) is not int or qe.nbnd < 1 or qe.nbnd != _value(
                text, r'number of Kohn-Sham states\s*=\s*(\d+)', 'nbnd'):
            return False
        mesh = _mesh(qe)
        if mesh is None:
            return False
        _, expected = mesh
        actual = _ordered_kpoints(text, qe, len(expected))
        if actual is None:
            return False
        if qe.cards['K_POINTS'][2] == 'crystal':
            return _same_kpoint_order(expected, actual)
        return _points_match(expected, actual, 2e-6, True)
    except (ValueError, IndexError, TypeError, OverflowError):
        return False


def _gap_reference(text, source, companion, kind, electrons, nbnd, blocks):
    if (kind != 'nscf' or companion is None or source.spin_mode != 'scalar'
            or source.get('system', 'occupations', 'fixed') != 'fixed'
            or companion.get('system', 'occupations', 'fixed') != 'fixed'
            or abs(_float(source.get('system', 'tot_charge', 0))) > 1e-12
            or electrons <= 0 or abs(electrons - round(electrons)) > 1e-8
            or round(electrons) % 2):
        return None
    occupied = round(electrons) // 2
    if nbnd <= occupied:
        return None
    try:
        mesh = _mesh(companion)
        if mesh is None:
            return None
        grid, expected = mesh
        count = len(expected)
        marker = re.search(r'number of k points\s*=\s*(\d+)', text, re.I)
        if marker is None or int(marker[1]) != count or len(blocks) != count:
            return None
        listed = text[marker.end():]
        fractional = _klist(listed, r'cryst\. coord\.', count)
        cartesian = _klist(listed, r'cart\. coord\. in units 2\s*pi/alat', count)
        if fractional is None or cartesian is None or not _points_match(expected, fractional, 2e-6, True):
            return None
        # Tie the two printed coordinate conventions together, then verify all
        # final energy-block k points against the more precise Cartesian list.
        alat = _value(text, r'celldm\(1\)\s*=\s*(' + _NUM + ')', '晶格尺度') * BOHR_ANGSTROM
        a, b, c = source.cell
        def cross(a, b):
            return (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])
        determinant = sum(x*y for x, y in zip(a, cross(b, c)))
        reciprocal = [tuple(value * alat / determinant for value in row)
                      for row in (cross(b, c), cross(c, a), cross(a, b))]
        converted = [_fractional(point, reciprocal) for point in cartesian]
        if any(any(abs(x-y-round(x-y)) > 2e-6 for x, y in zip(first, second))
               for first, second in zip(converted, fractional)):
            return None
        if any(point is None for point, _ in blocks) or not _points_match(
                [point for point, _ in blocks], cartesian, 0.0002):
            return None
    except (ValueError, IndexError, TypeError, ZeroDivisionError):
        return None
    if any(any(a > b for a, b in zip(values, values[1:])) for _, values in blocks):
        return None
    vbm = max(values[occupied - 1] for _, values in blocks)
    cbm = min(values[occupied] for _, values in blocks)
    # QE prints these bands to 0.0001 eV. Keep a conservative 0.001 eV
    # separation; a smaller apparent gap is not reliable rounding evidence.
    if cbm - vbm <= 0.001:
        return None
    return dict(method='sampled_midgap', value_eV=(vbm + cbm) / 2, vbm=vbm, cbm=cbm,
                gap_eV=cbm - vbm, electron_count=round(electrons), occupied_bands=occupied,
                kpoint_count=count, grid=grid, basis='complete_uniform_nscf_eigenvalues',
                scope='sampled_grid_only', minimum_gap_eV=0.001)


def _read(path, source, root):
    path = _absolute(path)
    try:
        if not path.is_file():
            raise ValueError('不是可读取的普通输出文件。')
        payload = path.read_bytes()
        text = payload.decode('utf-8')
    except (OSError, UnicodeError) as error:
        raise ValueError(f'无法读取 QE 输出 {path}：{error}') from error
    companion_path, companion = _companion(path, text, root)
    renamed_nscf = (companion is None and
                    bool(re.search(r'End of band structure calculation', text, re.I)) and
                    str(source.get('control', 'calculation', 'scf')).lower() == 'nscf' and
                    not _requires_companion(source) and
                    _nscf_input_matches_output(text, source))
    if renamed_nscf:
        companion = source
    kind, final = _kind(text, companion)
    geometry = _geometry(text)
    if not _same_geometry(source, geometry):
        raise ValueError('输出晶胞、原子或物种标签与来源 SCF 不匹配。')
    if _spin(text) != source.spin_mode:
        raise ValueError('输出自旋模式与来源 SCF 不匹配。')
    soc = bool(re.search(r'(?:non\s+)?magnetic calculation with spin.orbit', text, re.I))
    if soc != bool(source.get('system', 'lspinorb', False)):
        raise ValueError('输出自旋轨道耦合设置与来源 SCF 不匹配。')
    for key, label in [('ecutwfc', 'kinetic-energy'), ('ecutrho', 'charge density')]:
        expected = source.get('system', key)
        if expected is None and key == 'ecutrho' and source.get('system', 'ecutwfc') is not None:
            expected = 4 * _float(source.get('system', 'ecutwfc'))
        actual = _value(text, re.escape(label) + r' cutoff\s*=\s*(' + _NUM + r')\s*Ry', key)
        if expected is None or abs(actual - _float(expected)) > 0.000051:
            raise ValueError(f'输出 {key} 与来源 SCF 不一致或无法核对。')
    electrons = _upfs(source, root, text)
    if companion is not None:
        _check_companion(source, companion)
    elif _requires_companion(source):
        raise ValueError('来源含附加物理设置，需要对应输入辅助核对。')
    bands = _value(text, r'number of Kohn-Sham states\s*=\s*(\d+)', 'nbnd')
    if not bands.is_integer() or bands < 1:
        raise ValueError('输出 nbnd 无效。')
    if companion and companion.nbnd is not None and companion.nbnd != int(bands):
        raise ValueError('输出 nbnd 与其对应输入不符，可能不是该输入的计算结果。')
    notes = ['已核对输出晶胞、原子、自旋、截断能、电子数、交换关联泛函及实际 UPF 的 MD5。']
    if renamed_nscf:
        notes.append('输出记录的对应输入不可用；已用所选 NSCF 输入核对完整 k 点顺序、网格及 nbnd。')
    elif companion_path:
        notes.append(f'计算类型及附加物理设置已辅助核对对应输入：{companion_path}')
    else:
        notes.append('无对应输入；SCF 类型由唯一电子收敛段确定。')
    blocks = _band_blocks(final, int(bands))
    energies = _energies(final, blocks, notes)
    gap = _gap_reference(text, source, companion, kind, electrons, int(bands), blocks)
    if gap is not None:
        notes.append('采样均匀 NSCF 网格存在正带隙：其中点仅作为未掺杂零温的占据参考，不是 QE 报告的费米能；须检查插值后全布里渊区带隙。')
    return dict(path=str(path), kind=kind, sha256=hashlib.sha256(payload).hexdigest(),
                nbnd=int(bands), notes=notes, gap_reference=gap, **energies)


def read_output(path, source, *, run_root=None):
    """Return a validated record or raise ValueError; never alter any file."""
    _, qe, root = _source(source, run_root)
    return _read(path, qe, root)


def discover_outputs(source, directories, *, run_root=None):
    """Return all compatible .out/.pwo/.log files, sorted by absolute path.

    Invalid candidates and unreadable/missing search directories are skipped.
    An unavailable/invalid source returns no candidates, so optional discovery
    cannot block manual input setup. No choice is made by mtime/name.
    """
    try:
        _, qe, root = _source(source, run_root)
    except (ValueError, OSError, UnicodeError):
        return []
    paths = set()
    for directory in directories:
        try:
            paths.update(path for path in _absolute(directory).iterdir()
                         if path.suffix.lower() in ('.out', '.pwo', '.log'))
        except OSError:
            continue
    records = []
    for path in sorted(paths):
        try:
            records.append(_read(path, qe, root))
        except (ValueError, OSError, UnicodeError):
            continue
    return records
