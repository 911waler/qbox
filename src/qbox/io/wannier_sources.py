"""Read-only discovery of existing SCF/NSCF inputs for a selected CIF structure."""
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from .wannier_inputs import parse_qe


_STRUCTURE = r'''
source "$1" || exit $?
qe_install_cleanup_traps
qe_prepare_structure_context "$2" || exit $?
cp -- "$QE_STRUCT_TMP" "$3" || exit $?
'''
_TOLERANCE = 1e-5  # Angstrom: only rounding differences, not relaxed geometries.


def _cif_geometry(source, directory):
    """Use the same converter as pwin, without configuring or generating SCF."""
    from .wannier_cif import _runtime_environment

    environment = _runtime_environment()
    loader = Path(__file__).resolve().parents[1] / 'legacy/load.sh'
    with tempfile.TemporaryDirectory(prefix='.qbox-wannier-structure-', dir=directory) as temporary:
        stage = Path(temporary)
        copied = stage / 'structure.cif'
        shutil.copyfile(source, copied)
        result_path = stage / 'geometry.in'
        result = subprocess.run(['bash', '-c', _STRUCTURE, 'qbox-cif-structure',
                                 str(loader), str(copied), str(result_path)],
                                cwd=stage, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-1000:]
            raise ValueError(f'无法读取 CIF 结构以核对已有 SCF（退出码 {result.returncode}）：{detail}')
        try:
            info = result_path.lstat()
            if not stat.S_ISREG(info.st_mode) or not info.st_size:
                raise ValueError('CIF 转换未返回有效的普通结构文件。')
            text = result_path.read_text(encoding='utf-8')
        except OSError as error:
            raise ValueError('CIF 转换未返回可读取的结构文件。') from error
    # Multiwfn's geometry export omits ATOMIC_SPECIES. Dummy masses/file names
    # let the established QE parser validate units and coordinates; this text
    # remains private and is never an SCF input or a published artifact.
    if not re.search(r'(?im)^\s*ATOMIC_SPECIES\b', text):
        atom_card = re.search(r'(?im)^\s*ATOMIC_POSITIONS[^\n]*\n', text)
        if atom_card is None:
            raise ValueError('CIF 转换结果缺少原子坐标。')
        labels = []
        for row in text[atom_card.end():].splitlines():
            columns = row.split('!', 1)[0].split()
            if not columns:
                continue
            if len(columns) not in (4, 7) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', columns[0]):
                break
            if columns[0] not in labels:
                labels.append(columns[0])
        text += '\nATOMIC_SPECIES\n' + ''.join(f'{label} 1 unused.UPF\n' for label in labels)
    try:
        return parse_qe(text)
    except ValueError as error:
        raise ValueError(f'CIF 转换结果的晶胞或原子坐标无效：{error}') from error


def _element(label):
    # Common QE spin species use Fe1/Fe2 or Fe_up/Fe_down. Arbitrary aliases
    # cannot be inferred safely from mass or a pseudopotential filename.
    match = re.fullmatch(r'([A-Z][a-z]?)(?:[0-9_].*)?', label)
    return match[1] if match else None


def _determinant(cell):
    a, b, c = cell
    return (a[0] * (b[1]*c[2] - b[2]*c[1]) - a[1] * (b[0]*c[2] - b[2]*c[0])
            + a[2] * (b[0]*c[1] - b[1]*c[0]))


def _canonical_cell(cell):
    """Express lattice vectors in their own orthonormal Cartesian frame."""
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def unit(vector):
        norm = math.hypot(*vector)
        return tuple(value / norm for value in vector)
    first = unit(cell[0])
    third = unit(cross(first, cell[1]))
    axes = first, cross(third, first), third
    return [tuple(sum(x*y for x, y in zip(row, axis)) for axis in axes) for row in cell]


