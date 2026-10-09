"""Standard-library terminal UI for validated Wannier90 input generation.

The menu edits one configuration in memory. CIF sources first reuse matching QE
inputs, configuring SCF only when needed. Preparation is read-only until publishing.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import re
import sys

from .wannier_cif import generate_scf_from_cif
from .wannier_sources import find_existing_qe
from .wannier_help import FIELD_HELP


# Internal shell navigation status; normal CLI cancellation still returns 0.
RETURN_TO_MAIN = 10

PARAMETER_MENU = (
    '1) 计算项目与生成模式',
    '2) 来源文件与 QE 计算目录',
    '3) 输出文件名前缀',
    '4) 均匀 k 点网格',
    '5) 能带数与局域轨道',
    '6) 能量筛选范围',
    '7) 当前计算项目的专用参数',
    '8) 输出文件与检查结果',
    '0) 立即生成输入文件',
    'b) 返回方向选择',
    'q) 返回主菜单',
)

CHOICE_LABELS = {
    'mode': {'new': '从 QE 开始建立 Wannier 模型',
             'existing': '使用已有 Wannier 模型'},
    'reference': {'absolute': '使用 QE 本征值的能量零点',
                  'fermi': '相对于费米能填写能窗'},
    'wannier_plot_format': {'cube': 'Cube 轨道体数据（.cube）',
                            'xsf': 'XCrySDen 轨道体数据（.xsf）'},
    'wannier_plot_spinor_mode': {'total': '总幅值', 'up': '上自旋分量', 'down': '下自旋分量'},
    'boltz_2d_dir': {'no': '三维周期体系', 'x': '二维体系，非周期方向为 x',
                     'y': '二维体系，非周期方向为 y', 'z': '二维体系，非周期方向为 z'},
    'channel': {'all': '两种自旋的共同设置', 'up': '仅设置上自旋', 'down': '仅设置下自旋'},
    'components': {'u,d': '上、下自旋分量都包含', 'u': '仅上自旋分量', 'd': '仅下自旋分量'},
    'sc_phase_conv': {1: '紧束缚约定（TB，值为 1）', 2: 'Wannier90 约定（值为 2）'},
    'kubo_smr_type': {'gauss': 'Gaussian 高斯展宽', 'cold': 'Cold 冷展宽',
                      'm-v': 'Marzari–Vanderbilt 冷展宽', 'f-d': 'Fermi–Dirac 展宽',
                      'm-p1': '一阶 Methfessel–Paxton 展宽', 'm-p2': '二阶 Methfessel–Paxton 展宽'},
}


def _choice_label(key, value):
    if isinstance(value, bool):
        return '是' if value else '否'
    return CHOICE_LABELS.get(key, {}).get(value, _value(value))


def _edit_choice(mapping, key, label, field, input_fn, output):
    choices = (True, False) if field['type'] == 'bool' else field['choices']
    current = mapping.get(key, field.get('default'))
    if current is None:
        current = field.get('default')
    clearable = field.get('clearable', not field.get('required', False))
    output('\n' + label)
    for index, value in enumerate(choices, 1):
        mark = '（当前选择）' if value == current else ''
        output(f'{index}) {_choice_label(key, value)}{mark}')
    keep = (f'回车保留“{_choice_label(key, current)}”' if current is not None
            else '回车暂不设置')
    clear = ('；- 恢复默认' if field.get('default') is not None else '；- 清空可选值') if clearable else ''
    while True:
        answer = input_fn(f'请输入 1–{len(choices)}（{keep}{clear}；b 取消）：').strip()
        if answer == 'b':
            return False
        if not answer:
            if current is None and field.get('required'):
                output('这是必填项，请选择一个编号；也可以输入 b 返回后再设置。')
                continue
            if current is not None:
                mapping[key] = copy.deepcopy(current)
            return True
        if answer == '-' and clearable:
            mapping.pop(key, None)
            return True
        # Keep native tokens valid for existing terminal scripts; JSON is untouched.
        if field['type'] == 'bool' and answer.lower() in ('yes', 'no', 'y', 'n', 'true', 'false', '1', '0'):
            selected = parse_field(answer, field)
        elif field['type'] == 'choice' and answer in choices:
            selected = answer
        elif answer.isdigit() and 1 <= int(answer) <= len(choices):
            selected = choices[int(answer) - 1]
        else:
            output(f'请输入 1–{len(choices)} 选择一项，或按回车保留当前选择。')
            continue
        mapping[key] = selected
        return True


def parse_field(text, field):
    """Parse ordinary terminal values using the same profile field metadata."""
    kind = field.get('type', 'str')
    text = text.strip()
    if kind == 'bool':
        if text.lower() not in ('yes', 'no', 'y', 'n', 'true', 'false', '1', '0'):
            raise ValueError('请输入 yes/no')
        return text.lower() in ('yes', 'y', 'true', '1')
    if kind == 'int':
        if not re.fullmatch(r'[+-]?\d+', text):
            raise ValueError('请输入整数')
        value = int(text)
    elif kind == 'float':
        try:
            value = float(text.replace('D', 'e').replace('d', 'e'))
        except ValueError:
            raise ValueError('请输入一个数值，例如 0.5；单位不需要写入') from None
        if not math.isfinite(value):
            raise ValueError('数值必须有限')
    elif kind in ('mesh', 'mesh2', 'vector', 'int_list'):
        parts = re.split(r'[\s,]+', text)
        scalar = 'float' if kind == 'vector' else 'int'
        value = [parse_field(part, {'type': scalar}) for part in parts]
        length = 2 if kind == 'mesh2' else 3
        if kind != 'int_list' and len(value) != length:
            raise ValueError(f'请输入 {length} 个数值')
        if kind.startswith('mesh') and any(n <= 0 for n in value):
            raise ValueError('网格维度必须为正整数')
        if kind == 'int_list':
            if any(n <= 0 for n in value):
                raise ValueError('编号从 1 开始，请填写正整数')
            if len(value) != len(set(value)):
                raise ValueError('编号不能重复')
    elif kind == 'choice':
        if text not in field['choices']:
            raise ValueError('可选值：' + ', '.join(map(str, field['choices'])))
        value = text
    else:
        value = text
    if isinstance(value, (int, float)):
        if field.get('positive') and value <= 0:
            raise ValueError('数值必须大于零')
        if 'min' in field and value < field['min']:
            raise ValueError(f"数值不能小于 {field['min']}")
        if 'max' in field and value > field['max']:
            raise ValueError(f"数值不能大于 {field['max']}")
    return value


def _value(value):
    if value is None or value == '' or value == []:
        return '未设置'
    if isinstance(value, (list, tuple)):
        return ' '.join(map(str, value))
    return str(value)


def _empty(value):
    return value is None or value == '' or value == [] or value == ()


_EMPTY_BEHAVIOURS = {
    'source_output': '自动识别 SCF/NSCF 输出',
    'band_kpt': '按高对称路径生成采样点',
    'exclude_bands': '不排除能带',
    'select_projections': '使用全部投影',
    'num_iter': '使用 Wannier90 程序默认值',
    'dis_num_iter': '使用 Wannier90 程序默认值',
}


def _setting(mapping, key, field=None):
    """Describe the effective value without treating optional blanks as missing."""
    field = field or {}
    if key == 'source_output' and mapping.get('source_output_mode') == 'off':
        return '不读取 SCF/NSCF 输出 [已禁用，可输入 a 重新识别]'
    value = mapping.get(key, field.get('default'))
    if _empty(value):
        if field.get('required'):
            return '待填写（无默认值）'
        return _EMPTY_BEHAVIOURS.get(key, field.get('empty_label', '程序默认')) + ' [默认]'
    reason = mapping.get('basis_defaults', {}).get(key)
    if reason:
        origin = '已读取' if reason.startswith(('从 SCF', '已读取 NSCF')) else '首轮默认值'
    elif key in mapping.get('basis_manual_fields', []):
        origin = '用户设置'
    elif field.get('default') is not None and value == field['default']:
        origin = '默认值'
    elif mapping.get('mode') == 'existing' and key in ('seed', 'grid', 'nbnd', 'num_wann', 'projections'):
        origin = '已有模型'
    else:
        origin = field.get('display_origin', '当前值')
    shown = _parameter_value(key, value, field) if field.get('type') else _value(value)
    unit = f" {field['unit']}" if field.get('unit') else ''
    return f'{shown}{unit} [{origin}]'


def _effective_basis(config, target):
    values = {**config, **target, 'basis_defaults': dict(config.get('basis_defaults', {}))}
    if target is not config:
        for key in target:
            values['basis_defaults'].pop(key, None)
    return values


def _window_setting(windows, prefix, defaults=None):
    limits = (windows.get(prefix + '_min'), windows.get(prefix + '_max'))
    if limits == (None, None):
        return ('使用全部可用能带 [默认范围]' if prefix == 'dis_win' else '不启用 [默认]')
    if None in limits:
        return f'{_value(limits[0])} 至 {_value(limits[1])} eV [待补全上下限]'
    origin = '初值' if defaults and all(windows.get(prefix + suffix) == defaults.get(prefix + suffix)
                                      for suffix in ('_min', '_max')) else '当前值'
    return f'{_value(limits[0])} 至 {_value(limits[1])} eV [{origin}]'


def _mark_basis_edit(mapping, key):
    if 'source' not in mapping and 'basis_defaults' not in mapping:
        return
    if key not in ('nbnd', 'num_wann', 'projections', 'exclude_bands', 'select_projections',
                   'num_iter', 'dis_num_iter', 'conv_tol', 'conv_window',
                   'dis_mix_ratio', 'dis_conv_tol', 'dis_conv_window'):
        return
    mapping.get('basis_defaults', {}).pop(key, None)
    edits = mapping.setdefault('basis_manual_fields', [])
    if key not in edits:
        edits.append(key)


def _edit(mapping, key, label, field, input_fn, output, origin='用户输入'):
    if field.get('type') in ('choice', 'bool'):
        return _edit_choice(mapping, key, label, field, input_fn, output)
    output('\n' + label + '：' + _setting(mapping, key, field))
    formats = {'mesh': 'NX NY NZ', 'mesh2': 'NX NY', 'vector': 'x y z',
               'int_list': '编号以空格分隔'}
    if field.get('type') in formats:
        output('格式：' + formats[field['type']])
    current = mapping.get(key, field.get('default'))
    suffix = f" {field['unit']}" if field.get('unit') else ''
    required = field.get('required', False)
    clearable = field.get('clearable', not required)
    keep = ('回车保留' if not _empty(current) else
            '必填' if required else '回车默认')
    clear = ('；- 恢复默认' if field.get('default') is not None and 'clear_value' not in field else '；- 清空') if clearable else ''
    while True:
        unit = f'{suffix.strip()}；' if suffix else ''
        answer = input_fn(f'输入（{unit}{keep}{clear}；b 返回）：').strip()
        if answer == 'b':
            return False
        if answer == '-' and clearable:
            if 'clear_value' in field:
                mapping[key] = copy.deepcopy(field['clear_value'])
            else:
                mapping.pop(key, None)
            _mark_basis_edit(mapping, key)
            return True
        if not answer:
            if _empty(current) and required:
                output('这是必填项，请输入具体值；也可以输入 b 返回后再设置。')
                continue
            if current is not None:
                mapping[key] = copy.deepcopy(current)
            return True
        try:
            if answer == '-':
                raise ValueError('这是必填项，不能清空；输入 b 可返回')
            value = parse_field(answer, field)
            if key == 'seed' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
                raise ValueError('文件名前缀须以英文字母或数字开头，只能含字母、数字、_、-、.，不含路径')
        except ValueError as error:
            output('输入无效：' + str(error) + '。请重新输入。')
            continue
        mapping[key] = value
        _mark_basis_edit(mapping, key)
        return True


def _basis_edit_allowed(config, output):
    if config.get('mode') != 'existing':
        return True
    output('已有模型参数只读；菜单 1 可切换为新建。')
    return False


def _projects(config, direction, input_fn, output):
    from .wannier_profiles import TASKS
    choices = direction['tasks']
    output('计算项目（可多选）：')
    for index, task in enumerate(choices, 1):
        mark = '*' if task in config.get('tasks', []) else ' '
        output(f'{index}) {mark} {TASKS[task]["label"]}')
    while True:
        answer = input_fn('输入项目编号，以空格分隔（回车保留；b 返回）：').strip()
        if answer == 'b':
            return
        if not answer:
            break
        try:
            numbers = parse_field(answer, {'type': 'int_list'})
            if any(n < 1 or n > len(choices) for n in numbers):
                raise ValueError('项目编号不在当前方向内')
        except ValueError as error:
            output('输入无效：' + str(error))
            continue
        config['tasks'] = list(dict.fromkeys(choices[n - 1] for n in numbers))
        break
    old = config.get('mode', 'new')
    _edit(config, 'mode', '请选择这次从哪里开始',
          {'type': 'choice', 'choices': ('new', 'existing'), 'default': 'new', 'clearable': False}, input_fn, output)
    if config.get('mode') != old:
        source_kind = 'CIF 或 SCF/NSCF 输入' if config['mode'] == 'new' else '.win 文件'
        output('菜单 2：选择' + source_kind + '。')
        config['nbnd_confirmed'] = False
    _refresh_output_for_tasks(config)


def _refresh_output_for_tasks(config):
    """Reassess an automatic occupation reference for the selected tasks."""
    from .wannier_output_defaults import apply_output
    record = config.get('qe_output')
    if not record or config.get('source_output_mode') == 'off':
        return
    context = config.get('_output_scan_key')
    apply_output(config, record, mode=config.get('source_output_mode', 'auto'))
    if context is not None:
        config['_output_scan_key'] = context


def _complete_structure(config, input_fn, output):
    """Reuse a matching SCF/NSCF; configure SCF only if neither exists."""
    from .wannier_workflow import initial_config
    if config.get('source') or not config.get('structure_source') or config.get('mode') != 'new':
        return True
    candidates = find_existing_qe(config['structure_source'], directory=Path.cwd())
    source = candidates[0] if len(candidates) == 1 else None
    if len(candidates) > 1:
        output('找到多份与 CIF 结构一致的 QE 输入，请选择已有文件：')
        for index, candidate in enumerate(candidates, 1):
            output(f'{index}) {candidate.name}')
        while True:
            choice = input_fn('文件编号（b 返回）：').strip()
            if choice in ('b', 'q', ''):
                return False
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                source = candidates[int(choice) - 1]
                break
            output('请输入列出的文件编号，或 b 返回。')
    if source is None:
        if not candidates:
            output('未找到对应的 SCF/NSCF 输入，请设置 QE 参数。')
        source = generate_scf_from_cif(config['structure_source'], output_dir=Path.cwd(),
                                       input_fn=input_fn, output=output)
    if source is None:
        output('已取消从 CIF 生成 SCF 输入。')
        return False
    imported = initial_config(source)
    imported.update(structure_source=config['structure_source'], seed=config['seed'],
                    tasks=config.get('tasks', []),
                    parameters={**imported.get('parameters', {}), **config.get('parameters', {})})
    config.clear()
    config.update(imported)
    from .wannier_inputs import parse_qe
    kind = str(parse_qe(Path(source).read_text(encoding='utf-8')).get('control', 'calculation', 'scf')).upper()
    output(f'已读取 {kind} 输入：' + str(source))
    return True


def _show_qe_progress(config, output):
    """Show source-stage progress once, separately from the parameter menu."""
    progress = config.get('qe_progress')
    if not progress or config.get('mode', 'new') != 'new':
        return
    signature = json.dumps(progress, sort_keys=True)
    if config.get('_qe_progress_notice') == signature:
        return
    config['_qe_progress_notice'] = signature
    stages = []
    for kind in ('scf', 'nscf'):
        stage = progress.get(kind) or {}
        source = stage.get('input')
        if source:
            origin = '复用输入 ' + Path(source).name
        elif stage.get('output'):
            origin = '输出 ' + Path(stage['output']).name + '，输入未找到'
        else:
            stages.append(f'{kind.upper()} 输入未找到')
            continue
        completed = '已完成' if stage.get('completed') else '未确认完成'
        data = '保存数据存在' if stage.get('data_present') else '缺少保存数据'
        stages.append(f'{kind.upper()} {origin}（{completed}；{data}）')
    output('已有 QE 计算：' + '；'.join(stages) + '。')


def _refresh_qe_progress(config):
    """Recheck a changed run directory while retaining deliberate dimensions."""
    if not config.get('source') or not Path(config['source']).expanduser().is_file():
        return
    from .wannier_qe_reuse import inspect_qe, adopt_nscf
    old = (config.pop('qe_progress', {}) or {}).get('nscf') or {}
    retained = {key: copy.deepcopy(config.get(key)) for key in ('grid', 'nbnd')
                if config.get(key) != old.get(key)}
    if old.get('input') and config.get('source_nscf') == old['input']:
        config.pop('source_nscf', None)
    progress = inspect_qe(config)
    adopt_nscf(config, progress)
    if not (progress.get('nscf') or {}).get('reusable'):
        return
    for key, value in retained.items():
        config[key] = value
        config.get('basis_defaults', {}).pop(key, None)


def _output_context(config):
    """Directory and source identity for this interactive discovery attempt."""
    return [config.get('mode', 'new'), str(Path.cwd()),
            *(str(Path(config[key]).expanduser().resolve()) if config.get(key) else ''
              for key in ('source', 'reference_source', 'run_root'))]


def _output_label(record, config=None):
    from .wannier_output_defaults import midgap_allowed
    energy = record.get('fermi_energy')
    fermi = f'费米能 {_value(energy)} eV' if energy is not None else '未报告共同费米能'
    if energy is None and record.get('gap_reference') and config is not None and midgap_allowed(config):
        fermi = f'占据参考能 {_value(record["gap_reference"]["value_eV"])} eV（带隙中点估计）'
    return f'{record["path"]}（{str(record.get("kind", "QE")).upper()}；{fermi}）'


def _scan_outputs(config, input_fn, output, *, force=False):
    """Select only verified matching outputs, once per source/run directory."""
    from .wannier_output_defaults import apply_output, candidates, clear_output, preferred_records
    if not config.get('source'):
        return
    if force:
        clear_output(config)
    elif (config.get('source_output_mode') == 'off' or
          (config.get('source_output') and config.get('source_output_mode') != 'auto')):
        return
    context = _output_context(config)
    if not force and config.get('_output_scan_key') == context:
        return
    try:
        records = preferred_records(config, candidates(config))
    except (ValueError, OSError) as error:
        config['_output_scan_key'] = context
        output('暂时无法自动识别 SCF/NSCF 输出：' + str(error))
        return
    config['_output_scan_key'] = context
    if not records:
        if force:
            output('未找到与当前来源匹配且已完成的 SCF/NSCF 输出；可稍后提供输出或手动设置参数。')
        return
    if len(records) == 1:
        record = records[0]
        mode = 'auto'
    else:
        output('找到多份匹配且已完成的 QE 输出，请选择本次使用的文件：')
        for index, candidate in enumerate(records, 1):
            output(f'{index}) {_output_label(candidate, config)}')
        while True:
            choice = input_fn('输出文件编号（回车或 0 暂不读取；b 返回）：').strip()
            if choice in ('', '0', 'b'):
                return
            if choice.isdigit() and 1 <= int(choice) <= len(records):
                record = records[int(choice) - 1]
                mode = 'manual'
                break
            output('请输入列出的编号；回车或 0 可暂不读取。')
    apply_output(config, record, mode=mode)
    # apply_output clears old provenance, including the previous scan marker.
    config['_output_scan_key'] = context
    output('已识别输出：' + _output_label(record, config))


def _edit_output_source(config, input_fn, output):
    """Save a manual path for prepare, or request discovery after path edits."""
    from .wannier_output_defaults import clear_output
    output('\nSCF/NSCF 输出：' + _setting(config, 'source_output'))
    answer = input_fn('输出路径（回车保留或自动识别；a 重新识别；- 不读取；b 返回）：').strip()
    if answer == 'b':
        return None
    if answer == 'a':
        return 'scan'
    if answer == '-':
        clear_output(config, disable=True)
        return 'off'
    if not answer:
        return 'off' if config.get('source_output_mode') == 'off' else 'keep'
    clear_output(config)
    config['source_output'] = answer
    config['source_output_mode'] = 'manual'
    return 'manual'


def _sources(config, input_fn, output):
    from .wannier_workflow import initial_config
    from .wannier_output_defaults import clear_output
    old_context = _output_context(config)
    output_disabled = config.get('source_output_mode') == 'off'
    if config.get('mode', 'new') == 'new':
        output('来源：CIF 结构或 QE SCF/NSCF 输入文件。')
    else:
        output('来源：已有 .win 文件。')
    answer = input_fn(f'来源文件路径 [当前：{_value(config.get("source") or config.get("structure_source"))}]（回车保留；b 返回）：').strip()
    if answer == 'b':
        return
    same_source = bool(answer and any(
        config.get(key) and Path(answer).expanduser().resolve() == Path(config[key]).expanduser().resolve()
        for key in ('source', 'structure_source')))
    if answer and not same_source:
        imported = initial_config(answer)
        if not _complete_structure(imported, input_fn, output):
            return
        # A different source invalidates its previous basis; task requests remain.
        tasks = config.get('tasks', [])
        config.clear()
        config.update(imported)
        config['tasks'] = tasks
        if output_disabled:
            clear_output(config, disable=True)
        output('已读取文件，当前方式：' + _choice_label('mode', config['mode']))
    elif not _complete_structure(config, input_fn, output):
        return
    output_action = _edit_output_source(config, input_fn, output)
    if output_action is None:
        return
    old_root = config.get('run_root') or str(Path.cwd())
    if not _edit(config, 'run_root', 'QE 计算目录', {'type': 'str', 'required': True, 'default': str(Path.cwd())}, input_fn, output):
        return
    root_changed = Path(old_root).expanduser().resolve() != Path(config['run_root']).expanduser().resolve()
    if root_changed and output_action not in ('manual', 'off'):
        # Do this before later cancellable prompts or basis validation so the
        # new directory never keeps values from the previous output context.
        clear_output(config)
    if root_changed and config.get('mode', 'new') == 'new':
        from .wannier_workflow import initialize_basis_defaults
        # Relative UPF paths may now resolve to different files. Recompute only
        # automatic values; deliberate user choices (including clearing) survive.
        origins = config.get('basis_defaults', {})
        source_nbnd = config.get('nbnd') if origins.get('nbnd', '').startswith(('从 SCF', '已读取 NSCF')) else None
        for key in ('nbnd', 'num_wann', 'projections'):
            if key in origins and not origins[key].startswith(('从 SCF', '已读取 NSCF')):
                config.pop(key, None)
                origins.pop(key)
        initialize_basis_defaults(config, source_nbnd)
        _refresh_qe_progress(config)
    if config.get('mode') == 'existing':
        if not _edit(config, 'reference_source', '原模型对应的 SCF/NSCF 输入',
                     {'type': 'str', 'required': 'qe_bands' in config.get('tasks', []),
                      'empty_label': '未提供原 QE 输入；暂不自动识别 QE 输出'}, input_fn, output):
            return
    if 'qe_bands' in config.get('tasks', []):
        _edit(config, 'band_kpt', '实际能带采样点文件',
              {'type': 'str', 'empty_label': '默认按所选高对称路径生成 QE 采样点'}, input_fn, output)
    if output_action == 'manual':
        # The path was explicitly chosen during this edit; validate it in prepare.
        config['_output_scan_key'] = _output_context(config)
    elif output_action == 'scan':
        _scan_outputs(config, input_fn, output, force=True)
    elif output_action != 'off':
        if _output_context(config) != old_context:
            clear_output(config)
        _scan_outputs(config, input_fn, output)
    _show_qe_progress(config, output)


def _path_editor(input_fn, output):
    output('1) 自动高对称路径（SeeK-path）  2) 手动输入')
    while True:
        choice = input_fn('路径方式（1 / 2；b 返回）：').strip()
        if choice in ('b', ''):
            return None
        if choice in ('1', 'a'):
            return 'auto'
        if choice == '2':
            break
        output('请输入 1、2 或 b。')
    output('格式：起点标签 kx ky kz 终点标签 kx ky kz（倒格分数坐标）。')
    output('回车保存；b 取消。')
    segments = []
    while True:
        answer = input_fn(f'路径段 {len(segments) + 1}：').strip()
        if answer == 'b':
            return None
        if not answer:
            if segments:
                return segments
            output('还没有路径段；请输入一段路径，或 b 返回。')
            continue
        parts = answer.split()
        if len(parts) != 8:
            output('格式不完整：每段需要两个标签与六个坐标，请重填这一段。')
            continue
        try:
            start = parse_field(' '.join(parts[1:4]), {'type': 'vector'})
            end = parse_field(' '.join(parts[5:8]), {'type': 'vector'})
        except ValueError as error:
            output('坐标无效：' + str(error))
            continue
        segments.append({'start_label': parts[0], 'start': start, 'end_label': parts[4], 'end': end})


def _task_fields(config):
    from .wannier_profiles import fields_for_tasks
    if not config.get('tasks'):
        return {}
    fields = fields_for_tasks(config.get('tasks', []))
    parameters = config.get('parameters', {})
    if config.get('spin_mode') != 'spinor':
        fields.pop('wannier_plot_spinor_mode', None)
        fields.pop('include_spin', None)
    if set(config.get('tasks', [])).isdisjoint({'optical', 'shift_current'}) and not parameters.get('shc_freq_scan'):
        fields = {key: field for key, field in fields.items() if not key.startswith('kubo_freq_')}
    if 'kubo_freq_max' in fields and parameters.get('kubo_freq_min', 0) not in (None, 0):
        fields['kubo_freq_max'] = {**fields['kubo_freq_max'], 'required': True}
    if not parameters.get('kubo_adpt_smr', False):
        fields.pop('kubo_adpt_smr_fac', None)
        fields.pop('kubo_adpt_smr_max', None)
    return fields


def _parameter_value(key, value, field):
    if key == 'conv_window' and value is not None and value <= 1:
        return f'{value}（关闭收敛检查）'
    if field['type'] == 'path' and value:
        return '自动高对称路径' if value == 'auto' else f'已设置 {len(value)} 段路径'
    return _choice_label(key, value) if field['type'] in ('choice', 'bool') else _value(value)


def _task_setting(config, key, field):
    parameters = config.get('parameters', {})
    automatic = (config.get('response_parameter_defaults') or {}).get(key) or {}
    if automatic.get('value') is not None and parameters.get(key) == automatic['value']:
        return _setting(parameters, key, {**field, 'display_origin': '初值'})
    if key == 'fermi_energy':
        from .wannier_output_defaults import can_defer_fermi
        record = config.get('qe_output') or {}
        automatic = config.get('output_parameter_values', {})
        if key in automatic and parameters.get(key) == automatic[key] and record:
            if config.get('fermi_source', {}).get('method') == 'sampled_midgap':
                return f'占据参考能 {_value(parameters[key])} eV [带隙中点估计；来自 {record["path"]}]'
            return f'{_value(parameters[key])} eV [来自 {record["path"]}]'
        if can_defer_fermi(config):
            return '待补全（NSCF 后读取）'
        if key not in parameters and key not in config.get('output_manual_fields', []):
            if record and record.get('fermi_energy') is None:
                return '待填写（输出未报告 EF）'
            if config.get('source_output'):
                return '检查时从 SCF/NSCF 输出读取 [尚未验证]'
    if key in ('kubo_freq_max', 'kubo_eigval_max') and parameters.get(key) is None:
        if 'shift_current' in config.get('tasks', []):
            from .wannier_sc import pending_response_parameters
            state = '待补全' if key in pending_response_parameters(config) else '待填写'
            return f'{state}（postw90 前填写）'
        if key == 'kubo_freq_max' and field.get('required'):
            return '待填写（光子能量下限非零，需明确大于下限的上限）'
        return 'postw90 自动确定 [默认]'
    return _setting(parameters, key, field)


def _parameters(config, input_fn, output):
    from .wannier_window_defaults import initialize_window_defaults
    from .wannier_response_defaults import refresh_response_defaults
    parameters = config.setdefault('parameters', {})
    while True:
        initialize_window_defaults(config)
        refresh_response_defaults(config)
        fields = _task_fields(config)
        keys = list(fields)
        if not keys:
            output('当前项目无需额外专用参数。')
            return
        for index, key in enumerate(keys, 1):
            field = fields[key]
            shown = _task_setting(config, key, field)
            output(f'{index}) {FIELD_HELP[key]["label"]}：{shown} ({key})')
        selection = input_fn('参数编号（0 或 b 返回）：').strip()
        if selection in ('0', 'b', ''):
            return
        if not selection.isdigit() or not 1 <= int(selection) <= len(keys):
            output('请输入当前列表中的编号，或 b 返回。')
            continue
        key = keys[int(selection) - 1]
        if fields[key]['type'] == 'path':
            path = _path_editor(input_fn, output)
            if path is not None:
                parameters[key] = path
        else:
            field = fields[key]
            if key == 'sc_phase_conv':
                field = {**field, 'type': 'choice', 'choices': (1, 2)}
            if key in ('fermi_energy', 'kubo_freq_max', 'kubo_eigval_max'):
                from .wannier_output_defaults import mark_manual
                answers = []
                def read_parameter(prompt):
                    answer = input_fn(prompt)
                    answers.append(answer.strip())
                    return answer
                if _edit(parameters, key, FIELD_HELP[key]['label'], {**field, 'clearable': True},
                         read_parameter, output) and answers and answers[-1]:
                    mark_manual(config, key)
            else:
                _edit(parameters, key, FIELD_HELP[key]['label'], field, input_fn, output)


def _channel_target(config, input_fn, output):
    if config.get('spin_mode') != 'collinear':
        return config
    selection = {}
    if not _edit_choice(selection, 'channel', '选择要修改的自旋通道',
                        {'type': 'choice', 'choices': ('all', 'up', 'down'),
                         'default': 'all', 'clearable': False}, input_fn, output):
        return None
    channel = selection['channel']
    if channel == 'all':
        return config
    return config.setdefault('channels', {}).setdefault(channel, {})


def _basis_value(config, target, key):
    return target.get(key, config.get(key))


def _projection_count(config, target):
    from .wannier_inputs import parse_qe, projection_lines
    projections = _basis_value(config, target, 'projections')
    if not projections or not config.get('source'):
        return None
    parsed = parse_qe(Path(config['source']).read_text(encoding='utf-8'))
    return projection_lines(projections, parsed)[1]


def _convergence(config, input_fn, output):
    from .wannier_sc import MODEL_DEFAULTS, model_settings
    fields = {
        'num_iter': {'type': 'int', 'min': 1},
        'conv_tol': {'type': 'float', 'min': 0, 'unit': 'Å²'},
        'conv_window': {'type': 'int', 'min': -1},
        'dis_num_iter': {'type': 'int', 'min': 1},
        'dis_mix_ratio': {'type': 'float', 'positive': True, 'max': 1},
        'dis_conv_tol': {'type': 'float', 'min': 0},
        'dis_conv_window': {'type': 'int', 'min': 1},
    }
    while True:
        effective = {**config, **model_settings(config)}
        keys = list(fields)
        for index, key in enumerate(keys, 1):
            field = fields[key]
            if key not in config:
                field = {**field, 'display_origin': '模板默认值'}
            output(f'{index}) {FIELD_HELP[key]["label"]}：{_setting(effective, key, field)} ({key})')
        output('0) 返回')
        choice = input_fn('迭代设置编号（0 或 b 返回）：').strip()
        if choice in ('0', 'b', ''):
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(keys):
            output('请输入当前列表中的编号，或 b 返回。')
            continue
        key = keys[int(choice) - 1]
        edited = {key: effective.get(key)}
        if _edit(edited, key, FIELD_HELP[key]['label'],
                 {**fields[key], 'default': MODEL_DEFAULTS[key]}, input_fn, output):
            if key in edited:
                config[key] = edited[key]
            else:
                config.pop(key, None)
            _mark_basis_edit(config, key)


def _bands(config, input_fn, output):
    if config.get('mode') == 'existing':
        output('参与 Wannier 的能带数：' + _setting(config, 'nbnd', {'required': True}))
        output('局域轨道数：' + _setting(config, 'num_wann', {'required': True}))
        output('初始投影：沿用已有模型，无需重新设置。')
        output('原 QE 排除带：' + _setting(config, 'exclude_bands'))
    if not _basis_edit_allowed(config, output):
        return
    target = _channel_target(config, input_fn, output)
    if target is None:
        return
    while True:
        try:
            count = _projection_count(config, target)
        except (ValueError, OSError) as error:
            count = None
            output('暂时无法检查投影计数：' + str(error))
        effective = _effective_basis(config, target)
        output('\n1) QE 能带总数 nbnd：' + _setting(config, 'nbnd', {'required': True}))
        output('2) 初始轨道投影：' + _setting(effective, 'projections', {'required': True}))
        output('3) 最终局域轨道数 num_wann：' + _setting(effective, 'num_wann', {'required': True}))
        output('4) 排除部分 QE 能带：' + _setting(effective, 'exclude_bands'))
        output('5) 只保留部分投影：' + _setting(effective, 'select_projections'))
        if 'shift_current' in config.get('tasks', []):
            output('6) 迭代与收敛')
        else:
            output('6) 最大迭代次数：局域化 ' + _setting(config, 'num_iter') + '；解纠缠 ' + _setting(config, 'dis_num_iter'))
        output('0) 返回')
        if count is not None:
            output(f'投影展开数：{count}')
        selection = input_fn('设置编号（0 或 b 返回）：').strip()
        if selection in ('0', 'b', ''):
            return
        if selection == '1':
            if _edit(config, 'nbnd', 'QE 能带数 nbnd',
                     {'type': 'int', 'min': 1, 'required': True}, input_fn, output):
                config['nbnd_confirmed'] = True
        elif selection == '2':
            edit_projections(config, target, input_fn, output)
        elif selection == '3':
            _edit(target, 'num_wann', '最终局域轨道数 num_wann',
                  {'type': 'int', 'min': 1, 'required': True,
                   'default': _basis_value(config, target, 'num_wann')}, input_fn, output)
        elif selection in ('4', '5'):
            key = 'exclude_bands' if selection == '4' else 'select_projections'
            _edit(target, key, FIELD_HELP[key]['label'],
                  {'type': 'int_list', 'default': _basis_value(config, target, key),
                   'clear_value': []}, input_fn, output)
        elif selection == '6':
            if 'shift_current' in config.get('tasks', []):
                _convergence(config, input_fn, output)
                continue
            for key in ('num_iter', 'dis_num_iter'):
                if not _edit(config, key, FIELD_HELP[key]['label'],
                             {'type': 'int', 'min': 1}, input_fn, output):
                    break
        else:
            output('请输入 1–6，或 b 返回。')


def edit_projections(config, target, input_fn, output):
    """Select species/atoms and orbital sets, then validate the full expansion."""
    from .wannier_inputs import parse_qe, projection_lines
    if not config.get('source'):
        raise ValueError('请先进入菜单 2 选择 SCF 来源输入')
    parsed = parse_qe(Path(config['source']).read_text(encoding='utf-8'))
    projections = list(target.get('projections', config.get('projections', [])))
    original = list(projections)
    while True:
        output('当前投影：' + _value(projections))
        if projections:
            _, count = projection_lines(projections, parsed)
            output(f'投影实际展开数：{count}')
        output('1) 为某种原子的全部原子添加  2) 为单个原子添加')
        output('3) 手动输入投影表达式（高级）  4) 清空  0) 保存并返回  b) 放弃本次编辑')
        choice = input_fn('投影设置编号：').strip()
        if choice == 'b':
            return
        if choice in ('0', ''):
            target['projections'] = projections
            if projections != original and target is config:
                _mark_basis_edit(config, 'projections')
            return
        if choice == '4':
            projections = []
            continue
        if choice in ('1', '2'):
            if choice == '1':
                for index, label in enumerate(parsed.species, 1):
                    atoms = sum(atom[0] == label for atom in parsed.atoms)
                    output(f'{index}) {label}（共 {atoms} 个原子）')
                limit = len(parsed.species)
            else:
                output('原子坐标（晶胞分数坐标）：')
                for index, (label, coords) in enumerate(parsed.atoms, 1):
                    output(f'{index}) {label}  {_value(coords)}')
                limit = len(parsed.atoms)
            selected = {}
            if not _edit(selected, 'index', '原子类型编号' if choice == '1' else '原子编号',
                         {'type': 'int', 'min': 1, 'max': limit, 'required': True}, input_fn, output):
                continue
            index = selected['index']
            location = parsed.species[index - 1] if choice == '1' else f'atom:{index}'
            output('轨道：s、p、d、f、sp、sp2、sp3、sp3d、sp3d2；多组以分号分隔。')
            orbitals = input_fn('轨道组合（b 返回）：').strip()
            if orbitals == 'b':
                continue
            line = f'{location}:{orbitals}'
            if parsed.spin_mode == 'spinor':
                components = {}
                if not _edit_choice(components, 'components', '投影包含哪些自旋分量',
                                    {'type': 'choice', 'choices': ('u,d', 'u', 'd'),
                                     'default': 'u,d', 'clearable': False}, input_fn, output):
                    continue
                line += '(' + components['components'] + ')'
        elif choice == '3':
            output('格式：Si:s;p、atom:1:d 或 f=0,0,0:s。')
            line = input_fn('投影表达式（b 返回）：').strip()
            if line == 'b':
                continue
        else:
            output('请输入 1–4、0 或 b。')
            continue
        candidate = projections + [line]
        try:
            projection_lines(candidate, parsed)
        except ValueError as error:
            output('投影未添加：' + str(error) + '；请重新选择原子和轨道。')
            continue
        projections = candidate


def _window_pair(windows, frozen, input_fn, output):
    """Publish both limits together; cancellation never leaves a half-window."""
    prefix = 'dis_froz' if frozen else 'dis_win'
    label = '冻结窗' if frozen else '外窗'
    draft = copy.deepcopy(windows)
    for bound, word in (('min', '下限'), ('max', '上限')):
        if not _edit(draft, prefix + '_' + bound, label + word,
                     {'type': 'float', 'unit': 'eV', 'required': True}, input_fn, output):
            return
    if draft[prefix + '_min'] > draft[prefix + '_max']:
        output('未保存：下限必须不大于上限；请重新选择此项填写。')
        return
    if 'dis_froz_min' in draft:
        if 'dis_win_min' not in draft or not (draft['dis_win_min'] <= draft['dis_froz_min'] <=
                                            draft['dis_froz_max'] <= draft['dis_win_max']):
            output('未保存：冻结窗必须完全位于外窗内；请先设置外窗或调整范围。')
            return
    windows.clear()
    windows.update(draft)


def _window_reference(windows, input_fn, output):
    draft = copy.deepcopy(windows)
    fermi_answers = []
    def read_fermi(prompt):
        answer = input_fn(prompt)
        fermi_answers.append(answer.strip())
        return answer
    old_reference = draft.get('reference', 'absolute')
    old_fermi = draft.get('fermi_energy')
    if not _edit(draft, 'reference', '能窗数值以哪个能量为零',
                 {'type': 'choice', 'choices': ('absolute', 'fermi'),
                  'default': 'absolute', 'clearable': False}, input_fn, output):
        return
    if draft['reference'] == 'fermi':
        if not _edit(draft, 'fermi_energy', '参考能 EF',
                     {'type': 'float', 'unit': 'eV', 'required': True,
                      'help_key': 'windows_fermi_energy'}, read_fermi, output):
            return
    # Changing the coordinate origin must retain the same physical windows.
    old_offset = old_fermi if old_reference == 'fermi' else 0.
    new_offset = draft['fermi_energy'] if draft['reference'] == 'fermi' else 0.
    bounds = [key for key in draft if key.startswith(('dis_win_', 'dis_froz_'))]
    if bounds and old_offset is None:
        output('未保存：原能窗缺少费米能，无法换算已有范围；请先清空能窗后重新设置。')
        return
    for key in bounds:
        draft[key] = draft[key] + old_offset - new_offset
    if bounds and old_offset != new_offset:
        output('已换算已有能窗的数值，保留相同的实际能量范围。')
    windows.clear()
    windows.update(draft)
    return bool(fermi_answers and fermi_answers[-1])


def _window_energy_reference(config, output):
    """Display the already verified QE record without inferring a Fermi level."""
    record = config.get('qe_output') if config.get('source_output_mode') != 'off' else None
    if record:
        output('能量参考：' + Path(record['path']).name +
               f'（{str(record.get("kind", "QE")).upper()}；QE 零点，eV）')
        fermi = record.get('fermi_energy')
        energies = ['EF=' + (_value(fermi) if fermi is not None else '未报告')]
        for key, label in (('homo', 'HOMO'), ('lumo', 'LUMO')):
            if record.get(key) is not None:
                energies.append(label + '=' + _value(record[key]))
        output('；'.join(energies))
        sampled = []
        if record.get('eigenvalue_min') is not None and record.get('eigenvalue_max') is not None:
            sampled.append(f'打印本征值：{record["eigenvalue_min"]} 至 {record["eigenvalue_max"]}')
        gap = record.get('gap_reference') or {}
        if gap.get('value_eV') is not None:
            sampled.append('带隙中点估计：' + _value(gap['value_eV']))
        if sampled:
            output('；'.join(sampled))
    else:
        output('能量参考：未读取（菜单 2）。')


def _window_zero(windows):
    if windows.get('reference', 'absolute') == 'fermi':
        return 'E − EF；能窗 EF=' + _value(windows.get('fermi_energy')) + ' eV（QE 零点）'
    return 'QE 本征值（eV）'


def _windows(config, input_fn, output):
    from .wannier_window_defaults import initialize_window_defaults, mark_windows_manual
    from .wannier_response_defaults import refresh_response_defaults
    initialize_window_defaults(config)
    refresh_response_defaults(config)
    _window_energy_reference(config, output)
    note = (config.get('window_defaults') or {}).get('adjustment_note')
    if note:
        output(note)
    if config.get('mode') == 'existing':
        windows = config.get('windows', {})
        output('外窗：' + _window_setting(windows, 'dis_win'))
        output('冻结窗：' + _window_setting(windows, 'dis_froz'))
        output('能量零点：' + _window_zero(windows))
    if not _basis_edit_allowed(config, output):
        return
    target = _channel_target(config, input_fn, output)
    if target is None:
        return
    windows = copy.deepcopy(_basis_value(config, target, 'windows') or {})
    original = copy.deepcopy(windows)
    while True:
        output('\n能量零点：' + _window_zero(windows))
        for prefix, label in (('dis_win', '外窗'), ('dis_froz', '冻结窗')):
            defaults = (config.get('window_defaults') or {}).get('values')
            output(label + '：' + _window_setting(windows, prefix, defaults))
        output('1) 清空能窗（默认全部能带）')
        output('2) 外窗')
        output('3) 冻结窗')
        output('4) 能量零点 / EF')
        output('5) 清空冻结窗')
        output('0) 返回')
        choice = input_fn('能窗设置编号（0 或 b 返回）：').strip()
        if choice in ('0', 'b', ''):
            if windows != original:
                target['windows'] = windows
            return
        previous = copy.deepcopy(windows)
        if choice == '1':
            windows.clear()
        elif choice in ('2', '3'):
            if choice == '3' and 'dis_win_min' not in windows:
                output('请先通过 2 设置外窗，再设置其中的冻结窗。')
                continue
            _window_pair(windows, choice == '3', input_fn, output)
        elif choice == '4':
            if _window_reference(windows, input_fn, output) and target is config:
                from .wannier_output_defaults import mark_manual
                mark_manual(config, 'windows.fermi_energy')
        elif choice == '5':
            windows.pop('dis_froz_min', None)
            windows.pop('dis_froz_max', None)
        else:
            output('请输入 1–5，或 b 返回。')
        if windows != previous or choice in ('1', '5'):
            target['windows'] = copy.deepcopy(windows)
            mark_windows_manual(config)
            refresh_response_defaults(config)


def _missing_settings(config):
    from .wannier_output_defaults import can_defer_fermi
    from .wannier_window_defaults import initialize_window_defaults
    from .wannier_response_defaults import refresh_response_defaults
    from .wannier_sc import pending_response_parameters
    initialize_window_defaults(config)
    refresh_response_defaults(config)
    deferred = pending_response_parameters(config)
    missing = []
    if not config.get('source'):
        missing.append('菜单 2：选择来源文件')
    if config.get('mode', 'new') == 'new':
        if not config.get('grid'):
            missing.append('菜单 4：填写均匀 k 点网格')
        if not config.get('nbnd') or not config.get('nbnd_confirmed'):
            missing.append('菜单 5 → 1：填写或确认 QE 能带数')
        channels = config.get('channels', {}) if config.get('spin_mode') == 'collinear' else {}
        targets = [(name, channels.get(name, {})) for name in ('up', 'down')] if channels else [('', config)]
        for name, target in targets:
            prefix = {'up': '上自旋：', 'down': '下自旋：'}.get(name, '')
            if not _basis_value(config, target, 'projections'):
                missing.append('菜单 5 → 2：' + prefix + '选择初始轨道投影')
            if not _basis_value(config, target, 'num_wann'):
                missing.append('菜单 5 → 3：' + prefix + '填写最终局域轨道数')
    for key, field in _task_fields(config).items():
        value = config.get('parameters', {}).get(key, field.get('default'))
        if field.get('required') and (value is None or value == [] or value == ''):
            if key in deferred:
                continue
            if key == 'fermi_energy' and can_defer_fermi(config):
                continue
            if (key == 'fermi_energy' and config.get('source_output') and
                    key not in config.get('output_manual_fields', []) and
                    (not config.get('qe_output') or config['qe_output'].get('fermi_energy') is not None)):
                continue
            missing.append('菜单 7：' + FIELD_HELP[key]['label'])
    return missing


def _seed_editor(config, input_fn, output):
    seed = config.get('seed') or 'sample'
    output(f'当前名称对应的文件：{seed}.win、{seed}.nscf.in、{seed}.pw2wan 等。')
    output('填写公共前缀，不含目录或扩展名。')
    if config.get('mode') == 'existing':
        output('已有模型保留原文件名前缀：' + _value(config.get('seed')))
        return
    if _edit(config, 'seed', '输出文件名前缀', {'type': 'str', 'required': True}, input_fn, output):
        seed = config['seed']
        output(f'将使用：{seed}.win、{seed}.nscf.in、{seed}.pw2wan 等。')


def _explain_error(error):
    """Translate actionable model errors without hiding the original diagnosis."""
    message = str(error)
    common = {
        'automatic paths require optional seekpath; enter kpoint_path manually':
            '当前运行环境缺少自动路径所需的 SeeK-path；请进入菜单 7 的路径设置，选择 2 手动输入，或改用已配有 SeeK-path 的 Python 环境。',
        'num_wann must not exceed nbnd minus excluded bands':
            '局域轨道数不能超过排除能带后的可用带数；请到菜单 5 检查能带数、轨道数和排除带。',
        'select_projections must select exactly num_wann projections':
            '保留的投影编号个数必须等于局域轨道数；请到菜单 5 的第 3、5 项调整。',
        'spin matrices require a spinor SCF source; changing NSCF spin flags cannot provide it':
            '此项目需要非共线旋量（spinor）SCF 来源及对应的自旋矩阵；请在菜单 2 选择适合的来源，或在菜单 1 更换项目。',
    }
    if message in common:
        return common[message]
    match = re.fullmatch(r'expanded projection count (\d+) must equal num_wann (\d+); supply explicit select_projections', message)
    if match:
        return (f'当前投影展开为 {match[1]} 个轨道，设置的局域轨道数为 {match[2]}；'
                '请到菜单 5 调整投影或轨道数，需要时在第 5 项明确选择要保留的投影。')
    for key, help_info in sorted(FIELD_HELP.items(), key=lambda item: -len(item[0])):
        if re.search(r'\b' + re.escape(key) + r'\b', message):
            return help_info['label'] + '：' + message
    return message


def _preview(config, output):
    from .wannier_workflow import prepare
    from .wannier_publish import snapshot
    files = prepare(config, output_dir=Path.cwd())
    output(f'输出目录：{Path.cwd()}')
    for filename in files:
        path = Path.cwd() / filename
        conflict = ' [同名冲突]' if path.exists() or path.is_symlink() else ''
        output(f'  {filename}{conflict}')
    try:
        expected = snapshot(files, Path.cwd())
    except ValueError:
        if not any((Path.cwd() / name).is_symlink() or ((Path.cwd() / name).exists() and not (Path.cwd() / name).is_file()) for name in files):
            raise
        expected = None
        output('存在符号链接或非普通文件：只能改名或取消。')
    output('检查通过，待保存。')
    return files, expected


def _protected(config):
    keys = ['source_output', 'reference_source', 'band_kpt', 'structure_source', 'source_nscf']
    if config.get('mode') != 'existing':
        keys.append('source')
    paths = [config[key] for key in keys if config.get(key)]
    paths.extend(stage['input'] for stage in (config.get('qe_progress') or {}).values()
                 if isinstance(stage, dict) and stage.get('input'))
    return tuple(dict.fromkeys(Path(path).expanduser().resolve() for path in paths))


def _generate(config, input_fn, output):
    from .wannier_publish import publish, read_dependencies
    missing = _missing_settings(config)
    if missing:
        output('还需完成以下设置：')
        for item in missing:
            output('  · ' + item)
        return False
    while True:
        files, expected = _preview(config, lambda _: None)
        conflicts = [name for name in files if (Path.cwd() / name).exists() or (Path.cwd() / name).is_symlink()]
        policy = 'cancel'
        if conflicts:
            output('已有同名文件：' + '、'.join(conflicts))
            prompt = ('同名文件：1) 备份到 bak/ 后覆盖  2) 改名  3) 取消 [3]：' if expected is not None
                      else '非普通文件冲突：2) 改名  3) 取消 [3]：')
            decision = input_fn(prompt).strip() or '3'
            if decision == '2':
                if config.get('mode') == 'existing':
                    output('已有结果必须保留 seed；请取消并移动输入，或切换到新建模式。')
                    return False
                if not _edit(config, 'seed', '新的输出文件名前缀', {'type': 'str', 'required': True}, input_fn, output):
                    return False
                continue
            if decision != '1' or expected is None:
                output('已取消，未写入文件。')
                return False
            policy = 'backup'
        publish(files, Path.cwd(), conflict=policy, expected=expected, protected=_protected(config),
                dependencies=read_dependencies(files))
        output('输入文件已在当前文件夹生成。')
        if policy == 'backup':
            output('原同名文件已备份到当前目录的 bak/。')
        _pending_notice(files, output)
        return True


def _pending_notice(files, output):
    from .wannier_sc import pending_response_parameters
    for name, text in files.items():
        if not name.endswith('.qbox.json'):
            continue
        config = json.loads(text).get('config', {})
        note = (config.get('window_defaults') or {}).get('adjustment_note')
        if note:
            output(note)
        pending = pending_response_parameters(config)
        if 'fermi_energy' in pending:
            output('尚未取得占据参考能：SCF/NSCF 后补全。')
        if pending:
            output('运行 postw90 前还需补全：' + '、'.join(FIELD_HELP[key]['label'] for key in pending) + '。')
            output('补全：菜单 2 读取输出，或菜单 7 填写参数。')


def run_interactive(config, input_fn=input, output=print, *, return_to_main_status=0, resume=False):
    """Edit shared config; keep any SCF input already generated by the CIF wizard."""
    from .wannier_profiles import DIRECTIONS, TASKS
    direction = None
    try:
        if resume and config.get('tasks'):
            saved_tasks = set(config['tasks'])
            if saved_tasks - TASKS.keys():
                raise ValueError('已保存配置包含无法识别的计算项目')
            direction = next((item for item in DIRECTIONS if saved_tasks <= set(item['tasks'])),
                             {'label': '已保存的 Wannier 计算项目', 'tasks': tuple(config['tasks'])})
            config.pop('_output_scan_key', None)
            config.pop('_qe_progress_notice', None)
            if config.get('mode', 'new') == 'new' and config.get('source'):
                from .wannier_qe_reuse import inspect_qe
                config.pop('qe_progress', None)
                try:
                    config['qe_progress'] = inspect_qe(config)
                    nscf = config['qe_progress']['nscf']
                    if nscf.get('reusable'):
                        config['source_nscf'] = nscf['input']
                except (ValueError, OSError) as error:
                    output(f'检查未通过：{error}')
                    output('可进入菜单 2 重新选择来源文件。')
            _refresh_output_for_tasks(config)
            _scan_outputs(config, input_fn, output)
            _show_qe_progress(config, output)
        while True:
            if direction is None:
                output('Wannier90 输入生成：选择计算方向')
                for index, item in enumerate(DIRECTIONS, 1):
                    output(f'{index}) {item["label"]}')
                choice = input_fn('方向编号（q 返回主菜单）：').strip()
                if choice in ('q', 'b', '0'):
                    return return_to_main_status
                if not choice.isdigit() or not 1 <= int(choice) <= len(DIRECTIONS):
                    output('请输入 1–6 或 q。')
                    continue
                direction = DIRECTIONS[int(choice) - 1]
                config['tasks'] = [direction['tasks'][0]]
                try:
                    if not _complete_structure(config, input_fn, output):
                        direction = None
                        continue
                    _refresh_output_for_tasks(config)
                    _scan_outputs(config, input_fn, output)
                    _show_qe_progress(config, output)
                except (ValueError, OSError) as error:
                    output(f'检查未通过：{error}')
                    output('可进入菜单 2 重新选择来源文件。')
            output('\n' + direction['label'])
            output('当前项目：' + '、'.join(TASKS[task]['label'] for task in config['tasks']))
            for line in PARAMETER_MENU:
                output(line)
            choice = input_fn('参数菜单：').strip()
            if choice == 'q':
                return return_to_main_status
            if choice == 'b':
                direction = None
                continue
            try:
                if choice == '1':
                    _projects(config, direction, input_fn, output)
                elif choice == '2':
                    _sources(config, input_fn, output)
                elif choice == '3':
                    _seed_editor(config, input_fn, output)
                elif choice == '4':
                    if config.get('mode') == 'existing':
                        output('均匀 k 点网格：' + _setting(config, 'grid', {'required': True}))
                    if _basis_edit_allowed(config, output):
                        _edit(config, 'grid', 'k 点网格（NX NY NZ）', {'type': 'mesh', 'required': True}, input_fn, output)
                elif choice == '5':
                    _bands(config, input_fn, output)
                elif choice == '6':
                    _windows(config, input_fn, output)
                elif choice == '7':
                    _parameters(config, input_fn, output)
                elif choice == '8':
                    missing = _missing_settings(config)
                    if missing:
                        output('请先完成以下设置，再查看完整文件清单：\n  · ' + '\n  · '.join(missing))
                    else:
                        _preview(config, output)
                elif choice == '0':
                    if _generate(config, input_fn, output):
                        return 0
                elif choice not in ('4',):
                    output('请输入菜单编号、b 或 q。')
            except (ValueError, OSError, KeyError, TypeError) as error:
                output('检查未通过：' + _explain_error(error))
    except (EOFError, KeyboardInterrupt):
        output('\n已退出。')
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Wannier90 六方向输入生成；默认输出当前目录')
    parser.add_argument('source', nargs='?', help='CIF 结构、SCF/NSCF 输入或已有 .win；CIF 缺少已有输入时交互配置 QE 参数')
    parser.add_argument('--recover', type=Path, help='恢复中断发布的 transaction.json；隐藏暂存目录仅供恢复，不是计算目录')
    parser.add_argument('--config', type=Path, help='JSON 配置或本程序生成的 .qbox.json，进行非交互生成')
    parser.add_argument('--interactive', action='store_true', help='载入 --config 后进入参数菜单；仅在选择生成时保存文件')
    parser.add_argument('--conflict', choices=('cancel', 'backup'), help='自动化必须显式指定同名文件策略')
    parser.add_argument('--from-main-menu', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.recover and (args.config or args.source or args.conflict or args.interactive):
        parser.error('--recover 不与来源、配置或冲突选项合用')
    if args.interactive and not args.config:
        parser.error('--interactive 须与 --config 配合使用')
    if args.config and not args.interactive and args.conflict is None:
        parser.error('--config 自动化生成必须显式指定 --conflict cancel|backup')
    from .wannier_workflow import initial_config
    try:
        if args.recover:
            from .wannier_publish import recover
            recover(args.recover)
            print('已恢复中断的输入发布事务。')
            return 0
        if not args.config:
            return run_interactive(initial_config(args.source),
                                   return_to_main_status=RETURN_TO_MAIN if args.from_main_menu else 0)
        config = json.loads(args.config.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            raise ValueError('JSON 配置必须是对象')
        if 'config' in config:
            config = config['config']
            if not isinstance(config, dict):
                raise ValueError('JSON 中的 config 必须是对象')
        if args.source:
            config['source'] = args.source
        if args.interactive:
            return run_interactive(config, resume=True,
                                   return_to_main_status=RETURN_TO_MAIN if args.from_main_menu else 0)
        from .wannier_publish import publish, read_dependencies
        files, expected = _preview(config, print)
        written = publish(files, Path.cwd(), conflict=args.conflict, expected=expected, protected=_protected(config),
                          dependencies=read_dependencies(files))
        print('已写入：' + ', '.join(str(path) for path in written))
        _pending_notice(files, print)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Wannier 输入生成失败：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
