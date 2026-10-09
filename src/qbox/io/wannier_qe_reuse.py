"""Read-only discovery of authoritative QE inputs and independently proven progress.

Input discovery never repairs or writes QE files. Explicit crystal k points keep
their original order; automatic meshes require a completed output that records
the actual full order. Restart-file presence is separate from output convergence.
"""
import copy
import hashlib
import math
import os
from pathlib import Path
import re

from .wannier_inputs import _integer, parse_qe
from .wannier_outputs import (_absolute, _check_companion, _companion,
                              _float, _mesh, _ordered_kpoints,
                              _points_match, _same_kpoint_order, discover_outputs)


def _directory(value, fallback, root):
    name = os.path.expandvars(os.path.expanduser(str(fallback if value is None else value)))
    if re.search(r'\$[A-Za-z_{]', name):
        raise ValueError(f'QE 目录含未解析的环境变量：{name}')
    path = Path(name)
    return _absolute(path if path.is_absolute() else root / path)


def _paths(qe, root):
    outdir = _directory(qe.outdir, os.environ.get('ESPRESSO_TMPDIR') or '.', root)
    return outdir, _directory(qe.wfcdir, outdir, root)


def _pseudopotentials(qe, root):
    directory = _directory(qe.pseudo_dir, os.environ.get('ESPRESSO_PSEUDO')
                           or Path.home() / 'espresso/pseudo', root)
    start, end, _ = qe.cards['ATOMIC_SPECIES']
    result = {}
    for line in qe.text[start:end].splitlines()[1:]:
        row = line.split('!', 1)[0].split()
        if row:
            result[row[0]] = _directory(row[2], '', directory).resolve()
    return result


def _compatible(source, source_root, candidate, candidate_root):
    _check_companion(source, candidate)
    for key in ('ecutwfc', 'ecutrho'):
        def cutoff(qe):
            value = qe.get('system', key)
            if value is None and key == 'ecutrho' and qe.get('system', 'ecutwfc') is not None:
                value = 4 * _float(qe.get('system', 'ecutwfc'))
            return None if value is None else _float(value)
        if cutoff(source) != cutoff(candidate):
            raise ValueError(f'已有输入的 {key} 与来源不一致。')
    if _pseudopotentials(source, source_root) != _pseudopotentials(candidate, candidate_root):
        raise ValueError('已有输入的赝势路径与来源不一致。')
    if source.prefix != candidate.prefix or _paths(source, source_root)[0].resolve() != _paths(candidate, candidate_root)[0].resolve():
        raise ValueError('已有输入的 prefix/outdir 与来源不一致，不能确认使用同一电荷密度。')


def _read_input(path, kind=None):
    try:
        qe = parse_qe(path.read_text(encoding='utf-8'))
        actual = str(qe.get('control', 'calculation', 'scf')).lower()
        if actual not in ('scf', 'nscf') or kind is not None and actual != kind:
            raise ValueError(f'需要 calculation={kind or "scf/nscf"} 的输入。')
        return qe
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f'已有 QE 输入 {path} 无法复用：{error} 原文件保持不变，请检查或明确选择来源。') from error


def _unique(candidates, kind):
    by_target = {}
    for path, qe, root in candidates:
        by_target.setdefault(path.resolve(), (path, qe, root))
    if len(by_target) > 1:
        names = '\n'.join(str(item[0]) for item in by_target.values())
        raise ValueError(f'发现多个兼容的 {kind.upper()} 输入，不能自动选择：\n{names}\n请明确指定所用输入。')
    return next(iter(by_target.values()), None)


