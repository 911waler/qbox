"""Compact bilingual run guides shared by new and existing Wannier models."""
from pathlib import Path
from shlex import quote
import os


_PLOT_TASKS = {'bands', 'qe_bands', 'orbitals', 'centres', 'model', 'fermi_surface', 'shift_current'}
_POST_TASKS = {'dos', 'projected_dos', 'boltzmann', 'berry_path', 'berry_slice',
               'ahc', 'shc', 'optical', 'shift_current', 'orbital_magnetization',
               'natural_optical_activity', 'current_induced_optical',
               'current_induced_magnetization'}


def uses_postw90(tasks):
    return bool(_POST_TASKS.intersection(tasks))


def uses_wannier_plot(tasks):
    return bool(_PLOT_TASKS.intersection(tasks))


def mpi_command(command):
    return 'mpirun -np 4 ' + command


def _resume_command(seed):
    # Use this checkout when generating from source; installed packages use
    # their normal qbox command. Never point at an unrelated installed version.
    entry = Path(__file__).resolve().parents[3] / 'qbox'
    launcher = str(entry) if entry.is_file() and os.access(entry, os.X_OK) else 'qbox'
    return (quote(launcher) + ' --task wannier-input --config '
            + quote(seed + '.qbox.json') + ' --conflict backup --interactive')


def execution_setup(output_dir):
    """Render configured environment setup, without discovering or running tools."""
    lines = ['', '运行准备 / Preparation']
    qe_module = os.environ.get('QBOX_WANNIER_QE_MODULE')
    wannier_module = os.environ.get('QBOX_WANNIER_MODULE')
    bindir = os.environ.get('QBOX_WANNIER_BIN_DIR')
    modules = [module for module in (qe_module, wannier_module) if module]
    if modules:
        lines.append('module load ' + ' '.join(quote(module) for module in modules))
    if bindir and not wannier_module:
        lines.append('export PATH=' + quote(str(Path(bindir).expanduser())) + ':"$PATH"')
    lines += ['export OMP_NUM_THREADS=1', 'cd ' + quote(str(output_dir))]
    return lines


def numbered_steps(steps):
    lines = ['', '执行顺序 / Run in sequence']
    for number, (title, command) in enumerate(steps, 1):
        lines += [f'{number}. {title}', command, '']
    return lines


def interface_step(seed, channel=None):
    suffix = '_' + channel if channel else ''
    title = '导出接口数据 / Export interface data' + (f' ({channel})' if channel else '')
    return title, mpi_command(f'pw2wannier90.x -in {quote(seed + ".pw2wan")} > pw2wan{suffix}.out')


def _display_path(path, output_dir):
    path = Path(path).expanduser().absolute()
    try:
        return str(path.relative_to(Path(output_dir).absolute()))
    except ValueError:
        return str(path)


def output_lines(config, output_dir=None):
    """Keep imported output and its energies together in the calculation summary."""
    record = config.get('qe_output')
    lines = []
    if record:
        path = _display_path(record['path'], output_dir or Path.cwd())
        info = record['kind'].upper()
        if record.get('nbnd'):
            info += f', nbnd={record["nbnd"]}'
        lines.append(f'已读输出 / Imported QE output: {path} ({info})')
        energies = []
        for key, label in (('fermi_energy', '费米能/EF'), ('homo', '最高占据/HOMO'),
                           ('lumo', '最低未占据/LUMO')):
            if record.get(key) is not None:
                energies.append(f'{label}={record[key]:.10g}')
        lower, upper = record.get('eigenvalue_min'), record.get('eigenvalue_max')
        if lower is not None and upper is not None:
            energies.append(f'本征值/printed eigenvalues=[{lower:.10g}, {upper:.10g}]')
        if energies:
            lines.append('输出能量 / Output energies (eV): ' + '; '.join(energies))
    fermi = (config.get('parameters') or {}).get('fermi_energy')
    if fermi is not None and (not record or fermi != record.get('fermi_energy')):
        if config.get('fermi_source', {}).get('method') == 'sampled_midgap':
            lines.append(f'占据参考能 / Occupation reference: {fermi} eV（采样带隙中点 / sampled midgap）')
            lines.append('计算响应前确认该值仍位于 Wannier 插值带隙内 / Confirm this value remains inside the interpolated gap before computing the response.')
        else:
            lines.append(f'后处理费米能 / Postprocessing EF: {fermi} eV')
    return lines


