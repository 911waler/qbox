"""Prepare an isolated PHONON workspace and validate its resumable stages.

This module never launches QE.  The shell runner calls begin immediately before
each command and finish only after that command exits successfully.  Completion
is tied to input hashes, upstream records, and validated products; large SCF
binary data use size/mtime inventories instead of repeated full-file hashing.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from .phonon_inputs import load_scf, write_inputs
from .wannier_inputs import parse_namelists, rewrite_namelists


STAGES = ('scf', 'ph', 'q2r', 'matdyn', 'plot')
MANIFEST = '.qbox-phonon.json'
SCHEMA = 1


def _root(directory):
    path = Path(directory).expanduser()
    if not path.is_absolute() or path.name != 'PHONON':
        raise ValueError('声子执行目录必须是绝对路径且名称为 PHONON')
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('PHONON 执行目录不能通过符号链接访问')
    if path.exists() and not path.is_dir():
        raise ValueError('PHONON 已存在但不是目录')
    return path


def _inside(directory, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('工作流文件路径不能逃逸 PHONON 目录')
    current = directory
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'工作流文件不能是符号链接：{current.name}')
    return current


def _prefix(raw):
    value = re.sub(r'[^A-Za-z0-9_.-]', '_', raw)
    while '..' in value:
        value = value.replace('..', '_')
    value = value.strip('.') or 'pwscf'
    if not re.match(r'[A-Za-z0-9_]', value):
        value = 'qbox_' + value
    return value


def _paths(prefix, xml):
    return {
        'scf': {'input': prefix + '.scf.in', 'log': 'scf.out', 'save': 'tmp/' + prefix + '.save'},
        'ph': {'input': prefix + '.ph.in', 'log': 'ph.out', 'dyn_prefix': prefix + '.dyn', 'xml': xml},
        'q2r': {'input': prefix + '.q2r.in', 'log': 'q2r.out', 'fc': prefix + '.fc' + ('.xml' if xml else '')},
        'matdyn': {'input': prefix + '.matdyn.in', 'log': 'matdyn.out',
                   'freq': prefix + '.freq', 'gp': prefix + '.freq.gp'},
        'plot': {'log': 'plot.out', 'metadata': prefix + '.path.json',
                 'png': prefix + '_phonon.png', 'svg': prefix + '_phonon.svg'},
    }


def _read(directory):
    directory = _root(directory)
    path = _inside(directory, MANIFEST)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('PHONON 中没有可读取的本流程状态文件') from exc
    if (not isinstance(data, dict) or data.get('schema') != SCHEMA
            or data.get('workflow') != 'qbox-phonon' or data.get('directory') != str(directory)):
        raise ValueError('PHONON 状态文件版本、归属或目录不匹配')
    prefix = data.get('file_prefix')
    if not isinstance(prefix, str) or not prefix or _prefix(prefix) != prefix:
        raise ValueError('PHONON 状态文件的 file_prefix 不安全')
    if type(data.get('xml')) is not bool or data.get('paths') != _paths(prefix, data['xml']):
        raise ValueError('PHONON 状态文件含非本流程拥有的路径')
    if not isinstance(data.get('stages'), dict) or set(data['stages']) != set(STAGES):
        raise ValueError('PHONON 状态文件的阶段信息不完整')
    for record in data['stages'].values():
        if not isinstance(record, dict) or record.get('status') not in ('pending', 'running', 'complete'):
            raise ValueError('PHONON 阶段状态无效')
    return directory, data


def _save(directory, data):
    target = _inside(directory, MANIFEST)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='.qbox-phonon-state-',
                                     dir=directory, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _regular(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError(f'阶段产物缺失、为空或不是普通文件：{path.name}')
    return path


def _snapshot(directory, paths, binary=False):
    result = {}
    for path in sorted(set(paths)):
        relative = str(path.relative_to(directory))
        path = _regular(_inside(directory, relative))
        stat = path.stat()
        item = {'size': stat.st_size}
        if binary and path.suffix.lower() in ('.dat', '.hdf5', '.h5'):
            item['mtime_ns'] = stat.st_mtime_ns
        elif stat.st_size > 8 * 1024 * 1024:
            item['mtime_ns'] = stat.st_mtime_ns
        else:
            item['sha256'] = _hash(path)
        result[relative] = item
    return result


def _input_snapshot(directory, data, stage):
    descriptor = data['paths'][stage]
    names = [descriptor['input']] if 'input' in descriptor else []
    if stage in ('matdyn', 'plot'):
        names.append(data['paths']['plot']['metadata'])
    result = {name: _hash(_regular(_inside(directory, name))) for name in names}
    if stage == 'scf':
        scf = load_scf(_inside(directory, descriptor['input']))
        if scf.prefix != data['file_prefix'] or scf.outdir != str(directory / 'tmp'):
            raise ValueError('工作 SCF 的 prefix/outdir 已偏离本流程，必须重新配置')
        if scf.get('control', 'wfcdir') != str(directory / 'tmp'):
            raise ValueError('工作 SCF 的 wfcdir 必须位于 PHONON/tmp')
        if (scf.get('control', 'restart_mode') != 'from_scratch'
                or scf.get('control', 'disk_io') not in ('low', 'medium', 'high')
                or scf.get('electrons', 'startingpot') == 'file'
                or scf.get('electrons', 'startingwfc') == 'file'):
            raise ValueError('隔离 SCF 必须从头开始并保留 PH 所需波函数；请重新配置')
        pseudo_dir = Path(scf.get('control', 'pseudo_dir', ''))
        if not pseudo_dir.is_absolute():
            raise ValueError('工作 SCF 的 pseudo_dir 必须为绝对路径')
        for species in scf.species:
            pseudo = pseudo_dir / species.pseudo
            if not pseudo.is_file():
                raise ValueError(f'缺少赝势：{pseudo}')
            result['pseudo:' + str(pseudo)] = _hash(pseudo)
    elif stage in ('ph', 'q2r', 'matdyn'):
        section = 'inputph' if stage == 'ph' else 'input'
        settings = parse_namelists(_inside(directory, descriptor['input']).read_text())[section]
        prefix = data['file_prefix']
        xml = '.xml' if data['xml'] else ''
        required = {
            'ph': {'prefix': prefix, 'outdir': str(directory / 'tmp'), 'fildyn': prefix + '.dyn' + xml, 'ldisp': True},
            'q2r': {'fildyn': prefix + '.dyn' + xml, 'flfrc': prefix + '.fc'},
            'matdyn': {'flfrc': prefix + '.fc' + xml, 'flfrq': prefix + '.freq'},
        }[stage]
        if any(settings.get(key) != value for key, value in required.items()):
            raise ValueError(f'{stage} 输入的路径或色散模式被修改，必须重新配置')
        # Extra QE output path options must not redirect writes out of this workspace.
        for key in ('fildvscf', 'fildrho', 'flvec', 'fleig', 'fldyn', 'wpot_dir'):
            value = settings.get(key)
            if value:
                _inside(directory, str(value))
    return result


def _log(directory, data, stage):
    path = _regular(_inside(directory, data['paths'][stage]['log']))
    text = path.read_text(errors='replace')
    if stage != 'plot':
        if not re.search(r'\bJOB\s+DONE\.', text, re.I) or re.search(r'Error in routine|convergence NOT achieved', text, re.I):
            raise ValueError(f'{stage} 日志未确认成功完成')
    if stage == 'scf' and not re.search(r'convergence has been achieved', text, re.I):
        raise ValueError('SCF 日志未确认自洽收敛')
    return path


def _xml(path):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f'XML 产物不完整：{path.name}') from exc


def _artifacts(directory, data, stage):
    descriptor = data['paths'][stage]
    paths = [_log(directory, data, stage)]
    if stage == 'scf':
        saved = _inside(directory, descriptor['save'])
        if not saved.is_dir():
            raise ValueError('SCF 缺少保存数据目录')
        xml = _regular(_inside(directory, descriptor['save'] + '/data-file-schema.xml'))
        _xml(xml)
        charge = [p for p in saved.iterdir() if p.name in ('charge-density.dat', 'charge-density.hdf5')]
        spin = load_scf(_inside(directory, descriptor['input'])).get('system', 'nspin', 1)
        waves = [p for p in saved.iterdir() if re.fullmatch(r'wfc(?:up|dw)?\d+\.(?:dat|hdf5|h5)', p.name)]
        if spin == 2:
            channels = [{re.search(r'\d+', p.name).group() for p in waves if p.name.startswith('wfc' + channel)}
                        for channel in ('up', 'dw')]
            if not channels[0] or channels[0] != channels[1]:
                raise ValueError('自旋极化 SCF 保存数据缺少配对的 up/dw 波函数')
        # PH reconstructs disposable prefix.wfcN files from collected save data.
        # Their appearance must not mutate the upstream SCF product inventory.
        if not waves:
            waves = [p for p in (directory / 'tmp').iterdir()
                     if re.fullmatch(re.escape(data['file_prefix']) + r'\.wfc\d+(?:\.(?:dat|hdf5|h5))?', p.name)]
        if not charge or not waves:
            raise ValueError('SCF 保存数据缺少电荷密度或波函数')
        paths.extend([xml, *charge, *waves])
    elif stage == 'ph':
        prefix = descriptor['dyn_prefix']
        grid_paths = [p for p in (_inside(directory, prefix + '0'), _inside(directory, prefix + '0.xml')) if p.is_file()]
        if not grid_paths:
            raise ValueError('PH 缺少 dyn0 网格清单')
        grid_file = grid_paths[0]
        rows = [line.split() for line in grid_file.read_text().splitlines() if line.strip()]
        try:
            grid = tuple(int(value) for value in rows[0])
            count = int(rows[1][0])
            settings = parse_namelists(_inside(directory, descriptor['input']).read_text())['inputph']
            expected = tuple(settings[f'nq{i}'] for i in (1, 2, 3))
            if grid != expected or count < 1 or count > math.prod(grid) or len(rows) != count + 2:
                raise ValueError
            if any(len(row) != 3 or not all(math.isfinite(float(x.replace('D', 'e').replace('d', 'e'))) for x in row)
                   for row in rows[2:]):
                raise ValueError
        except (IndexError, KeyError, ValueError):
            raise ValueError('PH dyn0 网格维度、计数或 q 坐标不完整') from None
        paths.extend(grid_paths)
        for number in range(1, count + 1):
            path = _regular(_inside(directory, prefix + str(number) + ('.xml' if data['xml'] else '')))
            if data['xml']:
                _xml(path)
            paths.append(path)
    elif stage == 'q2r':
        force = _regular(_inside(directory, descriptor['fc']))
        if data['xml']:
            _xml(force)
        paths.append(force)
    elif stage == 'matdyn':
        from qbox.postprocess.phonon_plot import read_frequencies, prepare_segments
        frequency = _regular(_inside(directory, descriptor['freq']))
        gp = _regular(_inside(directory, descriptor['gp']))
        points, modes = read_frequencies(frequency.read_text())
        metadata = json.loads(_inside(directory, data['paths']['plot']['metadata']).read_text())
        prepare_segments(points, modes, metadata)
        rows = [line.split() for line in gp.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if len(rows) != len(points) or any(len(row) != modes.shape[1] + 1 for row in rows):
            raise ValueError('MATDYN freq.gp 点数或频率分支数不匹配')
        try:
            if not all(math.isfinite(float(value.replace('D', 'e').replace('d', 'e'))) for row in rows for value in row):
                raise ValueError
        except ValueError:
            raise ValueError('MATDYN freq.gp 含非法数值') from None
        paths.extend((frequency, gp))
    elif stage == 'plot':
        png = _regular(_inside(directory, descriptor['png']))
        svg = _regular(_inside(directory, descriptor['svg']))
        payload = png.read_bytes()
        if not payload.startswith(b'\x89PNG\r\n\x1a\n') or b'IEND' not in payload[-12:]:
            raise ValueError('绘图 PNG 文件不完整')
        if _xml(svg).tag.rsplit('}', 1)[-1] != 'svg':
            raise ValueError('绘图 SVG 文件无效')
        paths.extend((png, svg))
    return _snapshot(directory, paths, binary=stage == 'scf')


def _upstream(data, stage):
    index = STAGES.index(stage)
    return data['stages'][STAGES[index - 1]].get('stamp') if index else None


def _check(directory, data, stage):
    index = STAGES.index(stage)
    if index and not _check(directory, data, STAGES[index - 1]):
        return False
    record = data['stages'][stage]
    return (record.get('status') == 'complete'
            and record.get('inputs') == _input_snapshot(directory, data, stage)
            and record.get('upstream') == _upstream(data, stage)
            and record.get('products') == _artifacts(directory, data, stage))


def check(directory, stage):
    try:
        root, data = _read(directory)
        return _check(root, data, stage)
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return False


def _cleanup_paths(directory, data, first):
    prefix = data['file_prefix']
    result = []
    for stage in STAGES[STAGES.index(first):]:
        descriptor = data['paths'][stage]
        result.append(directory / descriptor['log'])
        if stage == 'scf':
            result.append(directory / 'tmp')
        elif stage == 'ph':
            result.extend(path for path in directory.iterdir()
                          if re.fullmatch(re.escape(prefix) + r'\.dyn\d+(?:\.xml)?', path.name))
            temporary = _inside(directory, 'tmp')
            if temporary.is_dir() and first != 'scf':
                result.extend(p for p in temporary.iterdir() if re.fullmatch(r'_ph\d+', p.name))
        elif stage == 'q2r':
            result.append(directory / descriptor['fc'])
        elif stage == 'matdyn':
            result.extend(directory / descriptor[key] for key in ('freq', 'gp'))
            result.extend(directory / name for name in ('matdyn.modes', 'matdyn.eig'))
        elif stage == 'plot':
            result.extend(directory / descriptor[key] for key in ('png', 'svg'))
    # Validate the whole removal set before removing any member.
    for path in result:
        _inside(directory, path.relative_to(directory))
        if path.is_dir() and any(child.is_symlink() for child in path.rglob('*')):
            raise ValueError(f'拒绝清理含符号链接的工作目录：{path.name}')
    return result


def _invalidate(directory, data, first):
    paths = _cleanup_paths(directory, data, first)
    for stage in STAGES[STAGES.index(first):]:
        data['stages'][stage] = {'status': 'pending'}
    _save(directory, data)
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def begin(directory, stage):
    root, data = _read(directory)
    if stage not in STAGES:
        raise ValueError('未知声子阶段')
    index = STAGES.index(stage)
    if index and not _check(root, data, STAGES[index - 1]):
        raise ValueError(f'{stage} 的上游计算尚未有效完成')
    inputs = _input_snapshot(root, data, stage)
    _invalidate(root, data, stage)
    data['stages'][stage] = {'status': 'running', 'inputs': inputs,
                              'upstream': _upstream(data, stage), 'started_at': time.time_ns()}
    _save(root, data)


def finish(directory, stage):
    root, data = _read(directory)
    if stage not in STAGES:
        raise ValueError('未知声子阶段')
    record = data['stages'][stage]
    if record.get('status') != 'running':
        raise ValueError(f'{stage} 没有对应的 begin 记录，不能凭旧产物标记完成')
    index = STAGES.index(stage)
    if index and not _check(root, data, STAGES[index - 1]):
        raise ValueError(f'{stage} 运行期间上游产物已改变')
    if record.get('inputs') != _input_snapshot(root, data, stage) or record.get('upstream') != _upstream(data, stage):
        raise ValueError(f'{stage} 运行期间输入发生变化，不能记录成功')
    products = _artifacts(root, data, stage)
    complete = {**record, 'status': 'complete', 'products': products, 'completed_at': time.time_ns()}
    complete['stamp'] = hashlib.sha256(json.dumps(complete, sort_keys=True).encode()).hexdigest()
    data['stages'][stage] = complete
    _save(root, data)


def prepare(directory, source=None, *, input_fn=input, output=print):
    """Return 0 prepared/reused, 10 cancelled, or 1 failed; never launch QE."""
    created = False
    root = None
    try:
        from .phonon_menu import prepare_interactive, _phonon_readme, _ask, _choose
        root = _root(directory)
        source = Path(source).expanduser().resolve() if source is not None else None
        previous = None
        if root.exists():
            if _inside(root, MANIFEST).is_file():
                _, previous = _read(root)
                origin = previous.get('source', {})
                changed_source = source is not None and (
                    str(source) != origin.get('path')
                    or not source.is_file()
                    or _hash(source) != origin.get('sha256'))
                changed_scf = False
                if (Path(origin.get('path', '')).suffix.lower() == '.cif'
                        and origin.get('generated_from_cif') is False):
                    linked_scf = Path(origin.get('scf_path', ''))
                    changed_scf = (not linked_scf.is_file()
                                   or _hash(linked_scf) != origin.get('scf_sha256'))
                if changed_source:
                    output(f"来源已改变：原来源 {origin.get('path', '未知')}；本次来源 {source}")
                if changed_scf:
                    output(f'关联 SCF 来源已改变或缺失：{linked_scf}')
                if changed_source or changed_scf:
                    choice = _choose(input_fn, output, {'1', '2'},
                                     '1) 重新配置（回车）  2) 返回：', '1')
                else:
                    choice = _choose(input_fn, output, {'0', '1', '2'},
                                     '已有声子工作流：0) 复用输入（回车）  1) 重新配置  2) 返回：', '0')
                if choice == '2':
                    return 10
                if choice == '0':
                    for stage in STAGES:
                        _input_snapshot(root, previous, stage)
                    output(f'复用声子输入：{root}')
                    return 0
                if source is None:
                    source = previous['source']['path']
            elif any(root.iterdir()):
                raise ValueError('PHONON 已有不属于本流程的文件，未覆盖；请另选空工作位置')
        else:
            root.mkdir(parents=True)
            created = True
        source = Path(source).expanduser().resolve() if source is not None else None
        identity = {}
        with tempfile.TemporaryDirectory(prefix='.qbox-phonon-prepare-', dir=root) as temporary:
            stage_dir = Path(temporary)

            def relocate(scf):
                prefix = _prefix(scf.file_prefix)
                original = scf.source.read_text(encoding='utf-8')
                default_pseudo = os.environ.get('ESPRESSO_PSEUDO', str(Path.home() / 'espresso' / 'pseudo'))
                pseudo = Path(scf.get('control', 'pseudo_dir', default_pseudo)).expanduser()
                if not pseudo.is_absolute():
                    pseudo = scf.source.parent / pseudo
                origin = source if source is not None else scf.source
                generated = scf.source.parent == stage_dir
                identity.update(path=str(origin), sha256=_hash(origin),
                                scf_path=str(root / (prefix + '.scf.in') if generated else scf.source),
                                scf_sha256=hashlib.sha256(original.encode()).hexdigest(),
                                generated_from_cif=generated)
                copied = rewrite_namelists(original, {'control': {
                    'prefix': prefix, 'outdir': str(root / 'tmp'), 'wfcdir': str(root / 'tmp'),
                    'pseudo_dir': str(pseudo.resolve()), 'restart_mode': 'from_scratch', 'disk_io': 'low',
                }, 'electrons': {'startingpot': 'atomic', 'startingwfc': 'atomic+random'}})
                path = stage_dir / (prefix + '.scf.in')
                path.write_text(copied, encoding='utf-8')
                return load_scf(path)

            bundle = prepare_interactive(source, output_dir=stage_dir, input_fn=input_fn,
                                         output=output, task='dispersion', transform_source=relocate)
            if bundle is None:
                return 10
            prefix = bundle.scf.file_prefix
            final_scf = replace(bundle.scf, source=root / (prefix + '.scf.in'))
            files = {prefix + '.scf.in': bundle.scf.source.read_text(encoding='utf-8'), **bundle.files}
            files[prefix + '.README.txt'] = _phonon_readme(final_scf, bundle.settings, root)
            old_inputs = set()
            if previous:
                old_inputs = {item['input'] for item in previous['paths'].values() if 'input' in item}
                old_inputs.update((previous['file_prefix'] + '.path.json', previous['file_prefix'] + '.README.txt'))
            for name in files:
                target = _inside(root, name)
                if target.exists() and name not in old_inputs:
                    raise ValueError(f'不能覆盖不属于本流程的文件：{name}')
            xml = bool(final_scf.get('system', 'noncolin', False) or final_scf.get('system', 'lspinorb', False))
            data = {'schema': SCHEMA, 'workflow': 'qbox-phonon', 'directory': str(root),
                    'source': identity, 'file_prefix': prefix, 'xml': xml,
                    'settings': asdict(bundle.settings), 'paths': _paths(prefix, xml),
                    'stages': {name: {'status': 'pending'} for name in STAGES}}
            if previous:
                _invalidate(root, previous, 'scf')
            write_inputs(files, root, overwrite=bool(previous))
            _save(root, data)
            for name in sorted(old_inputs - set(files)):
                _inside(root, name).unlink(missing_ok=True)
            output(f'声子谱工作目录已准备：{root}')
            return 0
    except (EOFError, StopIteration, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        output(f'声子工作流准备失败：{exc}')
        return 1
    finally:
        if created and root is not None and root.is_dir() and not any(root.iterdir()):
            root.rmdir()


def main(argv=None):
    parser = argparse.ArgumentParser(description='准备及校验 PHONON 声子谱执行工作流')
    subparsers = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'info', 'check', 'begin', 'finish'):
        item = subparsers.add_parser(command)
        item.add_argument('--directory', type=Path, required=True)
        if command == 'prepare':
            item.add_argument('--source', type=Path)
        elif command in ('check', 'begin', 'finish'):
            item.add_argument('--stage', choices=STAGES, required=True)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        return prepare(args.directory, args.source)
    if args.command == 'check':
        return 0 if check(args.directory, args.stage) else 1
    try:
        if args.command == 'info':
            _, data = _read(args.directory)
            print(data['file_prefix'])
        elif args.command == 'begin':
            begin(args.directory, args.stage)
        else:
            finish(args.directory, args.stage)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(f'声子阶段验证失败：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
