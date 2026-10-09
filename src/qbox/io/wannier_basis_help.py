"""Read-only, conservative basis guidance from a QE input and its actual UPFs.

Electron bookkeeping does not determine a useful Wannier subspace or the
unoccupied bands needed by a calculation. This helper never chooses either.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re

from .wannier_inputs import parse_qe


_NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?'
_BASIS_HELP = [
    'nbnd 是 QE 要计算的能带总数；首轮初值会在轨道数和电子容量之外留出空带。',
    'num_wann 是模型中的局域轨道数；初值按投影展开数填写，需要时可按目标能带修改。',
]


def _number(value):
    text = str(value).strip()
    if not re.fullmatch(_NUMBER, text):
        raise ValueError('invalid electron count')
    number = Decimal(text.replace('D', 'E').replace('d', 'e'))
    if not number.is_finite():
        raise ValueError('nonfinite electron count')
    return number


def _path(value, root):
    expanded = os.path.expandvars(os.fspath(value))
    if '$' in expanded:
        raise ValueError('unresolved path variable')
    path = Path(expanded).expanduser()
    return path if path.is_absolute() else root / path


def _valence(path):
    """Read only the standard UPF header, never numbers in prose or cutoffs."""
    text = re.sub(r'<!--.*?-->', '', path.read_text(encoding='utf-8'), flags=re.S)
    headers = list(re.finditer(r'<PP_HEADER\b([^>]*)>', text, re.I | re.S))
    if len(headers) != 1:
        raise ValueError('UPF needs one PP_HEADER')
    header = headers[0]
    values = re.findall(r'\bz_valence\s*=\s*([\'"])(.*?)\1', header[1], re.I | re.S)
    if values:
        if len(values) != 1:
            raise ValueError('ambiguous UPF valence')
        value = _number(values[0][1])
    else:
        # UPF v1 stores "4.000000 Z valence" inside a text PP_HEADER.
        # A following line such as "35 Suggested cutoff" is not its value.
        ending = re.search(r'</PP_HEADER\s*>', text[header.end():], re.I)
        if ending is None or header[1].rstrip().endswith('/'):
            raise ValueError('UPF lacks valence')
        body = text[header.end():header.end() + ending.start()]
        values = re.findall(r'^\s*(' + _NUMBER + r')[ \t]+Z[ \t]+valence\b[^\r\n]*$',
                            body, re.I | re.M)
        if len(values) != 1:
            raise ValueError('UPF lacks unambiguous valence')
        value = _number(values[0])
    if value <= 0:
        raise ValueError('UPF valence must be positive')
    return value


def _format(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def describe_basis(config):
    """Return nonblocking Chinese guidance; do not mutate config or any file."""
    help_lines = list(_BASIS_HELP)
    source = config.get('source')
    if not source:
        return ['无法读取电子数：请先选择 QE SCF 输入及其赝势文件。', *help_lines]
    try:
        source = Path(source).expanduser()
        if config.get('mode') == 'existing' or source.suffix.lower() == '.win':
            return ['已有 Wannier 模型的轨道数以原 .win 为准；仅凭 .win 无法读取 QE 价电子数。', *help_lines]
        qe = parse_qe(source.read_text(encoding='utf-8'))
        charge = _number(qe.get('system', 'tot_charge', 0))
    except (OSError, UnicodeError, ValueError, TypeError, InvalidOperation):
        return ['无法读取电子数：请检查所选 QE SCF 输入及 tot_charge 是否有效。', *help_lines]

    try:
        run_root = _path(config.get('run_root') or Path.cwd(), Path.cwd())
        pseudo_dir = _path(qe.pseudo_dir or os.environ.get('ESPRESSO_PSEUDO')
                           or Path.home() / 'espresso/pseudo', run_root)
        start, end, _ = qe.cards['ATOMIC_SPECIES']
        species_files = {}
        for raw in qe.text[start:end].splitlines()[1:]:
            fields = raw.split('!', 1)[0].split()
            if fields:
                species_files[fields[0]] = fields[2]
        counts = Counter(label for label, _ in qe.atoms)
        valence_sum = sum((count * _valence(_path(species_files[label], pseudo_dir))
                           for label, count in counts.items()), Decimal(0))
        electrons = valence_sum - charge
        if electrons <= 0 or not electrons.is_finite():
            raise ValueError('nonpositive electron count')
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, InvalidOperation):
        return ['无法可靠读取电子数：请检查原运行目录下的 UPF 路径、z_valence 和 tot_charge；仍可手动设置能带。', *help_lines]

    lines = [f'价电子数：{_format(electrons)}（实际 UPF 价电子合计 {_format(valence_sum)}'
             f' − tot_charge {_format(charge)}）。']
    occupation = str(qe.get('system', 'occupations', 'fixed')).lower()
    if qe.spin_mode == 'collinear':
        lines.append('共线自旋计算：上下自旋占据数取决于实际磁化，不能由总电子数确定每个通道的带数。')
    elif qe.spin_mode == 'spinor':
        lines.append('旋量计算：不能使用无自旋极化的双占据除以 2 规则；请依据实际能带和占据选择 nbnd。')
    elif occupation != 'fixed' or 'OCCUPATIONS' in qe.cards:
        lines.append('展宽、金属或自定义占据：总电子数不能确定实际占据带数，请检查 SCF 能带和占据。')
    elif electrons != electrons.to_integral_value():
        lines.append('分数电子数：不能据此确定完整双占据轨道数，请检查电荷与实际占据。')
    elif electrons % 2:
        lines.append('奇数电子数：不能构成完整双占据轨道，请检查自旋、电荷与实际占据。')
    else:
        lines.append(f'双占据轨道数参考：{_format(electrons / 2)}（价电子数 / 2）。'
                     '这只是当前无自旋极化、固定占据设置的容量下限，不代表所需空带或目标 Wannier 轨道数。')
    return [*lines, *help_lines]