def summary_lines(config, *, seed, version, spin_mode, output_dir,
                  source_path=None, run_root=None, prefix=None, outdir=None):
    lines = [f'Wannier90 {version} — {seed}', '', '计算摘要 / Calculation summary',
             f'运行目录 / Run directory: {output_dir}']
    if run_root is not None and Path(run_root).resolve() != Path(output_dir).resolve():
        lines.append(f'原 QE 目录 / Original QE directory: {run_root}')
    if source_path:
        lines.append(f'来源输入 / Source input: {_display_path(source_path, output_dir)}')
    settings = []
    if prefix is not None:
        settings.append(f'prefix={prefix}')
    if outdir is not None:
        settings.append(f'outdir={outdir}')
    settings.append(f'spin={spin_mode}')
    lines.append('QE: ' + ' | '.join(settings))
    lines.extend(output_lines(config, output_dir))
    if 'shift_current' in config.get('tasks', []):
        from .wannier_profiles import fields_for_tasks, _number
        fields = fields_for_tasks(config['tasks'])
        parameters = config.get('parameters') or {}
        photon_min = parameters.get('kubo_freq_min', fields['kubo_freq_min']['default'])
        photon_max = parameters.get('kubo_freq_max', fields['kubo_freq_max']['default'])
        cutoff = parameters.get('kubo_eigval_max', fields['kubo_eigval_max']['default'])
        photon_range = ('待补全 / pending' if photon_max is None else
                        f'{_number(photon_min or 0, "kubo_freq_min"):g}–{_number(photon_max, "kubo_freq_max"):g} eV')
        cutoff_value = '待补全 / pending' if cutoff is None else f'{_number(cutoff, "kubo_eigval_max"):g} eV'
        lines += [f'光子能量 / Photon energy: {photon_range}',
                  f'初/末态能量上限 / Initial/final-state cutoff: {cutoff_value}（与 .eig 同零点 / same energy zero as .eig）',
                  'SC 沿用同一模型的 .win/.chk/.eig/.mmn / SC uses matching .win/.chk/.eig/.mmn from one model.']
    return lines


def file_lines(files):
    purposes = (('.nscf.in', '均匀网格 / NSCF'),
                ('.win', '模型与任务 / Wannier model & tasks'),
                ('.pw2wan', '接口导出 / QE → Wannier90'),
                ('.bands.pp.in', '能带整理 / bands.x'),
                ('.bands.in', 'QE 能带对照 / QE reference bands'))
    lines = ['', '文件用途 / Files']
    for name in files:
        for suffix, purpose in purposes:
            if name.endswith(suffix):
                lines.append(f'  {name} — {purpose}')
                break
    return lines


def reference_steps(seed, files):
    if f'{seed}.bands.in' not in files:
        return []
    steps = [('QE 能带计算 / QE band calculation',
              mpi_command(f'pw.x -in {quote(seed + ".bands.in")} > band.out'))]
    for name in files:
        if name.endswith('.bands.pp.in'):
            channel = next((value for value in ('up', 'down')
                            if name == f'{seed}_{value}.bands.pp.in'), None)
            suffix = '_' + channel if channel else ''
            title = '整理 QE 能带 / Process QE bands' + (f' ({channel})' if channel else '')
            steps.append((title, mpi_command(f'bands.x -in {quote(name)} > bands{suffix}.out')))
    return steps