def _same_structure(first, second):
    if len(first.atoms) != len(second.atoms):
        return False
    # A common proper Cartesian rotation is harmless. Basis changes,
    # reflections, primitive-cell transformations and supercells are excluded.
    if _determinant(first.cell) * _determinant(second.cell) <= 0:
        return False
    if any(math.dist(a, b) > _TOLERANCE for a, b in
           zip(_canonical_cell(first.cell), _canonical_cell(second.cell))):
        return False
    edges = []
    for label, position in first.atoms:
        element = _element(label)
        if element is None:
            return False
        compatible = []
        for index, (other, coordinates) in enumerate(second.atoms):
            if _element(other) != element:
                continue
            delta = [a-b-round(a-b) for a, b in zip(position, coordinates)]
            cartesian = [sum(delta[i]*first.cell[i][j] for i in range(3)) for j in range(3)]
            if sum(value*value for value in cartesian) <= _TOLERANCE**2:
                compatible.append(index)
        if not compatible:
            return False
        edges.append(compatible)
    # Match each atom once; reordering or close neighbours must not allow one
    # target atom to stand in for two distinct source atoms.
    assigned = {}
    def assign(atom, seen):
        for target in edges[atom]:
            if target in seen:
                continue
            seen.add(target)
            if target not in assigned or assign(assigned[target], seen):
                assigned[target] = atom
                return True
        return False
    return all(assign(atom, set()) for atom in range(len(edges)))


def _read_qe(path, calculation):
    if not path.is_file():
        raise ValueError('不是可读取的普通文件，或符号链接目标不存在')
    qe = parse_qe(path.read_text(encoding='utf-8'))
    if str(qe.get('control', 'calculation', 'scf')).lower() != calculation:
        raise ValueError(f'不是 calculation={calculation} 的输入文件')
    return qe


def find_existing_scf(source, directory=None):
    """Return matching SCFs, preferring the original/sanitized CIF basename.

    A malformed or mismatching same-name input raises an actionable error.
    Other invalid inputs are ignored. Conversion happens once and only after
    finding a parseable SCF. Returned absolute paths preserve symlink aliases.
    """
    return _find_existing_input(source, directory, 'scf')


def find_existing_qe(source, directory=None):
    """Prefer matching SCF inputs, falling back to existing matching NSCFs."""
    return find_existing_scf(source, directory) or _find_existing_input(source, directory, 'nscf')


def _find_existing_input(source, directory, calculation):
    kind = calculation.upper()
    source = Path(os.path.abspath(Path(source).expanduser()))
    directory = Path(os.path.abspath(Path(directory or Path.cwd()).expanduser()))
    if source.suffix.lower() != '.cif' or not source.is_file():
        raise ValueError('结构来源必须是可读取的 CIF 文件。')
    if not directory.is_dir():
        raise ValueError(f'查找已有 {kind} 的位置必须是已有目录。')
    prefix = re.sub(r'[^A-Za-z0-9_-]', '_', source.stem).strip('_')[:180] or 'structure'
    preferred = list(dict.fromkeys(directory / (stem + f'.{calculation}.in') for stem in (source.stem, prefix)))
    geometry = None
    for path in preferred:
        if not (path.exists() or path.is_symlink()):
            continue
        try:
            qe = _read_qe(path, calculation)
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError(f'同名 {kind} 输入 {path.name} 无法复用：{error}。请在菜单 2 另选 SCF/NSCF 输入。') from error
        if geometry is None:
            geometry = _cif_geometry(source, directory)
        if not _same_structure(geometry, qe):
            raise ValueError(f'同名 {kind} 输入 {path.name} 与 CIF 晶胞或原子位置不匹配；请在菜单 2 另选 SCF/NSCF 输入。')
        return [path]
    candidates = []
    paths = [directory / f'{calculation}.in', *sorted(directory.glob('*.in'))]
    for path in dict.fromkeys(paths):
        if path in preferred:
            continue
        try:
            candidates.append((path, _read_qe(path, calculation)))
        except (OSError, UnicodeError, ValueError):
            continue
    if not candidates:
        return []
    geometry = _cif_geometry(source, directory)
    return [path for path, qe in candidates if _same_structure(geometry, qe)]