def _find_input(config, source_path, source, source_root, directories, kind):
    source_kind = str(source.get('control', 'calculation', 'scf')).lower()
    if source_kind == kind:
        return source_path, source, source_root
    explicit = config.get('source_nscf') if kind == 'nscf' else None
    stems = [str(config.get('seed') or ''), re.sub(r'\.(?:scf|nscf)$', '', source_path.stem)]
    names = list(dict.fromkeys([f'{stem}.{kind}.in' for stem in stems if stem] + [f'{kind}.in']))
    preferred = ([_absolute(explicit)] if explicit else
                 [directory / name for directory in directories for name in names])

    def read(path):
        root = source_root if path.parent == source_path.parent else path.parent
        qe = _read_input(path, kind)
        try:
            _compatible(source, source_root, qe, root)
        except ValueError as error:
            raise ValueError(f'已有 {kind.upper()} 输入 {path} 无法复用：{error} 原文件保持不变，请检查或明确选择来源。') from error
        return path, qe, root

    matches = []
    for path in dict.fromkeys(preferred):
        if path.exists() or path.is_symlink() or explicit:
            matches.append(read(path))
    if matches:
        return _unique(matches, kind)
    for directory in directories:
        try:
            paths = sorted(directory.glob('*.in'))
        except OSError:
            continue
        for path in paths:
            if path == source_path:
                continue
            try:
                matches.append(read(path))
            except ValueError:
                continue
    return _unique(matches, kind)


def _unshifted_mesh(qe, path):
    try:
        mesh = _mesh(qe)
        if mesh is None:
            raise ValueError('需要完整、等权重、无偏移的均匀三维网格。')
        grid, normalized = mesh
        if any(abs(value * size - round(value * size)) > 2e-7
               for point in normalized for value, size in zip(point, grid)):
            raise ValueError('网格含偏移；Wannier 复用需要无偏移网格。')
        nbnd = _integer(qe.nbnd, 'NSCF nbnd')
        start, end, unit = qe.cards['K_POINTS']
        if unit == 'crystal':
            rows = [line.split('!', 1)[0].split() for line in qe.text[start:end].splitlines()]
            rows = [row for row in rows if row]
            points = [[_float(value) for value in row[:3]] for row in rows[2:]]
        else:
            points = None
        return grid, points, normalized, nbnd
    except (ValueError, IndexError, TypeError, OverflowError) as error:
        raise ValueError(f'已有 NSCF 输入 {path} 无法复用：{error} 原文件保持不变，不会重写 K_POINTS。') from error


def _nonempty(path):
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _restart_files(qe, root, kind, count=None):
    outdir, wfcdir = _paths(qe, root)
    save = outdir / f'{qe.prefix}.save'
    xml = [save / name for name in ('data-file-schema.xml', 'data-file.xml')]
    if kind == 'scf':
        density = [save / name for name in ('charge-density.dat', 'charge-density.hdf5')]
        files = [path for path in xml + density if path.is_file()]
        present = any(map(_nonempty, xml)) and any(map(_nonempty, density))
    else:
        files = [path for path in xml if path.is_file()]
        for directory, patterns in ((save, ('wfc*.dat', 'wfc*.hdf5')),
                                    (outdir, (f'{qe.prefix}.wfc*',)),
                                    (wfcdir, (f'{qe.prefix}.wfc*',))):
            for pattern in patterns:
                files.extend(path for path in directory.glob(pattern) if path.is_file())
        files = sorted(set(files))
        stems = ('wfcup', 'wfcdw') if qe.spin_mode == 'collinear' else ('wfc',)
        # Distributed prefix.wfc* names identify processor-local files, not a
        # proven complete k-point collection. Report them without promising
        # that a downstream interface can restart from them.
        present = bool(count) and any(map(_nonempty, xml)) and all(
            any(_nonempty(save / f'{stem}{index}.{suffix}') for suffix in ('dat', 'hdf5'))
            for stem in stems for index in range(1, count + 1))
    note = ('保存数据文件已齐备；文件存在不代表计算已收敛。' if present
            else '保存数据完整性未确认；请检查 XML、电荷密度或完整波函数集合。')
    return present, [str(path) for path in files], note


