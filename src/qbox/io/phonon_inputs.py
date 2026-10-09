"""Validated, pure Quantum ESPRESSO phonon input generation.

SCF paths are resolved relative to the supplied SCF input directory.  Callers
running pw.x from another directory should supply an SCF with absolute outdir.
``atoms`` are fractional coordinates and ``cell`` contains row vectors in Å.
For dimension 2, ``periodic_axis`` names the nonperiodic axis (1-based); for
dimension 1 it names the periodic axis.  No function starts a calculation.
"""
from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
import re
import tempfile


_NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$')
_ASSIGN = re.compile(r'\b([a-zA-Z][a-zA-Z0-9_]*(?:\s*\([^()\n]*\))?)\s*=')
_CARDS = {'ATOMIC_SPECIES', 'ATOMIC_POSITIONS', 'CELL_PARAMETERS', 'K_POINTS',
          'HUBBARD', 'OCCUPATIONS', 'CONSTRAINTS', 'ATOMIC_FORCES', 'SOLVENTS',
          'ADDITIONAL_K_POINTS'}
_ASR = {'no', 'simple', 'crystal', 'one-dim', 'zero-dim', 'all'}


def _number(value, name):
    if isinstance(value, bool) or not _NUMBER.fullmatch(str(value).strip()):
        raise ValueError(f'{name} 必须是有限数值，不能是表达式')
    result = float(str(value).replace('D', 'e').replace('d', 'e'))
    if not math.isfinite(result):
        raise ValueError(f'{name} 必须是有限数值')
    return result


def _integer(value, name, minimum=1):
    if isinstance(value, bool) or not re.fullmatch(r'[+-]?\d+', str(value)):
        raise ValueError(f'{name} 必须是大于等于 {minimum} 的整数')
    result = int(value)
    if result < minimum:
        raise ValueError(f'{name} 必须是大于等于 {minimum} 的整数')
    return result


def _mask(text, strings=False):
    """Preserve character positions while hiding comments and optionally strings."""
    chars, quote, index = list(text), None, 0
    while index < len(text):
        char = text[index]
        if quote:
            if strings and char != '\n':
                chars[index] = ' '
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 1
                    if strings:
                        chars[index] = ' '
                else:
                    quote = None
        elif char in "'\"":
            quote = char
            if strings:
                chars[index] = ' '
        elif char == '!':
            while index < len(text) and text[index] != '\n':
                chars[index] = ' '
                index += 1
            continue
        index += 1
    if quote:
        raise ValueError('SCF 输入中引号未闭合')
    return ''.join(chars)


def _decode(raw, name):
    raw = raw.strip().rstrip(',').strip()
    if not raw:
        raise ValueError(f'SCF 中 {name} 缺少数值')
    if raw[0] in "'\"" and raw[-1] == raw[0]:
        return raw[1:-1].replace(raw[0] * 2, raw[0])
    if raw.lower() in ('.true.', '.t.'):
        return True
    if raw.lower() in ('.false.', '.f.'):
        return False
    if re.fullmatch(r'[+-]?\d+', raw):
        return int(raw)
    if _NUMBER.fullmatch(raw):
        return _number(raw, name)
    raise ValueError(f'SCF 中 {name} 的值无效：{raw}')


def _parse(text):
    clean, masked = _mask(text), _mask(text, strings=True)
    outside, sections, cursor = list(clean), {}, 0
    while match := re.search(r'&([a-zA-Z][a-zA-Z0-9_]*)\b', masked[cursor:]):
        name = match.group(1).lower()
        begin, body = cursor + match.start(), cursor + match.end()
        ending = re.search(r'/|&end\b', masked[body:], re.I)
        if ending is None:
            raise ValueError(f'SCF 的 &{name.upper()} 未闭合')
        close, end = body + ending.start(), body + ending.end()
        if name in sections:
            raise ValueError(f'SCF 中重复的 &{name.upper()}')
        assignments = list(_ASSIGN.finditer(masked, body, close))
        values = {}
        for index, assignment in enumerate(assignments):
            key = re.sub(r'\s+', '', assignment.group(1)).lower()
            limit = assignments[index + 1].start() if index + 1 < len(assignments) else close
            if key in values:
                raise ValueError(f'SCF 中重复的 {name}.{key}')
            values[key] = _decode(clean[assignment.end():limit], key)
        sections[name] = values
        outside[begin:end] = ['\n' if c == '\n' else ' ' for c in clean[begin:end]]
        cursor = end
    cards, current = {}, None
    for line in ''.join(outside).splitlines():
        line = line.strip()
        if not line:
            continue
        header = re.match(r'^([A-Za-z_]+)\b', line)
        token = header.group(1).upper() if header else ''
        if token in _CARDS:
            if token in cards:
                raise ValueError(f'SCF 中重复的 {token}')
            current = token
            cards[token] = [line[len(token):].strip().strip('{}()').strip().lower(), []]
        elif current:
            cards[current][1].append(line)
    return sections, cards


