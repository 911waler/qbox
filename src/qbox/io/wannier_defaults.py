"""Conservative, editable first-run basis defaults from an SCF and its UPFs.

PP_PSWFC supplies angular channels, not material-specific energy windows or
Wannier radial functions. Repeated radial/angular channels require manual
selection until the projection interface supports distinct radial functions.
"""
from collections import Counter
from decimal import InvalidOperation
import math
import os
from pathlib import Path
import re

from .wannier_basis_help import _number, _path, _valence
from .wannier_inputs import _indices, _integer, parse_qe, projection_lines


def _positive_int(value):
    try:
        return _integer(value, '数量')
    except ValueError:
        return None


def _shells(path):
    text = re.sub(r'<!--.*?-->', '', path.read_text(encoding='utf-8'), flags=re.S)
    blocks = re.findall(r'<PP_PSWFC(?:\s[^>]*)?>(.*?)</PP_PSWFC\s*>', text, re.I | re.S)
    if len(blocks) != 1:
        raise ValueError('UPF 缺少唯一的 PP_PSWFC 原子轨道段')
    entries = re.findall(r'<PP_CHI(?:\.\d+)?\b([^>]*)>', blocks[0], re.I | re.S)
    if not entries:
        raise ValueError('UPF 的 PP_PSWFC 中没有可识别的 PP_CHI 轨道元数据')
    angular = []
    for attributes in entries:
        values = re.findall(r'\bl\s*=\s*([\'"])(.*?)\1', attributes, re.I | re.S)
        if len(values) != 1 or not re.fullmatch(r'[0-3]', values[0][1].strip()):
            raise ValueError('UPF 轨道缺少有效 l，或超出当前支持的 s/p/d/f 范围')
        angular.append(int(values[0][1]))
    if len(set(angular)) != len(angular):
        raise ValueError('UPF 有重复的同 l 径向壳层或未归并的自旋轨道分裂；当前投影语法需手动选择')
    return ';'.join('spdf'[l] for l in sorted(angular))


def _excluded(value):
    """Count unique band indices without expanding potentially large ranges."""
    if value is None or value == '' or value == []:
        return 0, 0
    items = re.split(r'[\s,;]+', value.strip()) if isinstance(value, str) else value
    if not isinstance(items, (list, tuple)):
        raise ValueError('排除能带须为编号或编号范围')
    intervals = []
    for item in items:
        match = re.fullmatch(r'(\d+)\s*[-:]\s*(\d+)', str(item))
        if match:
            first, last = map(int, match.groups())
        else:
            first = last = _integer(item, '排除能带')
        if first < 1 or last < first:
            raise ValueError('排除能带编号范围无效')
        intervals.append((first, last))
    merged = []
    for first, last in sorted(intervals):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = merged[-1][0], max(last, merged[-1][1])
        else:
            merged.append((first, last))
    return sum(last-first+1 for first, last in merged), max((last for _, last in merged), default=0)


