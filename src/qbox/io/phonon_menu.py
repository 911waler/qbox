"""Interactive task 2: validated phonon inputs and molecular Shermo conversion."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import math
from pathlib import Path
import re
import shlex
import unicodedata


RETURN_TO_MAIN = 10
SYSTEMS = {'1': ('adsorbate', '表面/吸附模型'), '2': ('gas', '气相分子'),
           '3': ('nonpolar', '非极性材料'), '4': ('polar', '极性材料')}
TASKS = {'1': ('frequency', 'Gamma 点声子频率'), '2': ('dispersion', '声子色散'),
         '3': ('ir', '红外光谱 IR'), '4': ('raman', '拉曼光谱 Raman')}


@dataclass(frozen=True)
class PhononPreparation:
    """Validated input bundle returned to execution workflows before publication."""
    scf: object
    settings: object
    files: dict
    path_data: dict | None
    cif_file: Path | None


def _ask(input_fn, prompt):
    try:
        return input_fn(prompt).strip()
    except (EOFError, StopIteration):
        raise EOFError('输入已结束；未生成本次文件。') from None


def _choose(input_fn, output, choices, prompt, default=None):
    while True:
        answer = _ask(input_fn, prompt) or default
        if answer in choices:
            return answer
        output('请输入有效的功能编号。')


def _number(value):
    try:
        number = float(value.lower().replace('d', 'e'))
    except ValueError:
        raise ValueError('请输入有限数值。') from None
    if not math.isfinite(number):
        raise ValueError('请输入有限数值。')
    return number


def _positive(value):
    if _number(value) <= 0:
        raise ValueError('必须为正数。')
    return value.lower()


def _integer(value, minimum=1, maximum=None):
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError('请输入正整数。')
    result = int(value)
    if result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f'整数范围为 {minimum}–{maximum or "不限"}。')
    return result


def _grid(value):
    values = value.replace(',', ' ').split()
    if len(values) != 3:
        raise ValueError('网格需要三个正整数，例如 4 4 4。')
    return tuple(_integer(item) for item in values)


def _boolean(value):
    if value.lower() in ('1', 'y', 'yes', 'true', '.true.', '是'):
        return True
    if value.lower() in ('0', 'n', 'no', 'false', '.false.', '否'):
        return False
    raise ValueError('请输入 yes/no（或 1/0）。')


def parse_atom_indices(value, nat):
    """Expand only bounded integer ranges, without interpreting shell syntax."""
    if not re.fullmatch(r'\s*\d+(?:\s*-\s*\d+)?(?:\s*[, ]\s*\d+(?:\s*-\s*\d+)?)*\s*', value):
        raise ValueError('原子编号格式为 1,3,5-8。')
    result = []
    compact = re.sub(r'\s*-\s*', '-', value.strip())
    for item in re.split(r'[,\s]+', compact):
        limits = [int(part) for part in item.split('-')]
        start, end = limits[0], limits[-1]
        if start < 1 or end > nat or start > end:
            raise ValueError(f'原子编号必须在 1–{nat} 内，范围必须从小到大。')
        for index in range(start, end + 1):
            if index not in result:
                result.append(index)
    return tuple(result)


def _edit_value(current, label, parser, input_fn, output):
    while True:
        answer = _ask(input_fn, f'{label} [当前 {_display(current)}]（回车保留，b 返回）：')
        if not answer or answer.lower() == 'b':
            return current
        try:
            return parser(answer)
        except ValueError as error:
            output(f'错误：{error} 已保留原值，请重新输入。')


def _display(value):
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, (tuple, list)):
        return ' '.join(str(item) for item in value)
    return str(value) if value is not None else '自动'


def find_cif(source):
    source = Path(source)
    name = source.name
    for suffix in ('.scf.in', '.relax.in', '.vcrelax.in', '.in'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    for candidate in (source.with_name(name + '.cif'), source.with_suffix('.cif')):
        if candidate.is_file():
            return candidate
    return None


def _scf_candidates(cif):
    """Discover readable SCF inputs without creating files or guessing their data."""
    from .phonon_inputs import load_scf
    candidates = {}
    for directory in dict.fromkeys((cif.parent, Path.cwd())):
        for path in directory.iterdir():
            if path.suffix.lower() != '.in' or not path.is_file():
                continue
            try:
                scf = load_scf(path)
            except (OSError, ValueError):
                continue
            candidates[scf.source] = scf
    preferred_name = (cif.stem + '.scf.in').casefold()
    return sorted(candidates.values(), key=lambda scf: (
        scf.source.name.casefold() != preferred_name, str(scf.source)))


def _select_scf(cif, output_dir, input_fn, output):
    from .phonon_inputs import load_scf
    candidates = _scf_candidates(cif) if cif else []
    if candidates:
        output('找到以下有效 SCF 输入，请确认使用的文件：')
        for index, scf in enumerate(candidates, 1):
            output(f'{index}) {scf.source}')
    elif cif:
        from .wannier_cif import generate_scf_from_cif
        output('未找到已有 SCF 输入，进入 SCF 输入生成向导。')
        reached_eof = False

        def wizard_input(prompt):
            nonlocal reached_eof
            try:
                return _ask(input_fn, prompt)
            except EOFError:
                reached_eof = True
                raise

        Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        generated = generate_scf_from_cif(cif, output_dir=output_dir,
                                         input_fn=wizard_input, output=output)
        # The shared bridge treats EOF at its own prompts as cancellation.
        if reached_eof:
            raise EOFError('输入已结束；未生成本次声子文件。')
        return load_scf(generated) if generated is not None else None
    default = '（回车使用 1，b 返回）' if len(candidates) == 1 else '（b 返回）'
    prompt = ('选择 SCF 编号或输入 pw.x SCF 输入文件路径' if candidates
              else '请输入 pw.x SCF 输入文件路径') + default + '：'
    while True:
        answer = _ask(input_fn, prompt)
        if answer.lower() == 'b':
            return None
        if not answer:
            if len(candidates) == 1:
                return candidates[0]
            output('请明确选择一个 SCF 文件，或输入 b 返回。')
            continue
        if candidates and answer.isdecimal():
            index = int(answer)
            if 1 <= index <= len(candidates):
                return candidates[index - 1]
            output('SCF 编号无效，请重新选择。')
            continue
        path = Path(answer).expanduser()
        if path.suffix.lower() == '.cif':
            output('CIF 是结构文件；此处需要已有 pw.x SCF 输入文件，请重新输入或 b 返回。')
            continue
        try:
            return load_scf(path)
        except (OSError, ValueError) as error:
            output(f'错误：{error} 请重新输入 SCF 路径，或 b 返回。')


def _load_source(source, output_dir, input_fn, output):
    from .phonon_inputs import load_scf
    if source:
        path = Path(source).expanduser()
        if path.suffix.lower() != '.cif':
            return load_scf(path), None
        cif = path.resolve()
        if not cif.is_file():
            raise ValueError(f'CIF 结构文件不存在：{cif}')
        output(f'CIF：{cif}')
        return _select_scf(cif, output_dir, input_fn, output), cif
    return _select_scf(None, output_dir, input_fn, output), None


def _advanced_fields(settings):
    fields = {}
    dispersion = settings.task == 'dispersion'
    if dispersion:
        fields['1'] = ('q_grid', '均匀 q 网格', _grid)
    fields.update({
        '2': ('tr2_ph', '收敛阈值 tr2_ph', _positive),
        '3': ('asr', '声学和规则 ASR（no/simple/crystal/one-dim/zero-dim/all）', str),
        '4': ('dimension', '周期维度（0=分子，1/2/3=周期体系）', lambda v: _integer(v, 0, 3)),
    })
    if settings.dimension in (1, 2):
        fields['5'] = ('periodic_axis', '轴方向（1=x，2=y，3=z；二维为非周期轴，一维为周期轴）',
                       lambda v: _integer(v, 1, 3))
    if dispersion:
        fields['6'] = ('points_per_segment', '每段路径采样点数（含端点）', lambda v: _integer(v, 2))
        fields['7'] = ('cif_file', 'CIF 来源（- 使用 SCF 结构）', lambda v: None if v == '-' else Path(v).expanduser())
        fields['13'] = ('zasr', 'q2r 电荷声学和规则 zasr（no/simple/crystal/one-dim/zero-dim）', str)
    if not dispersion and (settings.system == 'polar' or settings.task in ('ir', 'raman', 'combined')):
        fields['8'] = ('epsil', '介电张量/Born 电荷 epsil（yes/no）', _boolean)
    if settings.system == 'polar' and dispersion:
        fields['9'] = ('loto_disable', '禁用插值路径 Gamma 点 LO–TO 附加项（yes/no；不关闭全部长程项）', _boolean)
    if settings.system == 'polar' and settings.dimension == 2:
        fields['10'] = ('loto_2d', '二维 LO–TO 修正 loto_2d（yes/no）', _boolean)
    if settings.system == 'polar' and not dispersion:
        def direction(value):
            parts = value.split()
            if len(parts) != 3:
                raise ValueError('方向需要三个实数。')
            values = tuple(_number(part) for part in parts)
            return values
        fields['11'] = ('q_direction', 'Gamma 点 LO–TO 方向 q(1..3)（0 0 0 不添加该项）', direction)
    if settings.asr == 'all':
        fields['12'] = ('huang', 'Huang 条件（yes/no）', _boolean)
    if settings.system == 'adsorbate':
        fields['14'] = ('selected_atoms', '参与计算的原子编号', None)
    if settings.task == 'raman':
        fields.update({
            '15': ('lraman', 'Raman 响应 lraman（yes/no）', _boolean),
            '16': ('eth_rps', 'Raman 迭代阈值 eth_rps', lambda v: _number(_positive(v))),
            '17': ('eth_ns', 'Raman 非自洽阈值 eth_ns', lambda v: _number(_positive(v))),
            '18': ('dek', 'Raman 差分步长 dek', lambda v: _number(_positive(v))),
        })
    if not dispersion and (settings.epsil or settings.task in ('ir', 'raman', 'combined')):
        fields['19'] = ('zeu', 'Born 有效电荷 zeu（yes/no）', _boolean)
    if settings.task in ('ir', 'raman', 'combined'):
        fields['20'] = ('trans', '计算声子响应 trans（yes/no）', _boolean)
    return fields


def edit_advanced(scf, settings, path_options, input_fn, output):
    from .phonon_inputs import resolve_settings
    while True:
        output('\n高级设置')
        fields = _advanced_fields(settings)
        for key, (name, label, _) in fields.items():
            current = path_options.get(name) if name in path_options else getattr(settings, name)
            output(f'{key}) {label}：{_display(current)}')
        output('0) 返回设置摘要')
        choice = _choose(input_fn, output, set(fields) | {'0'}, '选择参数：', '0')
        if choice == '0':
            return settings
        name, label, parser = fields[choice]
        if name == 'selected_atoms':
            parser = lambda value: parse_atom_indices(value, scf.nat)
        current = path_options.get(name) if name in path_options else getattr(settings, name)
        while True:
            value = _edit_value(current, label, parser, input_fn, output)
            try:
                if name in path_options:
                    if name == 'cif_file' and value is not None and not value.is_file():
                        raise ValueError(f'未找到 CIF 文件：{value}')
                    path_options[name] = value
                else:
                    changes = {name: value}
                    if name == 'epsil' and settings.task == 'frequency':
                        changes['zeu'] = value
                    if name == 'dimension' and value != settings.dimension:
                        changes.update(asr=None, periodic_axis=None, loto_2d=None, q_grid=None)
                        if value in (1, 2):
                            changes['periodic_axis'] = _edit_value(
                                3, '非周期轴' if value == 2 else '周期轴',
                                lambda v: _integer(v, 1, 3), input_fn, output)
                    if name == 'periodic_axis' and settings.dimension in (1, 2):
                        changes['q_grid'] = None
                    settings = resolve_settings(scf, replace(settings, **changes))
                break
            except ValueError as error:
                output(f'错误：{error} 已保留原值，请重新输入。')


def _summary(scf, settings, path_options, output):
    def field(label, value):
        width = sum(2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
                    for char in label)
        output(f'  {label}{" " * max(2, 24 - width)}{value}')

    def path(label, value):
        output(f'  {label}：')
        output(f'    {value}')

    system_label = next(label for name, label in SYSTEMS.values() if name == settings.system)
    task_label = next((label for name, label in TASKS.values() if name == settings.task), 'Gamma 点 IR + Raman')
    output('\n声子输入 · 设置摘要')
    output('-' * 56)
    output('[计算任务]')
    field('体系类型', system_label)
    field('计算目标', task_label)
    field('周期维度', f'{settings.dimension}D')
    field('原子数', scf.nat)
    if settings.system == 'adsorbate':
        field('参与计算的原子', _display(settings.selected_atoms))

    output('\n[计算参数]')
    field('收敛阈值 tr2_ph', settings.tr2_ph)
    field('声学和规则 ASR', settings.asr)
    if settings.task == 'dispersion':
        field('均匀 q 网格', _display(settings.q_grid))
        field('路径每段采样', f'{path_options["points_per_segment"]} 点（含端点）')

    output('\n[文件与目录]')
    field('文件前缀 prefix', scf.prefix)
    path('SCF 输入', scf.source)
    path('SCF 数据目录 outdir', scf.outdir)
    if settings.task == 'dispersion':
        path('高对称路径的结构来源', path_options['cif_file'] or 'SCF 结构（SeeK-path）')

    if settings.task == 'dispersion':
        output('\n[响应设置]')
        field('介电张量 / Born 电荷', '自动（ph.x）')
    elif settings.system == 'polar' or settings.task in ('ir', 'raman', 'combined'):
        output('\n[响应设置]')
        field('epsil（介电响应）', _display(settings.epsil))
        field('zeu（Born 电荷）', _display(settings.zeu))
        field('loto_2d', _display(settings.loto_2d))
        field('loto_disable', _display(settings.loto_disable))
    if settings.task == 'raman':
        field('lraman（Raman 响应）', _display(settings.lraman))
    output('\n' + '-' * 56)
    output('  0) 生成（回车）')
    output('  1) 高级设置')
    output('  2) 返回')


def _shermo_text(scf, frequencies, selected_atoms):
    masses = {item.label: item.mass for item in scf.species}
    lines = ['*E', '  Input electronic energy in Hartree unit rather than Ry unit.', '*wavenum']
    lines.extend(frequencies)
    lines.append('*atoms')
    for index in selected_atoms:
        label, fractional = scf.atoms[index - 1]
        xyz = [sum(fractional[j] * scf.cell[j][i] for j in range(3)) for i in range(3)]
        # ATOMIC_SPECIES labels may identify multiple species of one element.
        match = re.match(r'[A-Z][a-z]?', label)
        if match is None:
            raise ValueError(f'无法从原子类型 {label} 确定元素符号。')
        lines.append(f'{match[0]}\t{masses[label]}\t' + '    '.join(f'{v:.9f}' for v in xyz))
    return '\n'.join(lines + ['*elevel', '0.00    1', ''])


def _thermo(scf, system, output_dir, input_fn, output):
    prefix = scf.file_prefix
    default = Path(output_dir) / (f'{prefix}.molden' if system == 'gas' else 'ph.out')
    if system == 'gas' and not default.exists() and (Path(output_dir) / 'dynmat.mold').exists():
        default = Path(output_dir) / 'dynmat.mold'
    if system != 'gas' and not default.exists() and (Path(output_dir) / f'{prefix}.ph.out').exists():
        default = Path(output_dir) / f'{prefix}.ph.out'
    prompt = 'dynmat.mold' if system == 'gas' else 'ph.x 输出'
    raw = _ask(input_fn, f'请输入 {prompt} 文件 [默认 {default}]：')
    source = Path(raw).expanduser() if raw else default
    text = source.read_text(encoding='utf-8')
    if system == 'gas':
        section = re.search(r'\[?FREQ\]?\s*\n(.*?)\[?FR-COORD\]?', text, re.S | re.I)
        raw_frequencies = section[1].splitlines() if section else text.splitlines()[2:]
        frequencies = []
        for line in raw_frequencies:
            value = line.strip()
            if 'FR-COORD' in value.upper():
                break
            if not value:
                continue
            if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', value):
                raise ValueError(f'频率 {value!r} 不是支持的普通十进制形式；不支持指数记数法。')
            if _number(value) > 0:
                frequencies.append(value)
        selected = tuple(range(1, scf.nat + 1))
    else:
        atoms = re.search(r'Compute atoms[^\n]*', text)
        if atoms is None:
            raise ValueError('ph.x 输出缺少 Compute atoms，不能确定吸附原子。')
        selected = parse_atom_indices(' '.join(re.findall(r'\d+', atoms[0])), scf.nat)
        # Preserve the legacy contract: the second column identifies the mode.
        modes = re.findall(r'^\s*\d+\s+(\d+)\s+[^\n]*To be done', text, re.M)
        found = dict(re.findall(r'freq\s*\(\s*(\d+)\s*\)\s*=.*?=\s*([-+\d.eEdD]+)\s*\[?cm', text))
        if not modes:
            raise ValueError('ph.x 输出缺少 To be done 模式编号。')
        missing = [mode for mode in modes if mode not in found]
        if missing:
            raise ValueError('ph.x 输出缺少所选模式的频率：' + ', '.join(missing))
        frequencies = [found[mode] for mode in modes]
    if not frequencies:
        raise ValueError('未找到可用于 Shermo 的振动频率。')
    output(f'设置摘要：将 {len(frequencies)} 个 Gamma 振动模式转换为 {prefix}.shm。')
    choice = _choose(input_fn, output, {'0', '2'}, '0) 生成（回车）  2) 返回：', '0')
    if choice == '2':
        return False
    files = {f'{prefix}.shm': _shermo_text(scf, frequencies, selected),
             f'{prefix}.README.txt': _shermo_readme(scf, system)}
    paths = _publish(files, output_dir, input_fn, output)
    if paths is None:
        return False
    for path in paths:
        output(f'已生成：{path}')
    return True


def _publish(files, output_dir, input_fn, output):
    from .phonon_inputs import write_inputs
    existing = [Path(output_dir) / name for name in files if (Path(output_dir) / name).exists()]
    if existing:
        output('以下输出文件已存在：')
        for path in existing:
            output(f'  {path}')
        choice = _choose(input_fn, output, {'0', '1'}, '1) 覆盖本批同名文件  0) 返回（默认）：', '0')
        if choice == '0':
            return None
    return write_inputs(files, output_dir, overwrite=bool(existing))


def _phonon_readme(scf, settings, output_dir):
    quote = shlex.quote
    prefix = scf.file_prefix
    steps = [
        ('自洽计算（SCF） / Self-consistent calculation (SCF)',
         f'pw.x -in {quote(scf.source.name)} > scf.out'),
        ('声子响应（PH） / Phonon response (PH)',
         f'mpirun -np 32 ph.x -in {quote(prefix + ".ph.in")} > ph.out'),
    ]
    if settings.task == 'dispersion':
        steps.extend([
            ('实空间力常数（Q2R） / Real-space force constants (Q2R)',
             f'q2r.x -in {quote(prefix + ".q2r.in")} > q2r.out'),
            ('路径上的声子频率（MATDYN） / Phonon frequencies along the path (MATDYN)',
             f'matdyn.x -in {quote(prefix + ".matdyn.in")} > matdyn.out'),
        ])
    else:
        steps.append(('Gamma 点频率及响应后处理（DYNMAT） / Gamma-point frequency and response postprocessing (DYNMAT)',
            f'dynmat.x -in {quote(prefix + ".dynmat.in")} > dynmat.out'))
    lines = ['qbox 声子计算 / qbox phonon calculation', '',
             '运行顺序 / Run order',
             '请按编号顺序执行；每一步成功完成后再进行下一步。',
             'Run the numbered steps in order; continue only after each step completes successfully.', '']
    if scf.source.parent != Path(output_dir).expanduser().resolve():
        lines.extend([f'SCF 工作目录 / SCF working directory: {scf.source.parent}',
                      '其余步骤在本 README 所在目录执行。',
                      'Run the remaining steps in the directory containing this README.', ''])
    for number, (label, command) in enumerate(steps, 1):
        lines.extend([f'{number}. {label}', command, ''])
    return '\n'.join(lines)


def _shermo_readme(scf, system):
    quote = shlex.quote
    prefix = scf.file_prefix
    mode = 0 if system == 'gas' else 1
    return '\n'.join([
        'qbox 分子/吸附体系热力学 / qbox molecular or adsorbate thermochemistry', '',
        f'{prefix}.shm 由 Gamma 振动模式生成，用于 Shermo 后处理。',
        f'{prefix}.shm is generated from Gamma vibrational modes for Shermo postprocessing.',
        f'运行前请在 {prefix}.shm 的 *E 下填写电子能量，单位为 Hartree，不能使用 Ry。',
        f'Before running, enter the electronic energy under *E in {prefix}.shm in Hartree, not Ry.', '',
        '运行顺序 / Run order',
        '1. 运行 Shermo / Run Shermo',
        f'Shermo {quote(prefix + ".shm")} -T 298.15 -P 1 -imode {mode}', '',
    ])


def run_interactive(source=None, *, output_dir='.', input_fn=input, output=print,
                    from_main_menu=False, preset_task=None, result_only=False,
                    transform_source=None):
    from .phonon_inputs import PhononSettings, generate_inputs, resolve_settings
    try:
        scf, explicit_cif = _load_source(source, output_dir, input_fn, output)
        if scf is None:
            if result_only:
                return None
            return RETURN_TO_MAIN if from_main_menu else 0
        if preset_task not in (None, 'dispersion'):
            raise ValueError('执行流程目前只支持声子色散')
        explicit_cif = explicit_cif or find_cif(scf.source)
        if transform_source is not None:
            scf = transform_source(scf)
        while True:
            systems = {key: value for key, value in SYSTEMS.items()
                       if preset_task is None or value[0] in ('nonpolar', 'polar')}
            for key, (_, label) in systems.items():
                output(f'{key}) {label}')
            output('5) 返回')
            selected = _choose(input_fn, output, set(systems) | {'5'}, '选择体系：')
            if selected == '5':
                if result_only:
                    return None
                return RETURN_TO_MAIN if from_main_menu else 0
            system, _ = SYSTEMS[selected]
            while True:
                molecular = system in ('gas', 'adsorbate')
                choices = {'1': ('frequency', 'Gamma 点振动频率'),
                           '2': ('thermo', '热力学性质（生成 Shermo 输入）')} if molecular else TASKS
                back = '3' if molecular else '5'
                if preset_task is not None:
                    task = preset_task
                else:
                    for key, (_, label) in choices.items():
                        output(f'{key}) {label}')
                    output(f'{back}) 返回')
                    selected = _choose(input_fn, output, set(choices) | {back}, '选择目标：')
                    if selected == back:
                        break
                    task, _ = choices[selected]
                if task == 'thermo':
                    if _thermo(scf, system, output_dir, input_fn, output):
                        return 0
                    continue
                settings = PhononSettings(system=system, task=task)
                if system == 'adsorbate':
                    selected_atoms = ()
                    while not selected_atoms:
                        answer = _ask(input_fn, '参与计算的原子编号，例如 1,3,5-8（b 返回）：')
                        if answer.lower() == 'b':
                            break
                        if not answer:
                            output('请至少选择一个原子。')
                            continue
                        try:
                            selected_atoms = parse_atom_indices(answer, scf.nat)
                        except ValueError as error:
                            output(f'错误：{error} 请重新输入。')
                    if not selected_atoms:
                        continue
                    settings = replace(settings, selected_atoms=selected_atoms)
                settings = resolve_settings(scf, settings)
                path_options = {'cif_file': explicit_cif or find_cif(scf.source),
                                'points_per_segment': 20}
                while True:
                    _summary(scf, settings, path_options, output)
                    choice = _choose(input_fn, output, {'0', '1', '2'}, '选择操作：', '0')
                    if choice == '2':
                        break
                    if choice == '1':
                        settings = edit_advanced(scf, settings, path_options, input_fn, output)
                        continue
                    try:
                        path_data = None
                        if task == 'dispersion':
                            from .phonon_paths import generate_phonon_path
                            path_data = generate_phonon_path(scf.source, path_options['cif_file'],
                                dimension=settings.dimension, periodic_axis=settings.periodic_axis or 3,
                                points_per_segment=path_options['points_per_segment'])
                            for warning in path_data.get('warnings', []):
                                output(f'路径提示：{warning}')
                        files = generate_inputs(scf, settings, path_data=path_data)
                        files[f'{scf.file_prefix}.README.txt'] = _phonon_readme(scf, settings, output_dir)
                        if result_only:
                            return PhononPreparation(scf, settings, files, path_data,
                                                     path_options['cif_file'])
                        paths = _publish(files, output_dir, input_fn, output)
                        if paths is None:
                            continue
                        for path in paths:
                            output(f'已生成：{path}')
                        return 0
                    except (OSError, ValueError, ImportError) as error:
                        output(f'生成失败：{error} 当前设置已保留，可进入高级设置或返回。')
                if preset_task is not None:
                    break
    except (EOFError, OSError, ValueError) as error:
        if result_only:
            raise
        output(f'错误：{error}')
        return 1


def prepare_interactive(source=None, *, output_dir='.', input_fn=input, output=print,
                        task='dispersion', transform_source=None):
    """Return a bundle or None on cancellation; propagate failure/EOF to runner."""
    return run_interactive(source, output_dir=output_dir, input_fn=input_fn, output=output,
                           preset_task=task, result_only=True, transform_source=transform_source)


def main(argv=None):
    parser = argparse.ArgumentParser(description='生成 Quantum ESPRESSO 声子输入文件')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('.'))
    parser.add_argument('--from-main-menu', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    return run_interactive(args.source, output_dir=args.output_dir,
                           from_main_menu=args.from_main_menu)


if __name__ == '__main__':
    raise SystemExit(main())