def _det(cell):
    a, b, c = cell
    return (a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def _fractional(position, cell):
    determinant = _det(cell)
    return tuple(_det([position if row == axis else cell[row] for row in range(3)]) / determinant
                 for axis in range(3))


@dataclass(frozen=True)
class Species:
    label: str
    mass: float
    pseudo: str


@dataclass(frozen=True)
class SCFInput:
    source: Path
    prefix: str
    outdir: str
    nat: int
    ntyp: int
    species: tuple
    namelists: dict
    cell: tuple
    atoms: tuple
    position_flags: tuple
    cards: dict

    def get(self, section, key, default=None):
        return self.namelists.get(section.lower(), {}).get(re.sub(r'\s+', '', key).lower(), default)

    @property
    def file_prefix(self):
        return re.sub(r'[^A-Za-z0-9_.-]', '_', self.prefix).strip('.') or 'pwscf'


def load_scf(path):
    """Read and validate source once; errors are actionable Chinese messages."""
    from .qe_lattice import build_cell

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f'SCF 输入文件不存在：{source}')
    try:
        text = source.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError(f'无法读取 SCF 输入：{source}：{exc}') from exc
    namelists, cards = _parse(text)
    if 'control' not in namelists or 'system' not in namelists:
        raise ValueError('SCF 输入必须包含 &CONTROL 和 &SYSTEM')
    control, system = namelists['control'], namelists['system']
    if str(control.get('calculation', 'scf')).lower() != 'scf':
        raise ValueError("声子计算需要 calculation='scf' 的输入及其保存数据")
    nat, ntyp = _integer(system.get('nat'), 'nat'), _integer(system.get('ntyp'), 'ntyp')
    prefix = control.get('prefix', 'pwscf')
    outdir = control.get('outdir', os.environ.get('ESPRESSO_TMPDIR', './'))
    for key, value in (('prefix', prefix), ('outdir', outdir)):
        if not isinstance(value, str) or not value.strip() or any(c in value for c in '\n\r\0'):
            raise ValueError(f'SCF 的 {key} 必须是非空字符串')
    outpath = Path(outdir).expanduser()
    if not outpath.is_absolute():
        outpath = source.parent / outpath
    for card, count in (('ATOMIC_SPECIES', ntyp), ('ATOMIC_POSITIONS', nat)):
        if card not in cards or len(cards[card][1]) != count:
            raise ValueError(f'SCF 的 {card} 必须包含 {count} 行有效数据')
    species = []
    for line in cards['ATOMIC_SPECIES'][1]:
        fields = line.split()
        if len(fields) != 3 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', fields[0]):
            raise ValueError('SCF 的 ATOMIC_SPECIES 行无效')
        mass = _number(fields[1], '原子质量')
        if mass <= 0:
            raise ValueError('原子质量必须为正数')
        if any(item.label == fields[0] for item in species):
            raise ValueError(f'ATOMIC_SPECIES 物种重复：{fields[0]}')
        species.append(Species(fields[0], mass, fields[2]))
    cell_card = cards.get('CELL_PARAMETERS')
    cell_rows = None
    if cell_card:
        if len(cell_card[1]) != 3 or any(len(row.split()) != 3 for row in cell_card[1]):
            raise ValueError('CELL_PARAMETERS 必须为 3×3 晶格矩阵')
        cell_rows = [[_number(value, '晶格坐标') for value in row.split()] for row in cell_card[1]]
    try:
        cell = tuple(tuple(row) for row in build_cell(namelists, cell_rows, cell_card[0] if cell_card else None))
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f'SCF 晶格无效：{exc}') from exc
    if not math.isfinite(_det(cell)) or abs(_det(cell)) < 1e-10:
        raise ValueError('SCF 晶格矩阵奇异，无法解析坐标')
    unit, rows = cards['ATOMIC_POSITIONS']
    if unit not in ('crystal', 'angstrom', 'bohr', 'alat', ''):
        raise ValueError(f'不支持 ATOMIC_POSITIONS 单位 {unit}')
    scale = 1.0
    if unit == 'bohr':
        scale = .529177210903
    elif unit in ('alat', ''):
        if 'celldm(1)' in system:
            scale = _number(system['celldm(1)'], 'celldm(1)') * .529177210903
        elif 'a' in system:
            scale = _number(system['a'], 'A')
        else:
            raise ValueError('ATOMIC_POSITIONS alat 需要 celldm(1) 或 A')
    atoms, flags = [], []
    labels = {item.label for item in species}
    for line in rows:
        fields = line.split()
        if len(fields) not in (4, 7) or fields[0] not in labels:
            raise ValueError('ATOMIC_POSITIONS 坐标行或物种标签无效')
        coords = tuple(_number(item, '原子坐标') for item in fields[1:4])
        if unit != 'crystal':
            coords = _fractional(tuple(value * scale for value in coords), cell)
        move = (1, 1, 1)
        if len(fields) == 7:
            if any(item not in ('0', '1') for item in fields[4:]):
                raise ValueError('ATOMIC_POSITIONS 冻结标记必须为 0 或 1')
            move = tuple(int(item) for item in fields[4:])
        atoms.append((fields[0], coords))
        flags.append(move)
    return SCFInput(source, prefix, str(outpath.resolve()), nat, ntyp, tuple(species),
                    namelists, cell, tuple(atoms), tuple(flags), cards)