def apply_initial_defaults(config):
    """Fill only absent new-model basis values and return Chinese explanations.

    Existing values and per-channel overrides are retained. ``basis_defaults``
    maps each filled field to its provenance; ``basis_default_notes`` contains
    nonblocking explanations, including cases requiring manual input.
    """
    if config.get('mode', 'new') != 'new' or not config.get('source'):
        return []
    source = Path(config['source']).expanduser()
    if source.suffix.lower() == '.win':
        return []
    notes = []
    try:
        qe = parse_qe(source.read_text(encoding='utf-8'))
        if str(qe.get('control', 'calculation', 'scf')).lower() != 'scf':
            return ['自动初值需要 QE SCF 输入；当前来源不是 SCF。']
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        return [f'无法从 SCF 读取首轮初值：{error}']

    provenance = config.setdefault('basis_defaults', {})
    manual = set(config.get('basis_manual_fields', []))
    def fill(key, value, reason):
        config[key] = value
        provenance[key] = reason

    for key in ('exclude_bands', 'select_projections'):
        if config.get(key) is None and key not in manual:
            fill(key, [], '首轮不自动排除能带或投影；可按目标模型修改。')
    for key in ('num_iter', 'dis_num_iter'):
        if config.get(key) is None and key not in manual:
            fill(key, 1000, 'qbox 首轮迭代上限模板为 1000；不是 Wannier90 官方默认值，也不保证收敛。')

    electrons, suggested = None, None
    try:
        root = _path(config.get('run_root') or Path.cwd(), Path.cwd())
        pseudo_dir = _path(qe.pseudo_dir or os.environ.get('ESPRESSO_PSEUDO')
                           or Path.home() / 'espresso/pseudo', root)
        start, end, _ = qe.cards['ATOMIC_SPECIES']
        filenames = {}
        for row in qe.text[start:end].splitlines()[1:]:
            fields = row.split('!', 1)[0].split()
            if fields:
                filenames[fields[0]] = fields[2]
        counts = Counter(label for label, _ in qe.atoms)
        paths = {label: _path(filenames[label], pseudo_dir) for label in qe.species}
        charge = _number(qe.get('system', 'tot_charge', 0))
        proposed_electrons = sum(counts[label] * _valence(paths[label]) for label in qe.species) - charge
        if not proposed_electrons.is_finite() or proposed_electrons <= 0:
            raise ValueError('UPF 价电子与 tot_charge 得到无效电子数')
        electrons = proposed_electrons
        suggested = []
        for label in qe.species:
            orbitals = _shells(paths[label])
            suffix = '(u,d)' if qe.spin_mode == 'spinor' else ''
            suggested.append(f'{label}:{orbitals}{suffix}')
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, InvalidOperation) as error:
        suggested = None
        notes.append(f'未自动选择原子投影：请检查实际 UPF 或手动选择轨道。原因：{error}')

    projections = config.get('projections')
    candidates = projections or (suggested if 'projections' not in manual else None)
    retained_count = None
    if candidates:
        try:
            _, count = projection_lines(candidates, qe)
            selected = _indices(config.get('select_projections'), count, 'select_projections')
            retained_count = len(selected) if selected else count
            existing_count = config.get('num_wann')
            if not projections:
                if existing_count is not None and _positive_int(existing_count) != retained_count:
                    notes.append(f'UPF 建议投影保留后为 {retained_count} 个轨道，与已有 num_wann={existing_count} 不一致；未替换已有轨道数，请手动选择投影。')
                    retained_count = None
                else:
                    fill('projections', suggested,
                         '读取各物种实际 UPF 的 PP_PSWFC/PP_CHI 角动量；不使用 PP_BETA 散射通道，不导入径向函数。')
            if config.get('num_wann') is None and retained_count is not None and 'num_wann' not in manual:
                fill('num_wann', retained_count, '按初始投影的原子数、角动量简并、自旋分量及 select_projections 展开计数。')
        except ValueError as error:
            notes.append(f'无法按当前投影设置轨道初值，请手动检查：{error}')

    nw = _positive_int(config.get('num_wann'))
    minimum = None
    excluded_max = 0
    if nw is not None and electrons is not None and electrons > 0:
        try:
            excluded_count, excluded_max = _excluded(config.get('exclude_bands'))
            capacity = math.ceil(electrons / 2) if qe.spin_mode == 'scalar' else math.ceil(electrons)
            minimum = max(_positive_int(qe.nbnd) or 0, nw + excluded_count, capacity)
            if qe.spin_mode == 'collinear':
                for channel in (config.get('channels') or {}).values():
                    channel_nw = _positive_int(channel.get('num_wann', nw))
                    if channel_nw is not None:
                        count, highest = _excluded(channel.get('exclude_bands', config.get('exclude_bands')))
                        minimum = max(minimum, channel_nw + count)
                        excluded_max = max(excluded_max, highest)
            if config.get('nbnd') is None and 'nbnd' not in manual:
                buffer = max(4, math.ceil(minimum * .25))
                proposal = minimum + buffer
                if excluded_max > proposal:
                    notes.append('排除能带编号超过首轮估计范围；请手动设置 nbnd，未自动填入。')
                else:
                    fill('nbnd', proposal, f'基数 {minimum} 取原 SCF 带数、轨道数加排除数与电子容量下限的最大值，再加 {buffer} 条首轮空带余量；需要后续检查能区覆盖。')
        except (ValueError, TypeError, AttributeError) as error:
            notes.append(f'无法估计首轮能带数，请检查能带排除/分通道设置：{error}')
    elif config.get('nbnd') is None:
        notes.append('轨道数或 UPF 电子容量信息不足，未自动估计 nbnd；请手动设置。')
    actual = _positive_int(config.get('nbnd'))
    config['nbnd_confirmed'] = actual is not None
    if actual is not None and minimum is not None and actual < minimum:
        notes.append(f'保留已有 nbnd={actual}；当前模型/电子容量要求至少 {minimum} 条，请在菜单中调整。')
    config['basis_default_notes'] = list(dict.fromkeys([*notes, *provenance.values()]))
    return config['basis_default_notes']
