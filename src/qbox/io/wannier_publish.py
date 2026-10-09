"""Recoverable publication of a small input bundle into an existing directory.

This is deliberately not described as an atomic multi-file operation. A journal
survives process termination; normal exceptions roll back the changes we own.
Unrelated edits encountered during rollback are never overwritten.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile


_SUFFIXES = ('.win', '.pw2wan', '.nscf.in', '.bands.in', '.bands.pp.in',
             '.qbox.json', '.README.txt')


def _name(name):
    if (not isinstance(name, str) or Path(name).name != name or
            name.startswith('.') or '\\' in name or '\n' in name or
            not name.endswith(_SUFFIXES)):
        raise ValueError(f'不允许发布该输入文件名：{name!r}')
    return name


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _state(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'目标不是普通文件（含符号链接）：{path}')
    # O_NOFOLLOW also protects the read if the entry was replaced after lstat.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        content = handle.read()
        after = os.fstat(handle.fileno())
    fields = lambda s: [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    if fields(info) != fields(before) or fields(before) != fields(after):
        raise ValueError(f'读取期间文件变化：{path}')
    return {'stat': fields(after), 'sha256': _digest(content)}


def snapshot(files, directory):
    """Capture every target (including absence) for a later publication check."""
    directory = Path(directory).resolve()
    return {_name(name): _state(directory / name) for name in files}


def _write(path, content):
    with path.open('xb') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _journal(stage, data):
    temporary = stage / 'transaction.next'
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, stage / 'transaction.json')
    fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _lock(directory):
    path = directory / '.qbox-wannier.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f'已有输入发布锁：{path}；确认无运行进程并恢复事务后再移除锁。') from exc
    try:
        os.write(fd, f'{os.getpid()}\n'.encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def _backup(path, content):
    directory = path.parent / 'bak'
    try:
        directory.mkdir()
    except FileExistsError:
        pass
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError(f'无法使用备份目录 bak；须为可访问的真实目录，不能是文件或符号链接：{directory}') from error
    try:
        opened = os.fstat(fd)
        def unchanged():
            current = directory.lstat()
            if (not stat.S_ISDIR(current.st_mode) or
                    (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
                raise ValueError(f'备份目录 bak 在发布期间发生变化：{directory}')
        index = 0
        while True:
            unchanged()
            name = path.name + '.bak' + (f'.{index}' if index else '')
            try:
                # Pin the directory and reserve the filename atomically. Neither
                # a replaced bak symlink nor an existing backup is followed.
                backup_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                    0o666, dir_fd=fd)
            except FileExistsError:
                index += 1
                continue
            with os.fdopen(backup_fd, 'wb') as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(fd)
            unchanged()
            return str(Path('bak') / name)
    finally:
        os.close(fd)


def _rollback(stage, data):
    conflicts = []
    for entry in reversed(data['entries']):
        target = stage.parent / entry['name']
        if not entry.get('armed'):
            continue
        try:
            current = _state(target)
            old = entry['old']
            # No change took place, or rollback has already restored old bytes.
            if current == old or (old and current and current['sha256'] == old['sha256']):
                continue
            if current is None and old is None:
                continue
            if current is None or current['sha256'] != entry['new_sha256']:
                raise ValueError('目标已被其他操作改动')
            if old is None:
                target.unlink()
            else:
                original = stage / entry['original']
                if _state(original)['sha256'] != old['sha256']:
                    raise ValueError('事务原文摘要不匹配')
                # Keep the recovery copy until all entries have been restored.
                restore = stage / (entry['original'] + '.restore')
                restore.unlink(missing_ok=True)
                _write(restore, original.read_bytes())
                os.replace(restore, target)
        except (OSError, ValueError, TypeError) as error:
            conflicts.append(f'{entry["name"]}: {error}')
    data['state'] = 'rollback-conflict' if conflicts else 'rolled-back'
    _journal(stage, data)
    if conflicts:
        raise ValueError('恢复遇到并发改动，保留事务清单：' + str(stage / 'transaction.json') +
                         '\n' + '\n'.join(conflicts))


def read_dependencies(files):
    """Recover input/output hashes checked while preparing a reused QE model."""
    result = {}
    for name, text in files.items():
        if not name.endswith('.qbox.json'):
            continue
        record = json.loads(text)
        for stage in (record.get('config', {}).get('qe_progress') or {}).values():
            for path_key, hash_key in (('input', 'sha256'), ('output', 'output_sha256')):
                path, digest = stage.get(path_key), stage.get(hash_key)
                if path and digest:
                    result[str(Path(path).absolute())] = digest
    return list(result.items())


def _check_dependencies(dependencies):
    for name, digest in dependencies:
        path = Path(name)
        try:
            unchanged = path.is_file() and _digest(path.read_bytes()) == digest
        except OSError:
            unchanged = False
        if not unchanged:
            raise ValueError(f'复用的 QE 文件发生变化；请重新读取并生成：{path}')


def publish(files, directory, conflict='cancel', expected=None, protected=(), dependencies=None):
    """Publish validated texts; require explicit backup policy for collisions.

    expected is the snapshot shown at preview. With None a fresh snapshot is
    taken. Files outside this bundle are never touched. Return absolute paths.
    """
    if conflict not in ('cancel', 'backup'):
        raise ValueError('冲突策略必须为 cancel 或 backup；改名请重新生成整个文件包。')
    directory = Path(directory).resolve(strict=True)
    dependencies = read_dependencies(files) if dependencies is None else dependencies
    texts = {_name(name): text.encode('utf-8') for name, text in files.items()}
    blocked = {Path(path).resolve() for path in protected} | {Path(path).resolve() for path, _ in dependencies}
    for name in texts:
        if (directory / name).resolve() in blocked:
            raise ValueError(f'不得覆盖来源文件：{name}')
    if not texts:
        return []
    with _lock(directory):
        _check_dependencies(dependencies)
        actual = snapshot(texts, directory)
        if expected is not None and actual != expected:
            raise ValueError('预览后目标文件发生变化；请重新检查输出文件。')
        if conflict == 'cancel' and any(value is not None for value in actual.values()):
            raise FileExistsError('存在同名文件；请选择备份后覆盖、改名或取消。')
        stage = Path(tempfile.mkdtemp(prefix='.qbox-wannier-', dir=directory))
        data = {'schema': 1, 'state': 'prepared', 'entries': []}
        try:
            for index, (name, content) in enumerate(texts.items()):
                entry = {'name': name, 'old': actual[name], 'new_sha256': _digest(content),
                         'staged': f'{index}.new', 'original': f'{index}.old', 'armed': False}
                _write(stage / entry['staged'], content)
                if actual[name]:
                    old_content = (directory / name).read_bytes()
                    if _digest(old_content) != actual[name]['sha256']:
                        raise ValueError(f'暂存期间目标文件变化：{name}')
                    _write(stage / entry['original'], old_content)
                data['entries'].append(entry)
            _journal(stage, data)
            if snapshot(texts, directory) != actual:
                raise ValueError('暂存后目标文件变化；取消发布。')
            data['state'] = 'publishing'
            for entry in data['entries']:
                _check_dependencies(dependencies)
                target = directory / entry['name']
                if _state(target) != entry['old']:
                    raise ValueError(f'发布期间目标文件变化：{target}')
                if entry['old']:
                    entry['backup'] = _backup(target, (stage / entry['original']).read_bytes())
                entry['armed'] = True
                _journal(stage, data)
                if _state(target) != entry['old']:
                    raise ValueError(f'发布前目标文件变化：{target}')
                if entry['old'] is None:
                    # Atomic no-clobber creation, including a late symlink race.
                    os.link(stage / entry['staged'], target)
                    (stage / entry['staged']).unlink()
                else:
                    os.replace(stage / entry['staged'], target)
            _check_dependencies(dependencies)
            data['state'] = 'complete'
            _journal(stage, data)
        except Exception:
            _rollback(stage, data)
            shutil.rmtree(stage)
            raise
        shutil.rmtree(stage)
    return [str(directory / name) for name in texts]


def recover(manifest):
    """Explicitly restore a surviving transaction, refusing unrelated edits."""
    manifest = Path(manifest).absolute()
    stage = manifest.parent
    if (manifest.name != 'transaction.json' or not stage.name.startswith('.qbox-wannier-')
            or stage.is_symlink() or manifest.is_symlink()):
        raise ValueError('不是可恢复的 Wannier 输入事务清单')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or not isinstance(data.get('entries'), list):
        raise ValueError('未知事务格式')
    for index, entry in enumerate(data['entries']):
        _name(entry['name'])
        if entry['original'] != f'{index}.old' or entry['staged'] != f'{index}.new':
            raise ValueError('事务暂存路径无效')
    if data.get('state') == 'complete':
        raise ValueError('事务已成功发布，不作撤销；备份位置见清单 backup 字段，新备份位于 bak/。')
    lock = stage.parent / '.qbox-wannier.lock'
    if lock.exists() or lock.is_symlink():
        state = _state(lock)
        try:
            pid = int(lock.read_text().strip())
            if pid < 1:
                raise ValueError
        except ValueError as exc:
            raise ValueError('发布锁内容异常；请人工核实，不自动移除。') from exc
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            if _state(lock) != state:
                raise ValueError('恢复前发布锁发生变化')
            lock.unlink()
        else:
            raise ValueError(f'发布进程 {pid} 仍在运行，拒绝并发恢复。')
    with _lock(stage.parent):
        _rollback(stage, data)
        shutil.rmtree(stage)