@dataclass(frozen=True)
class PhononSettings:
    system: str = 'nonpolar'
    task: str = 'frequency'
    dimension: int | None = None
    q_grid: tuple | None = None
    tr2_ph: str = '1d-12'
    asr: str | None = None
    zasr: str = 'no'
    epsil: bool | None = None
    loto_disable: bool = False
    loto_2d: bool | None = None
    q_direction: tuple = (1., 0., 0.)
    huang: bool = True
    selected_atoms: tuple = ()
    periodic_axis: int | None = None
    trans: bool = True
    zeu: bool | None = None
    lraman: bool | None = None
    eth_rps: float | None = None
    eth_ns: float | None = None
    dek: float | None = None


def _lda(functional):
    value = ' '.join(str(functional).upper().split())
    return value in {'LDA', 'PZ', 'PW', 'SLA PZ NOGX NOGC', 'SLA PW NOGX NOGC'}


def _validate_raman(scf):
    if scf.get('system', 'noncolin', False) or scf.get('system', 'lspinorb', False):
        raise ValueError('Raman 暂不支持 SOC 或非共线自旋')
    if scf.get('system', 'nspin', 1) != 1:
        raise ValueError('Raman 要求 nspin=1')
    if ('HUBBARD' in scf.cards or scf.get('system', 'lda_plus_u', False)
            or any(key.startswith('hubbard_') for key in scf.namelists['system'])):
        raise ValueError('Raman 暂不支持 Hubbard / DFT+U')
    dft = scf.get('system', 'input_dft')
    if dft is not None and not _lda(dft):
        raise ValueError('Raman 要求 LDA 泛函；PBE/GGA 等不受支持')
    default_pseudo = os.environ.get('ESPRESSO_PSEUDO', str(Path.home() / 'espresso' / 'pseudo'))
    pseudo_dir = Path(scf.get('control', 'pseudo_dir', default_pseudo)).expanduser()
    if not pseudo_dir.is_absolute():
        pseudo_dir = scf.source.parent / pseudo_dir
    for species in scf.species:
        pp = pseudo_dir / species.pseudo
        try:
            content = pp.read_text(errors='replace')
        except OSError as exc:
            raise ValueError(f'Raman 兼容性未知：无法核实赝势 {pp}；请提供可读取的 NC/LDA UPF') from exc
        match = re.search(r'<PP_HEADER\b([^>]+)>', content, re.I | re.S)
        attrs = dict((key.lower(), value) for key, _, value in
                     re.findall(r'([A-Za-z_]+)\s*=\s*([\'\"])(.*?)\2', match.group(1) if match else '', re.S))
        if not attrs.get('pseudo_type') or not attrs.get('functional'):
            raise ValueError(f'Raman 兼容性未知：{pp.name} 的 UPF header 未明确给出 NC/LDA 信息')
        if (attrs['pseudo_type'].upper() != 'NC'
                or attrs.get('is_paw', '').lower() in ('true', 't', '.true.')
                or attrs.get('is_ultrasoft', '').lower() in ('true', 't', '.true.')):
            raise ValueError(f'Raman 要求 NC 赝势：{pp.name} 不是已确认的 NC')
        if not _lda(attrs['functional']):
            raise ValueError(f'Raman 要求 LDA 赝势：{pp.name} 的 functional={attrs["functional"]}')