def _stage(selected, kind, directories, default_root, reference=None):
    result = dict(input=None, output=None, completed=False, data_present=False,
                  run_root=str(default_root), outputs=[], data_files=[])
    if kind == 'nscf':
        result.update(grid=None, nbnd=None, kpoints=[], prefix=None, outdir=None, reusable=False)
    if selected is None and (kind != 'scf' or reference is None):
        return result
    path, qe, root = selected or reference
    outdir, wfcdir = _paths(qe, root)
    if kind == 'nscf':
        grid, points, normalized, nbnd = _unshifted_mesh(qe, path)
        result.update(grid=grid, nbnd=nbnd)
    data_present, data_files, data_note = _restart_files(
        qe, root, kind, math.prod(grid) if kind == 'nscf' else None)
    result.update(prefix=qe.prefix, outdir=str(outdir), wfcdir=str(wfcdir), run_root=str(root),
                  data_present=data_present, data_files=data_files, data_note=data_note)
    if selected is not None:
        result.update(input=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for record in discover_outputs(path, directories, run_root=root):
        if record['kind'] != kind:
            continue
        output_path = Path(record['path'])
        try:
            text = output_path.read_text(encoding='utf-8')
            companion_path, _ = _companion(output_path, text, root)
            if selected is not None and companion_path is not None and companion_path.resolve() != path.resolve():
                continue
            if kind == 'nscf':
                actual = _ordered_kpoints(text, qe, math.prod(grid))
                if record['nbnd'] != nbnd or actual is None or not _points_match(normalized, actual, 2e-6, True):
                    continue
                if points is not None and not _same_kpoint_order(points, actual):
                    continue
                if points is None:
                    points = actual
        except (OSError, UnicodeError, ValueError):
            continue
        result['outputs'].append(record['path'])
        if result['output'] is None:
            result.update(output=record['path'], output_sha256=record['sha256'], completed=True)
    if kind == 'nscf':
        if points is None:
            raise ValueError(f'已有 NSCF 输入 {path} 使用 K_POINTS automatic；缺少可核对完整 k 点顺序的已完成输出。'
                             '请保留原输入并提供该计算的完整 QE 输出（含晶体或笛卡尔 k 点列表），不会自动重写。')
        result.update(kpoints=points, reusable=True)
    return result


def inspect_qe(config, output_dir=None):
    """Return SCF/NSCF progress without importing energy defaults or writing files.

    Preferred or explicitly selected inputs that cannot be reused raise instead
    of silently enabling generation. Nonpreferred unrelated inputs are skipped.
    ``run_root`` retains the original input's execution-directory semantics.
    """
    source_value = config.get('reference_source') if config.get('mode') == 'existing' else config.get('source')
    source_path = _absolute(source_value) if source_value else None
    root = _absolute(config.get('run_root') or (source_path.parent if source_path else Path.cwd()))
    empty = {kind: _stage(None, kind, [], root) for kind in ('scf', 'nscf')}
    if source_path is None or source_path.suffix.lower() in ('.cif', '.win'):
        return empty
    source = _read_input(source_path)
    directories = list(dict.fromkeys(_absolute(path) for path in
        [Path.cwd(), output_dir or Path.cwd(), source_path.parent, root]))
    selected = {kind: _find_input(config, source_path, source, root, directories, kind)
                for kind in ('scf', 'nscf')}
    return {kind: _stage(selected[kind], kind, directories, root,
                         reference=(source_path, source, root)) for kind in ('scf', 'nscf')}


def adopt_nscf(config, progress):
    """Adopt existing NSCF basis dimensions on startup; return the same config."""
    config['qe_progress'] = copy.deepcopy(progress)
    nscf = progress.get('nscf') or {}
    if nscf.get('reusable'):
        config.update(grid=list(nscf['grid']), nbnd=nscf['nbnd'],
                      source_nscf=nscf['input'], nbnd_confirmed=True)
        config.setdefault('basis_defaults', {}).update(
            grid='已读取 NSCF 输入的完整均匀网格；保留原 k 点顺序。',
            nbnd='已读取 NSCF 输入，保留原能带数。')
    return config
