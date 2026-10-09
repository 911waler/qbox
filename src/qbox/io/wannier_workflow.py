"""File-facing orchestration; generation stays separate from publication."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re


_MODEL_INTEGER_KEYS = ('num_iter', 'dis_num_iter', 'conv_window', 'dis_conv_window')
_MODEL_REAL_KEYS = ('conv_tol', 'dis_mix_ratio', 'dis_conv_tol')


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_fermi_energy(path):
    """Read a reported SCF chemical potential; a band edge is not a Fermi level."""
    text = Path(path).read_text(encoding='utf-8')
    values = re.findall(r'the\s+Fermi\s+energy\s+is\s+([+\-\d.eEdD]+)\s*ev', text, re.I)
    if not values:
        raise ValueError('所选 SCF 输出没有明确的共同费米能；请直接输入，不能用最高占据能级代替。')
    value = float(values[-1].replace('D', 'e').replace('d', 'e'))
    if not math.isfinite(value):
        raise ValueError('SCF 输出费米能不是有限数值')
    return value


def _win_parts(text):
    values, blocks = {}, {}
    current = None
    for raw in text.splitlines():
        line = re.split(r'[!#]', raw, maxsplit=1)[0].strip()
        if not line:
            continue
        begin = re.fullmatch(r'begin\s+(\w+)', line, re.I)
        end = re.fullmatch(r'end\s+(\w+)', line, re.I)
        if begin:
            if current is not None:
                raise ValueError('已有 win 中存在嵌套 block')
            current = begin[1].lower()
            if current in blocks:
                raise ValueError(f'已有 win 中重复 block：{current}')
            blocks[current] = []
        elif end:
            if current != end[1].lower():
                raise ValueError('已有 win 的 begin/end 不匹配')
            current = None
        elif current:
            blocks[current].append(line)
        else:
            pair = re.match(r'(\w+)\s*(?:=|:|\s)\s*(.+)', line)
            if not pair:
                raise ValueError(f'无法解析已有 win 行：{line}')
            key = pair[1].lower()
            if key in values:
                raise ValueError(f'已有 win 中重复参数：{key}')
            values[key] = pair[2].strip()
    if current:
        raise ValueError(f'已有 win 中未结束的 block：{current}')
    return values, blocks


def _basis(text):
    from .wannier_profiles import PROFILE_KEYS, PROFILE_BLOCKS
    kept, block = [], None
    for raw in text.splitlines(keepends=True):
        line = re.split(r'[!#]', raw, maxsplit=1)[0].strip()
        start = re.fullmatch(r'begin\s+(\w+)', line, re.I)
        stop = re.fullmatch(r'end\s+(\w+)', line, re.I)
        if start:
            block = start[1].lower()
        if block:
            if block not in PROFILE_BLOCKS:
                kept.append(raw)
            if stop:
                block = None
        else:
            key = re.match(r'(\w+)\s*(?:=|:|\s)', line)
            if not key or key[1].lower() not in PROFILE_KEYS:
                kept.append(raw)
    return ''.join(kept).rstrip() + '\n'


def _existing_basis(text):
    values, blocks = _win_parts(text)
    try:
        nw = int(values['num_wann'])
        nb = int(values.get('num_bands', nw))
        grid = [int(v) for v in values['mp_grid'].replace(',', ' ').split()]
    except (ValueError, KeyError) as error:
        raise ValueError('已有 win 必须包含有效 num_wann、num_bands 和 mp_grid') from error
    if nw < 1 or nb < nw or len(grid) != 3 or min(grid) < 1:
        raise ValueError('已有 win 中轨道、能带或网格维度无效')
    if len(blocks.get('kpoints', [])) != math.prod(grid):
        raise ValueError('已有 win 的 kpoints 与 mp_grid 维度不一致')
    spinor = values.get('spinors', 'false').lower().strip('.') in ('true', 't')
    spin_mode = 'spinor' if spinor else ('collinear' if values.get('spin', '').lower() in ('up', 'down') else 'scalar')
    model_settings = {}
    for key in _MODEL_INTEGER_KEYS:
        if key in values:
            # Existing native settings include zero iterations and a negative
            # conv_window to disable the spread convergence stopping criterion.
            if not re.fullmatch(r'[+-]?\d+', values[key]):
                raise ValueError(f'已有 win 的 {key} 必须为整数')
            value = int(values[key])
            if key != 'conv_window' and value < 0:
                raise ValueError(f'已有 win 的 {key} 必须为非负整数')
            model_settings[key] = value
    for key in _MODEL_REAL_KEYS:
        if key in values:
            try:
                value = float(values[key].replace('D', 'e').replace('d', 'e'))
            except ValueError as error:
                raise ValueError(f'已有 win 的 {key} 必须为有限数值') from error
            if (not math.isfinite(value) or value < 0 or
                    key == 'dis_mix_ratio' and not 0 < value <= 1):
                raise ValueError(f'已有 win 的 {key} 超出允许范围')
            model_settings[key] = value
    return {'grid': grid, 'nbnd': nb, 'num_wann': nw,
            'projections': blocks.get('projections', []), 'spin_mode': spin_mode,
            'exclude_bands': values.get('exclude_bands', ''),
            'windows': {key: values[key] for key in values if key.startswith('dis_') and ('min' in key or 'max' in key)},
            **model_settings}


def _win_geometry(text):
    _, blocks = _win_parts(text)
    rows = list(blocks.get('unit_cell_cart', []))
    unit = rows.pop(0).lower() if rows and rows[0].lower() in ('angstrom', 'ang', 'bohr') else 'angstrom'
    factor = 0.529177210903 if unit == 'bohr' else 1.
    try:
        cell = [tuple(float(v) * factor for v in row.split()) for row in rows]
        atoms = [(parts[0], tuple(float(v) for v in parts[1:]))
                 for parts in (row.split() for row in blocks.get('atoms_frac', []))]
    except ValueError as exc:
        raise ValueError('无法读取已有 win 的晶胞或原子分数坐标') from exc
    if len(cell) != 3 or any(len(row) != 3 for row in cell) or not atoms or any(len(xyz) != 3 for _, xyz in atoms):
        raise ValueError('自动路径/QE 对照需要 win 中的 unit_cell_cart 和 atoms_frac 三维坐标')
    if not all(math.isfinite(v) for row in cell for v in row) or not all(math.isfinite(v) for _, xyz in atoms for v in xyz):
        raise ValueError('已有 win 晶胞/坐标必须是有限数值')
    return cell, atoms


def _reference_from_existing(config, text, seed, output_dir):
    from .wannier_inputs import parse_qe, build_reference
    if not config.get('reference_source'):
        raise ValueError('已有结果的 QE 对照需要 reference_source 指定原 SCF 输入，以保留完整物理设置。')
    reference = Path(config['reference_source']).expanduser().resolve(strict=True)
    qe = parse_qe(reference.read_text(encoding='utf-8'))
    cell, atoms = _win_geometry(text)
    if (len(qe.atoms) != len(atoms) or
            any(abs(a-b) > 1e-7 for first, second in zip(qe.cell, cell) for a, b in zip(first, second)) or
            any(label != other or any(abs((a-b)-round(a-b)) > 1e-7 for a, b in zip(xyz, coords))
                for (label, xyz), (other, coords) in zip(qe.atoms, atoms))):
        raise ValueError('QE 对照的 SCF 晶胞、原子顺序或位置与已有 Wannier 模型不匹配')
    basis = _existing_basis(text)
    if qe.spin_mode != basis['spin_mode']:
        raise ValueError('QE 对照的 SCF 自旋模式与已有 Wannier 模型不匹配')
    values, _ = _win_parts(text)
    excluded = set()
    for token in re.split(r'[,;\s]+', values.get('exclude_bands', '').strip()):
        if not token:
            continue
        match = re.fullmatch(r'(\d+)(?:[-:](\d+))?', token)
        if not match:
            raise ValueError('已有 win 的 exclude_bands 格式无效')
        first, last = int(match[1]), int(match[2] or match[1])
        if first < 1 or last < first or last - first > 100000:
            raise ValueError('已有 win 的 exclude_bands 范围无效')
        excluded.update(range(first, last + 1))
    total_bands = basis['nbnd'] + len(excluded)
    if excluded and max(excluded) > total_bands:
        raise ValueError('已有 win 的 exclude_bands 超出重建的 QE 能带数')
    reference_parameters = {**config.get('parameters', {}), 'nbnd': total_bands}
    result = build_reference(qe, seed, reference_parameters,
                             run_root=config.get('run_root'), output_dir=output_dir,
                             spin_channel=values.get('spin') if qe.spin_mode == 'collinear' else None)
    for name in result:
        if (output_dir / name).resolve() == reference:
            raise ValueError('QE 对照输出不得覆盖来源 SCF；请调整来源或文件名称。')
    return result


def initialize_basis_defaults(config, source_nbnd=None):
    """Apply first-run defaults, preserving manual values and the source file."""
    from .wannier_defaults import apply_initial_defaults
    notes = apply_initial_defaults(config)
    auto_basis = 'projections' in config.get('basis_defaults', {})
    if auto_basis and source_nbnd is not None and source_nbnd < (config.get('num_wann') or 0):
        config.pop('nbnd', None)
        notes = apply_initial_defaults(config)
        notes.insert(0, f'原 SCF 的 {source_nbnd} 条能带不足以容纳初始轨道；新 NSCF 预填 {config["nbnd"]} 条，原 SCF 文件保持不变。')
    elif source_nbnd is not None:
        config.setdefault('basis_defaults', {})['nbnd'] = '从 SCF 输入读取，保留原值'
    config['basis_default_notes'] = notes


def initial_config(source=None):
    """Import a source and fill editable first-run basis defaults when supported."""
    config = {'source': str(source) if source else '', 'run_root': str(Path.cwd()),
              'seed': 'wannier', 'version': '3.1.0', 'mode': 'new',
              'grid': [4, 4, 4], 'nbnd': None, 'num_wann': None, 'projections': [],
              'exclude_bands': [], 'windows': {}, 'tasks': [], 'parameters': {},
              'channels': {}, 'spin_mode': 'scalar', 'nbnd_confirmed': False}
    if not source:
        return config
    path = Path(source).expanduser().resolve(strict=True)
    config['source'] = str(path)
    config['seed'] = re.sub(r'[^A-Za-z0-9_.-]', '_', path.stem)
    if path.suffix.lower() == '.cif':
        if not path.is_file():
            raise ValueError('CIF 来源必须是普通文件')
        config.update(source='', structure_source=str(path))
        return config
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.win':
        config.update(_existing_basis(text))
        config['mode'] = 'existing'
        config['nbnd_confirmed'] = True
        # Import parameters for display only; selected tasks still start empty.
        from .wannier_profiles import FIELDS
        values, blocks = _win_parts(text)
        for key, field in FIELDS.items():
            if key in blocks and field['type'] == 'path':
                config['parameters'][key] = blocks[key]
            if key in values:
                raw = values[key]
                if field['type'] == 'bool':
                    if raw.lower().strip('.') not in ('true', 'false', 't', 'f'):
                        raise ValueError(f'已有 win 的 {key} 不是逻辑值')
                    value = raw.lower().strip('.') in ('true', 't')
                elif field['type'] in ('mesh', 'mesh2'):
                    value = [int(part) for part in raw.replace(',', ' ').split()]
                    if len(value) == 1:
                        value *= 2 if field['type'] == 'mesh2' else 3
                elif key == 'wannier_plot_format' and raw.lower() == 'xcrysden':
                    value = 'xsf'
                else:
                    try:
                        value = json.loads(raw)
                    except json.JSONDecodeError:
                        value = raw
                config['parameters'][key] = value
    else:
        from .wannier_inputs import parse_qe
        qe = parse_qe(text)
        config.update(nbnd=qe.nbnd, spin_mode=qe.spin_mode)
        mesh = re.search(r'(?im)^\s*K_POINTS\s*[{(]?automatic[})]?\s*\n\s*(\d+)\s+(\d+)\s+(\d+)', text)
        if mesh:
            config['grid'] = [int(mesh[i]) for i in range(1, 4)]
        initialize_basis_defaults(config, qe.nbnd)
        # The path is geometry-derived; no unknown energy or Fermi level is guessed.
        from importlib.util import find_spec
        if find_spec('seekpath') is not None:
            config['parameters']['kpoint_path'] = 'auto'
        from .wannier_qe_reuse import inspect_qe, adopt_nscf
        adopt_nscf(config, inspect_qe(config))
    return config


def _data_check(root, seed, basis, flags):
    """Check readable dimensions, never infer checkpoint provenance by name."""
    nb = basis['nbnd']
    nk = math.prod(basis['grid'])
    required = [seed + suffix for suffix in ('.win', '.chk', '.eig', '.mmn')]
    if flags.get('write_spn'):
        required.append(seed + '.spn')
    if flags.get('write_uHu'):
        required.append(seed + '.uHu')
    missing = [name for name in required if not (root / name).is_file()]
    unreadable = []
    eig = root / (seed + '.eig')
    if eig.is_file():
        count = 0
        outer_count = frozen_count = 0
        windows = {key: float(str(value).replace('D', 'E').replace('d', 'e'))
                   for key, value in basis['windows'].items()}
        with eig.open(encoding='utf-8') as handle:
            for line in handle:
                if not line.strip():
                    continue
                values = line.split()
                try:
                    band, kpoint = int(values[0]), int(values[1])
                    energy = float(values[2].replace('D', 'E').replace('d', 'e'))
                except (ValueError, IndexError) as error:
                    raise ValueError('已有 eig 行格式无效') from error
                if (band, kpoint) != (count % nb + 1, count // nb + 1) or not math.isfinite(energy):
                    raise ValueError('已有 eig 带/网格维度或顺序不匹配')
                outer_count += windows.get('dis_win_min', -math.inf) <= energy <= windows.get('dis_win_max', math.inf)
                frozen_count += ('dis_froz_max' in windows and
                                 windows.get('dis_froz_min', -math.inf) <= energy <= windows['dis_froz_max'])
                count += 1
                if band == nb and nb > basis['num_wann']:
                    if outer_count < basis['num_wann']:
                        raise ValueError(f'k 点 {kpoint} 外窗带数少于 num_wann')
                    if frozen_count > basis['num_wann']:
                        raise ValueError(f'k 点 {kpoint} 冻结窗带数超过 num_wann')
                    outer_count = frozen_count = 0
        if count != nb * nk:
            raise ValueError(f'已有 eig 维度不匹配：需要 {nb * nk} 行，实际 {count}')
    mmn = root / (seed + '.mmn')
    if mmn.is_file():
        with mmn.open(encoding='utf-8') as handle:
            handle.readline()
            header = handle.readline().split()
        try:
            dims = [int(v) for v in header]
            if len(dims) != 3 or dims[:2] != [nb, nk] or dims[2] < 1:
                raise ValueError
        except ValueError as error:
            raise ValueError('已有 mmn 维度与 win 不匹配') from error
    if flags.get('write_unk'):
        channel = 'NC' if basis['spin_mode'] == 'spinor' else ('2' if basis.get('spin') == 'down' else '1')
        for index in range(1, nk + 1):
            name = f'UNK{index:05d}.{channel}'
            if not (root / name).is_file():
                missing.append(name)
    for name in required:
        if name.endswith(('.chk', '.spn', '.uHu')) and (root / name).is_file():
            unreadable.append(name)
    return {'missing': missing, 'binary_dimensions_unverified': unreadable,
            'provenance': '未验证：同名文件不能证明 checkpoint 与矩阵规范一致',
            'status': '需先补齐数据' if missing else '文件存在及可读维度检查通过；计算与规范未验证'}


def _prepare_existing(config, output_dir):
    from shlex import quote
    from .wannier_profiles import render_profile
    from .wannier_readme import (summary_lines, file_lines, uses_postw90,
                                uses_wannier_plot, reference_steps, interface_step,
                                mpi_command, execution_setup, numbered_steps)
    source = Path(config['source']).expanduser().resolve(strict=True)
    if source.suffix.lower() != '.win':
        raise ValueError('已有结果模式需要来源 .win')
    if source.parent != output_dir:
        raise ValueError('已有结果模式必须在原 .win/.chk 所在目录运行，避免复制名称伪造匹配结果。')
    seed = source.stem
    if config.get('seed', seed) != seed:
        raise ValueError('已有结果的 seed 名称锁定；改名或模型变更请转入重建流程。')
    original = source.read_text(encoding='utf-8')
    basis = _existing_basis(original)
    values, blocks = _win_parts(original)
    basis['spin'] = values.get('spin', '')
    for key in _MODEL_INTEGER_KEYS:
        if config.get(key) is not None and type(config[key]) is not int:
            raise ValueError(f'已有模型参数 {key} 必须保留原整数值；如需调整请转入重建流程。')
    for key in _MODEL_REAL_KEYS:
        if config.get(key) is not None and type(config[key]) not in (int, float):
            raise ValueError(f'已有模型参数 {key} 必须保留原数值；如需调整请转入重建流程。')
    for key in ('grid', 'nbnd', 'num_wann', 'projections', 'exclude_bands', 'windows', 'spin_mode',
                *_MODEL_INTEGER_KEYS, *_MODEL_REAL_KEYS):
        if key in config and config[key] != basis.get(key):
            raise ValueError(f'已有模型参数 {key} 锁定；如需调整请转入重建流程。')
    # Minimal existing-model configurations may omit the locked model fields.
    # Read the original bound for response defaults without rewriting its text.
    config.setdefault('windows', basis['windows'])
    from .wannier_response_defaults import refresh_response_defaults
    refresh_response_defaults(config)
    parameters = dict(config.get('parameters', {}))
    if 'shift_current' in config.get('tasks', []) and not parameters.get('kpoint_path'):
        parameters['kpoint_path'] = blocks.get('kpoint_path') or 'auto'
    if parameters.get('kpoint_path') == 'auto':
        from .wannier_paths import automatic_path
        cell, atoms = _win_geometry(original)
        path = automatic_path(cell, [xyz for _, xyz in atoms], [label for label, _ in atoms],
                              magnetic=basis['spin_mode'] != 'scalar')
        parameters['kpoint_path'] = [segment.win_line() for segment in path.segments]
        config.setdefault('parameters', {})['kpoint_path'] = parameters['kpoint_path']
    parameters['num_wann'] = basis['num_wann']
    parameters.pop('band_kpt_text', None)
    profile = render_profile(config.get('tasks', []), parameters,
                             basis['spin_mode'], config.get('version', '3.1.0'))
    base = _basis(original)
    files = {seed + '.win': base + '\n' + '\n'.join(profile.win_lines) + '\n'}
    if 'qe_bands' in config.get('tasks', []):
        files.update(_reference_from_existing(config, original, seed, output_dir))
    checks = _data_check(output_dir, seed, basis, profile.pw2_flags)
    extra_needed = any(name.endswith(('.uHu', '.spn')) or name.startswith('UNK') for name in checks['missing'])
    pw2 = output_dir / (seed + '.pw2wan')
    inputs = {}
    if extra_needed:
        if pw2.is_file():
            from .wannier_inputs import rewrite_namelists, parse_namelists
            flags = dict(profile.pw2_flags)
            flags.update(write_amn=False, write_mmn=False)
            interface = pw2.read_text(encoding='utf-8')
            inputs = parse_namelists(interface).get('inputpp', {})
            if inputs.get('seedname') != seed:
                raise ValueError('补导出接口的 seedname 与已有 Wannier seed 不匹配')
            expected_spin = basis['spin'] if basis['spin_mode'] == 'collinear' else 'none'
            if str(inputs.get('spin_component', 'none')).lower() != expected_spin:
                raise ValueError('补导出接口的自旋通道与已有 win 不匹配')
            if not (output_dir / (seed + '.nnkp')).is_file():
                checks['missing'].append(seed + '.nnkp')
            files[pw2.name] = rewrite_namelists(interface, {'inputpp': flags})

    notes = summary_lines(config, seed=seed, version=config.get('version', '3.1.0'),
                          spin_mode=basis['spin_mode'], output_dir=output_dir,
                          source_path=source, run_root=config.get('run_root'),
                          prefix=inputs.get('prefix'), outdir=inputs.get('outdir'))
    if checks['missing']:
        notes.append('需先补齐 / Required missing files: ' + ', '.join(checks['missing']))
    notes.extend(['原模型数据的规范一致性未验证。',
                  'Gauge consistency of the original model data remains unverified.'])
    if checks['binary_dimensions_unverified']:
        notes.append('二进制维度未核验 / Unverified binary dimensions: ' + ', '.join(checks['binary_dimensions_unverified']))
    notes.extend(file_lines(files))
    notes.extend(execution_setup(output_dir))
    tasks = config.get('tasks', [])
    steps = []
    if extra_needed:
        notes.extend([f'补导出须保留同一批原 NSCF 波函数、{seed}.nnkp 及原 prefix/outdir/自旋通道；波函数丢失时须重建模型和全部接口矩阵。',
                      f'Supplementary export requires the same original NSCF wavefunctions, {seed}.nnkp and prefix/outdir/spin channel; missing wavefunctions require rebuilding the model and all interface matrices.'])
        if pw2.name in files:
            steps.append(interface_step(seed, basis['spin'] or None))
        else:
            notes.extend(['缺少原 .pw2wan：提供原接口文件后重新生成补导出输入。',
                          'Original .pw2wan missing: provide it and regenerate the supplementary interface input.'])
    if uses_wannier_plot(tasks):
        command = f'wannier90.x {quote(seed)}'
        if values.get('gamma_only', '').lower() not in ('true', '.true.', 't', '.t.'):
            command = mpi_command(command)
        steps.append(('读取已有模型绘图或导出 / Plot or export the existing model', command))
    if uses_postw90(tasks):
        steps.append(('Wannier 后处理 / Wannier postprocessing', mpi_command(f'postw90.x {quote(seed)}')))
    steps.extend(reference_steps(seed, files))
    notes.extend(numbered_steps(steps))
    if 'centres' in tasks:
        notes.extend(['中心与展宽读取原 .wout，保留原 .xyz；restart=plot 不保证重新导出中心。',
                      'Read centres and spreads from the original .wout and retain the original .xyz; restart=plot may not re-export centres.'])
    # plot restart is necessary to use, rather than refit, the existing model.
    if any(task in config.get('tasks', []) for task in ('bands', 'qe_bands', 'orbitals', 'centres', 'model', 'fermi_surface', 'shift_current')):
        files[seed + '.win'] = re.sub(
            r'(?im)^[^\S\n]*restart(?:[^\S\n]*[=:]|[^\S\n]+)[^\n]*(?:\n|$)',
            '', files[seed + '.win']) + 'restart = plot\n'
    record = {'schema': 1, 'mode': 'existing', 'version': config.get('version', '3.1.0'),
              'config': config, 'source_sha256': _hash(original), 'model_sha256': _hash(base),
              'data_checks': checks, 'state': 'inputs_generated',
              'files': list(files) + [seed + '.qbox.json', seed + '.README.txt']}
    files[seed + '.qbox.json'] = json.dumps(record, ensure_ascii=False, indent=2) + '\n'
    files[seed + '.README.txt'] = '\n'.join(notes) + '\n'
    return files


def prepare(config, output_dir=None):
    """Fully validate and render, without changing any input or result file."""
    if not isinstance(config, dict):
        raise ValueError('配置必须是 JSON 对象')
    config = copy.deepcopy(config)
    output_dir = Path(output_dir or Path.cwd()).resolve(strict=True)
    if (config.get('mode', 'new') == 'new' and config.get('source')
            and Path(config['source']).suffix.lower() != '.cif'):
        from .wannier_qe_reuse import inspect_qe
        config['qe_progress'] = inspect_qe(config, output_dir)
        nscf = config['qe_progress']['nscf']
        if nscf.get('reusable'):
            config['source_nscf'] = nscf['input']
            for key in ('grid', 'nbnd'):
                if config.get(key) is None:
                    config[key] = nscf[key]
    from .wannier_output_defaults import ensure_output
    ensure_output(config)
    from .wannier_response_defaults import refresh_response_defaults
    refresh_response_defaults(config)
    if config.get('band_kpt'):
        point_file = Path(config['band_kpt']).expanduser().resolve(strict=True)
        config.setdefault('parameters', {})['band_kpt_text'] = point_file.read_text(encoding='utf-8')
    if config.get('mode', 'new') == 'existing':
        return _prepare_existing(config, output_dir)
    if config.get('mode', 'new') != 'new':
        raise ValueError('生成模式必须是 new 或 existing')
    if not config.get('source'):
        if config.get('structure_source'):
            raise ValueError('CIF 还需配置 SCF 输入：请在交互菜单 2 中完成，无需预先运行 SCF 计算。')
        raise ValueError('请选择 CIF 结构或 SCF 输入文件')
    source = Path(config['source']).expanduser().resolve(strict=True)
    if source.suffix.lower() == '.cif':
        raise ValueError('CIF 还需配置 SCF 输入：请先运行 qbox --task wannier-input 结构.cif，再使用生成的 SCF 输入配置自动化任务。')
    original = source.read_text(encoding='utf-8')
    from .wannier_inputs import build_bundle
    files = build_bundle(original, config, source_path=source,
                         run_root=Path(config.get('run_root') or Path.cwd()).expanduser(),
                         output_dir=output_dir)
    # Bundle-specific artifacts must never become a writable alias of the source.
    for name in files:
        if (output_dir / name).resolve() == source:
            raise ValueError(f'生成目标与来源 SCF 相同：{name}；请修改 Wannier 名称。')
    return files