def _check_axis(scf, dimension, axis):
    row = scf.cell[axis - 1]
    length = math.sqrt(sum(value * value for value in row))
    if any(abs(row[index]) > 1e-7 * length for index in range(3) if index != axis - 1):
        raise ValueError('低维 ASR 要求所选晶格轴与对应笛卡尔 Cartesian 轴平行')
    if any(abs(scf.cell[index][axis - 1]) > 1e-7 * length for index in range(3) if index != axis - 1):
        raise ValueError('低维晶格的所选轴必须与其他晶格方向垂直')
    if dimension == 2:
        coords = sorted(position[axis - 1] % 1 for _, position in scf.atoms)
        gaps = [b - a for a, b in zip(coords, coords[1:])] + [coords[0] + 1 - coords[-1]]
        thickness = (1 - max(gaps)) * length
        if thickness * 2 >= length - 1e-8:
            raise ValueError('二维几何检查未通过：非周期轴上的真空不足，不能确认孤立薄层')


def resolve_settings(scf, settings):
    """Fill physical defaults and reject incompatible settings before writing."""
    system = 'adsorbate' if settings.system == 'surface' else settings.system
    if system not in ('adsorbate', 'gas', 'nonpolar', 'polar'):
        raise ValueError('未知声子体系类型')
    if settings.task not in ('frequency', 'dispersion', 'ir', 'raman', 'combined'):
        raise ValueError('未知声子计算目标')
    dispersion = settings.task == 'dispersion'
    cutoff = str(scf.get('system', 'assume_isolated', '')).lower() == '2d'
    dimension = settings.dimension
    if dimension is None:
        dimension = 0 if system == 'gas' else (2 if cutoff else 3)
    if type(dimension) is not int or dimension not in (0, 1, 2, 3):
        raise ValueError('维度必须是 0、1、2 或 3')
    if system == 'gas' and dimension != 0:
        raise ValueError('气相分子必须使用零维设置')
    if dispersion and (dimension == 0 or system == 'adsorbate'):
        raise ValueError('气相或局部冻结吸附分子不支持固体声子色散')
    axis = settings.periodic_axis
    if dimension in (1, 2):
        axis = 3 if axis is None else _integer(axis, '周期/非周期轴')
        if axis not in (1, 2, 3):
            raise ValueError('周期/非周期轴必须是 1、2 或 3')
        _check_axis(scf, dimension, axis)
    elif axis is not None:
        raise ValueError('只有一维或二维体系才应设置周期/非周期轴')
    grid = tuple(_integer(value, 'q 网格') for value in (settings.q_grid if settings.q_grid is not None else (4, 4, 4)))
    if len(grid) != 3:
        raise ValueError('q 网格必须有三个正整数')
    inactive = [i for i in range(3) if (dimension == 0 or
                (dimension == 2 and i == axis - 1) or (dimension == 1 and i != axis - 1))]
    if settings.q_grid is None:
        grid = tuple(1 if i in inactive else value for i, value in enumerate(grid))
    if any(grid[i] != 1 for i in inactive):
        raise ValueError('非周期方向的 q 网格必须为 1')
    if _number(settings.tr2_ph, 'tr2_ph') <= 0:
        raise ValueError('tr2_ph 必须是正数')
    asr = settings.asr or ('no' if system == 'adsorbate' else
                           {0: 'zero-dim', 1: 'one-dim', 2: 'crystal', 3: 'crystal'}[dimension])
    if asr not in _ASR or settings.zasr not in _ASR - {'all'}:
        raise ValueError('ASR/zasr 选项无效；zasr 修正 Born 有效电荷，不能设置为 all')
    if asr == 'all' and not dispersion:
        raise ValueError("asr='all' 仅适用于 matdyn 色散插值")
    if system == 'adsorbate' and asr != 'no':
        raise ValueError('局部冻结吸附分子只能使用 asr=no，不能施加整体分子 ASR')
    if asr == 'one-dim' and dimension != 1:
        raise ValueError('one-dim ASR 需要明确的一维周期轴')
    if asr == 'zero-dim' and dimension != 0:
        raise ValueError('zero-dim ASR 只适用于孤立的完整气相分子')
    insulating = str(scf.get('system', 'occupations', 'fixed')).lower() == 'fixed'
    if settings.loto_2d is not None and type(settings.loto_2d) is not bool:
        raise ValueError('loto_2d 必须是布尔值或自动')
    loto_2d = settings.loto_2d if settings.loto_2d is not None else bool(
        cutoff and dimension == 2 and (system == 'polar' or settings.epsil is True
        or settings.task in ('ir', 'raman', 'combined') or (dispersion and insulating)))
    if settings.loto_disable and loto_2d:
        raise ValueError('loto_disable 和 loto_2d 不能同时启用')
    if loto_2d and (dimension != 2 or not cutoff or axis != 3):
        raise ValueError("loto_2d 需要二维 z 真空方向及原 SCF assume_isolated='2D'")
    direction = tuple(_number(value, 'LO-TO 方向') for value in settings.q_direction)
    if len(direction) != 3:
        raise ValueError('LO-TO 方向必须是三个数；全零表示不加 Gamma 非解析项')
    if loto_2d and abs(direction[2]) > 1e-12 and not dispersion:
        raise ValueError('二维 LO-TO 的 Gamma 接近方向必须位于 xy 平面')
    for name in ('trans', 'loto_disable', 'huang'):
        if type(getattr(settings, name)) is not bool:
            raise ValueError(f'{name} 必须是布尔值')
    for name in ('epsil', 'lraman', 'zeu'):
        if getattr(settings, name) is not None and type(getattr(settings, name)) is not bool:
            raise ValueError(f'{name} 必须是布尔值或自动')
    lraman = settings.lraman if settings.lraman is not None else settings.task in ('raman', 'combined')
    if dispersion and settings.epsil is not None:
        raise ValueError('ldisp 色散模式的 epsil 由 QE 自动决定，不能手动覆盖')
    epsil = settings.epsil if settings.epsil is not None else (
        system == 'polar' or settings.task in ('ir', 'combined') or settings.zeu is True or lraman)
    # Match QE's automatic effective-charge response when epsil and trans are on.
    # Keep an explicit False through rendering: omission would re-enable zeu.
    zeu = settings.zeu if settings.zeu is not None else bool(epsil and settings.trans and not dispersion)
    if (zeu or lraman) and not (epsil and settings.trans):
        raise ValueError('IR/Raman 需要 trans=.true. 和 epsil=.true.')
    if dispersion and (zeu or lraman):
        raise ValueError('IR/Raman 目标必须使用 Gamma 单点')
    if (not dispersion and system == 'polar' and epsil and not zeu
            and any(direction) and not settings.loto_disable):
        raise ValueError('LO-TO 非解析项需要 zeu 有效电荷；请启用 zeu 或将 Gamma 方向设为 0 0 0')
    if not dispersion and epsil and not insulating:
        raise ValueError('介电响应、IR 和 Raman 要求绝缘体（occupations=fixed）')
    if lraman:
        _validate_raman(scf)
    atoms = tuple(_integer(item, '选择原子编号') for item in settings.selected_atoms)
    if any(item > scf.nat for item in atoms) or len(set(atoms)) != len(atoms):
        raise ValueError('选择原子编号重复或超出 nat 范围')
    if system == 'adsorbate' and not atoms:
        raise ValueError('局部冻结吸附分子需要明确选择要振动的原子编号')
    if atoms and system != 'adsorbate':
        raise ValueError('局部原子选择仅用于吸附分子')
    for name in ('eth_rps', 'eth_ns', 'dek'):
        value = getattr(settings, name)
        if value is not None and _number(value, name) <= 0:
            raise ValueError(f'{name} 必须是正数')
    return replace(settings, system=system, dimension=dimension, periodic_axis=axis, q_grid=grid,
                   asr=asr, epsil=None if dispersion else epsil, zeu=zeu, lraman=lraman,
                   loto_2d=loto_2d, q_direction=direction, selected_atoms=atoms)