def _qe_progress_steps(progress, seed, run_root, output_dir):
    lines, steps = [], []
    nscf = progress.get('nscf') or {}
    nscf_ready = nscf.get('completed') and nscf.get('data_present')
    for kind, title in (('scf', '自洽计算（SCF） / Self-consistent calculation (SCF)'),
                        ('nscf', '非自洽计算（NSCF） / Non-self-consistent calculation (NSCF)')):
        stage = progress.get(kind) or {}
        source = stage.get('input')
        ready = stage.get('completed') and stage.get('data_present')
        if source or stage.get('output'):
            state = ('已完成，数据存在 / completed, data present' if ready else
                     '计算已完成，缺少数据或完整性未确认 / completed, data missing or completeness unverified'
                     if stage.get('completed') else '已有输入，未确认完成 / input available, completion unverified')
            lines.append(f'{kind.upper()}: {_display_path(source or stage["output"], output_dir)} — {state}')
        if ready or kind == 'scf' and nscf_ready:
            continue
        if stage.get('completed'):
            lines += ['缺少的数据需先恢复；无法恢复时，使用已有输入重新计算。',
                      'Restore the missing data, or rerun the existing input if recovery is unavailable.']
        if kind == 'scf' and source is None:
            lines += ['未找到可复用的 SCF 输入或数据；运行 NSCF 前需先准备自洽电荷密度。',
                      'No reusable SCF input/data found; prepare the self-consistent charge density before NSCF.']
            continue
        directory = Path(stage.get('run_root') or run_root) if source else Path(output_dir)
        source = source or str(Path(output_dir) / (seed + '.nscf.in'))
        command = mpi_command(f'pw.x -in {quote(_display_path(source, directory))} > {kind}.out')
        if directory.resolve() != Path(output_dir).resolve():
            command = '(cd ' + quote(str(directory)) + ' && ' + command + ')'
        steps.append((title, command))
    return lines, steps


def new_model_lines(config, *, seed, version, qe, source_path, run_root,
                    output_dir, outdir, bases, files):
    lines = summary_lines(config, seed=seed, version=version, spin_mode=qe.spin_mode,
                          output_dir=output_dir, source_path=source_path,
                          run_root=run_root, prefix=qe.prefix, outdir=outdir)
    steps = []
    progress = config.get('qe_progress')
    if progress is not None:
        progress_lines, steps = _qe_progress_steps(progress, seed, run_root, output_dir)
        lines.extend(progress_lines)
    elif source_path:
        scf = mpi_command(f'pw.x -in {quote(_display_path(source_path, run_root))} > scf.out')
        if Path(run_root).resolve() != Path(output_dir).resolve():
            scf = '(cd ' + quote(str(run_root)) + ' && ' + scf + ')'
        steps.append(('自洽计算（SCF） / Self-consistent calculation (SCF)', scf))
    if progress is None:
        steps.append(('非自洽计算（NSCF） / Non-self-consistent calculation (NSCF)',
                      mpi_command(f'pw.x -in {quote(seed + ".nscf.in")} > nscf.out')))
    lines.extend(file_lines(files))
    lines.extend(execution_setup(output_dir))
    for basename in bases:
        channel = basename[len(seed) + 1:] if basename != seed else None
        label = f' ({channel})' if channel else ''
        steps += [('Wannier 预处理 / Wannier preprocessing' + label, f'wannier90.x -pp {quote(basename)}'),
                  interface_step(basename, channel),
                  ('Wannier 化 / Wannierisation' + label, mpi_command(f'wannier90.x {quote(basename)}'))]
    pending = list(config.get('pending_response_parameters') or [])
    if config.get('pending_fermi') and 'fermi_energy' not in pending:
        pending.insert(0, 'fermi_energy')
    if pending:
        steps.extend(reference_steps(seed, files))
        steps.append(('补全响应参数 / Complete response parameters', _resume_command(seed)))
        lines += ['', '待补全 / Pending: ' + ', '.join(pending),
                  '可先完成 Wannier 模型；响应参数补全后再运行后处理。',
                  'Build the Wannier model first; complete response parameters before postprocessing.']
        lines.extend(numbered_steps(steps))
        lines += ['补全时在菜单 2 选择需要读取的 SCF/NSCF 输出，在菜单 7 填写缺少的响应参数。',
                  'When completing inputs, choose the SCF/NSCF output in menu 2 and fill missing response parameters in menu 7.',
                  '核对插值能带后，按更新后的 README 运行后处理；模型设置未变时无需重复 SCF、NSCF 和 Wannier 化。',
                  'Check the interpolated bands, then run postprocessing from the updated README; unchanged model settings require no repeat of SCF, NSCF or Wannierisation.']
        return lines
    if uses_postw90(config.get('tasks', [])):
        steps.extend(('Wannier 后处理 / Wannier postprocessing' + (f' ({basename})' if len(bases) > 1 else ''),
                      mpi_command(f'postw90.x {quote(basename)}')) for basename in bases)
    steps.extend(reference_steps(seed, files))
    lines.extend(numbered_steps(steps))
    return lines