def _value(value):
    if isinstance(value, bool):
        return '.true.' if value else '.false.'
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return f'{value:.12g}'


def _namelist(name, entries, raw=()):
    return '&' + name + '\n' + ''.join(
        f'  {key} = {value if key in raw else _value(value)},\n' for key, value in entries.items()) + '/\n'


def _matdyn_q_rows(points, path_data):
    """Keep the numeric path intact and make its plot annotations self-contained."""
    count = len(points)
    labels = path_data.get('labels', [''] * count)
    if not isinstance(labels, (list, tuple)) or len(labels) != count:
        raise ValueError('声子路径标签数量必须与 q 点数一致')
    labels = list(labels)
    guards = path_data.get('guard_indices', [])
    if (not isinstance(guards, (list, tuple))
            or any(type(index) is not int or not 0 <= index < count for index in guards)
            or len(set(guards)) != len(guards)):
        raise ValueError('声子路径保护点索引不合法')
    guards = set(guards)
    sections = path_data.get('segments', [])
    if not isinstance(sections, list):
        raise ValueError('声子路径线段必须为对象列表')
    markers = [[] for _ in points]
    covered, previous_end = set(), -1
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError('声子路径线段必须为对象列表')
        start, end = section.get('start'), section.get('end')
        if (type(start) is not int or type(end) is not int
                or not previous_end < start < end < count):
            raise ValueError('声子路径线段索引必须有序、不重叠且每段至少两个点')
        covered.update(range(start, end + 1))
        previous_end = end
        for index, key, marker in ((start, 'start_label', 'qbox:start'), (end, 'end_label', 'qbox:end')):
            name = section.get(key, labels[index])
            if labels[index] and name != labels[index]:
                raise ValueError('声子路径线段标签与 q 点标签不一致')
            labels[index] = name
            markers[index].append(marker)
    if (sections or guards) and (not sections or covered != set(range(count)) - guards):
        raise ValueError('声子路径线段必须覆盖全部非保护点，且不包含保护点')
    for index in guards:
        if labels[index]:
            raise ValueError('声子路径保护点不能带高对称点标签')
        markers[index].append('qbox:guard')
    rows = [str(count) + (' ! qbox:path-v1' if sections else '')]
    for point, label, tags in zip(points, labels, markers):
        if (not isinstance(label, str) or any(char.isspace() or char in '!#' for char in label)
                or 'qbox:' in label.lower()):
            raise ValueError('声子路径标签必须为不含空白和保留标记的单个名称')
        comment = ' '.join(([label] if label else []) + tags)
        rows.append(' '.join(f'{value:.12g}' for value in point) + (' ! ' + comment if comment else ''))
    return '\n'.join(rows) + '\n'


def generate_inputs(scf, settings, path_data=None):
    """Return complete input text by output basename; does not touch the disk."""
    options = resolve_settings(scf, settings)
    prefix = scf.file_prefix
    dispersion = options.task == 'dispersion'
    dyn = prefix + ('.dyn' if dispersion else '.dynG')
    # Explicitly request XML for spinor input: QE 7.5 no longer enables this
    # automatically for noncolin (phq_readin). Readers use the same .xml name.
    # q2r still appends .xml to its chosen flfrc output basename.
    xml_suffix = '.xml' if (scf.get('system', 'noncolin', False)
                            or scf.get('system', 'lspinorb', False)) else ''
    ph = {'prefix': scf.prefix, 'outdir': scf.outdir, 'fildyn': dyn + xml_suffix,
          'tr2_ph': str(options.tr2_ph), 'trans': options.trans}
    ph.update({f'amass({i})': species.mass for i, species in enumerate(scf.species, 1)})
    if dispersion:
        ph.update(ldisp=True, **{f'nq{i}': value for i, value in enumerate(options.q_grid, 1)})
    else:
        ph['epsil'] = options.epsil
        if options.epsil or settings.zeu is not None:
            ph['zeu'] = options.zeu
        if options.lraman:
            ph['lraman'] = True
            for key in ('eth_rps', 'eth_ns', 'dek'):
                if getattr(options, key) is not None:
                    ph[key] = getattr(options, key)
        if options.selected_atoms:
            ph['nat_todo'] = len(options.selected_atoms)
            ph['nogg'] = True  # nat_todo is incompatible with the Gamma-only shortcut.
    ph_text = 'Qbox phonon input for ' + scf.prefix + '\n' + _namelist('INPUTPH', ph, raw=('tr2_ph',))
    if not dispersion:
        ph_text += '0.0 0.0 0.0\n'
        if options.selected_atoms:
            ph_text += ' '.join(map(str, options.selected_atoms)) + '\n'
    files = {prefix + '.ph.in': ph_text}
    if not dispersion:
        dynmat = {'fildyn': dyn + xml_suffix, 'asr': options.asr, 'filout': prefix + '.dynmat.modes',
                  'filmol': prefix + '.molden'}
        if options.dimension == 1:
            dynmat['axis'] = options.periodic_axis
        if options.selected_atoms:
            dynmat['remove_interaction_blocks'] = True
        if options.epsil and options.system == 'polar' and not options.loto_disable:
            dynmat.update({f'q({i})': value for i, value in enumerate(options.q_direction, 1)})
        if options.loto_2d:
            dynmat['loto_2d'] = True
        files[prefix + '.dynmat.in'] = _namelist('INPUT', dynmat)
        return files
    if not path_data or path_data.get('coordinate_system') != 'crystal' or not path_data.get('qpoints'):
        raise ValueError('色散输入需要以原 SCF 倒格分数坐标表示的非空声子路径')
    points = []
    for point in path_data['qpoints']:
        if len(point) != 3:
            raise ValueError('声子路径的 q 点必须有三个坐标')
        points.append(tuple(_number(value, '声子路径 q 坐标') for value in point))
    if options.dimension < 3:
        inactive = [i for i in range(3) if ((options.dimension == 2 and i == options.periodic_axis - 1)
                    or (options.dimension == 1 and i != options.periodic_axis - 1))]
        if any(abs(point[i]) > 1e-9 for point in points for i in inactive):
            raise ValueError('声子路径包含非周期方向的非零 q 坐标')
    q2r = {'fildyn': dyn + xml_suffix, 'flfrc': prefix + '.fc', 'zasr': options.zasr}
    matdyn = {'flfrc': prefix + '.fc' + xml_suffix, 'asr': options.asr, 'flfrq': prefix + '.freq',
              'q_in_cryst_coord': True, 'q_in_band_form': False}
    if options.loto_2d:
        q2r['loto_2d'] = matdyn['loto_2d'] = True
    if options.loto_disable:
        matdyn['loto_disable'] = True
    if options.asr == 'all':
        matdyn['huang'] = options.huang
        # With ldisp, insulating systems receive dielectric/Born tensors from QE.
        if str(scf.get('system', 'occupations', 'fixed')).lower() == 'fixed':
            q2r['write_lr'] = matdyn['read_lr'] = True
    files[prefix + '.q2r.in'] = _namelist('INPUT', q2r)
    files[prefix + '.matdyn.in'] = _namelist('INPUT', matdyn) + _matdyn_q_rows(points, path_data)
    files[prefix + '.path.json'] = json.dumps({**path_data, 'nat': scf.nat}, ensure_ascii=False, indent=2) + '\n'
    return files


def write_inputs(files, output_dir, overwrite=False):
    """Preflight, stage, then publish all files; restore old files on failure."""
    output = Path(output_dir).expanduser().resolve()
    for name, content in files.items():
        if Path(name).name != name or name in ('.', '..') or not isinstance(content, str):
            raise ValueError('输出文件名或内容无效')
    targets = [output / name for name in files]
    for target in targets:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f'输出目标不是普通文件：{target}')
        if target.exists() and not overwrite:
            raise ValueError(f'输出文件已存在：{target}；请明确允许覆盖')
    output.mkdir(parents=True, exist_ok=True)
    old = {target: target.read_bytes() if target.exists() else None for target in targets}
    published = []
    with tempfile.TemporaryDirectory(prefix='.qbox-phonon-', dir=output) as directory:
        stage = Path(directory)
        for name, content in files.items():
            (stage / name).write_text(content, encoding='utf-8')
        try:
            for target in targets:
                os.replace(stage / target.name, target)
                published.append(target)
        except OSError:
            for target in reversed(published):
                if old[target] is None:
                    target.unlink(missing_ok=True)
                else:
                    backup = stage / target.name
                    backup.write_bytes(old[target])
                    os.replace(backup, target)
            raise
    return targets
