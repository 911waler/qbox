#!/usr/bin/env python3
"""Real, disposable Docker acceptance; never installs onto the host.

python tests/installer/run-acceptance.py --archive FILE --image IMAGE --output DIR
Images must already contain Python 3.10+, venv/pip, bash, useradd and runuser.
The container downloads its own dependencies; no host Python or packages mount.
Every subprocess has captured stdout/stderr/exit status in commands.jsonl.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tarfile
import time
import traceback
import uuid

CIF = """data_silicon
_cell_length_a 5.43
_cell_length_b 5.43
_cell_length_c 5.43
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0 0 0
Si2 Si 0.25 0.25 0.25
"""


class Recorder:
    def __init__(self, stream):
        self.stream = stream

    def emit(self, event):
        self.stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        self.stream.flush()

    def run(self, argv, *, failure=False, timeout=1200, **kwargs):
        start = time.monotonic()
        try:
            result = subprocess.run(argv, text=True, capture_output=True,
                                    timeout=timeout, **kwargs)
        except subprocess.TimeoutExpired as error:
            self.emit({'type': 'command', 'argv': argv, 'returncode': None,
                       'error': 'timeout', 'seconds': time.monotonic() - start,
                       'stdout': str(error.stdout or ''), 'stderr': str(error.stderr or '')})
            raise
        self.emit({'type': 'command', 'argv': argv, 'returncode': result.returncode,
                   'stdout': result.stdout, 'stderr': result.stderr,
                   'seconds': round(time.monotonic() - start, 3)})
        assert (result.returncode != 0) if failure else (result.returncode == 0), (
            f'Unexpected exit {result.returncode}: {argv}\n{result.stdout}\n{result.stderr}')
        return result


def profile_example(output):
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('( set -C; printf ') and index + 1 < len(lines):
            assert lines[index + 1] == '  chmod 0644 /etc/profile.d/qbox.sh'
            return '\n'.join(lines[index:index + 2])
    raise AssertionError('installer did not print the profile.d example')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside():
    # --inside is deliberately unusable on the production host.
    assert Path('/.dockerenv').exists() and os.environ.get('QBOX_ACCEPTANCE_CONTAINER') == '1'
    assert os.geteuid() == 0
    recorder = Recorder(sys.stdout)
    cases = []
    records = []
    python = sys.executable

    def case(name):
        cases.append(name)
        recorder.emit({'type': 'case', 'name': name, 'status': 'passed'})

    def run_as(user: str, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        home = '/root' if user == 'root' else f'/home/{user}'
        env = ['HOME=' + home, 'USER=' + user, 'LOGNAME=' + user,
               'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'LANG=C.UTF-8', 'QBOX_PYTHON=/obsolete/python', 'PYTHONPATH=/obsolete/packages',
               'MPLBACKEND=Agg', 'PIP_NO_INDEX=1', 'PIP_FIND_LINKS=/wheels']
        return recorder.run(['runuser', '-u', user, '--', 'env', '-i', *env, *argv], **kwargs)

    try:
        recorder.run([python, '--version'])
        recorder.run(['cat', '/etc/os-release'])
        recorder.run(['id'])
        archive = Path('/input/installer.tar.gz')
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            roots = {Path(m.name).parts[0] for m in members}
            assert len(roots) == 1
            assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
            bundle.extractall('/bundle')
        root = Path('/bundle') / roots.pop()
        wheel, = (root / 'packages').glob('*.whl')
        wheel_sha = sha(wheel)
        installer = ['bash', str(root / 'install.sh')]
        recorder.emit({'type': 'identity', 'archive_sha256': sha(archive), 'wheel_sha256': wheel_sha,
                       'python': python, 'python_version': sys.version})
        recorder.run(['useradd', '-m', '-s', '/bin/bash', 'alice'])
        assert recorder.run(['id', '-u', 'alice']).stdout.strip() != '0'
        recorder.run(['id', 'bob'], failure=True)
        recorder.run([python, '-m', 'pip', 'wheel', '--use-pep517', '--wheel-dir', '/wheels', str(wheel) + '[analysis,structure]'])
        recorder.emit({'type': 'dependency_downloads', 'files': {p.name: sha(p) for p in sorted(Path('/wheels').iterdir())}})
        case('genuine network dependency download; alice exists before install; bob absent')

        def install(user, options, prefix, bin_dir=None):
            result = run_as(user, installer + options + ['--python', python])
            prefix = Path(prefix)
            entry = Path(bin_dir or prefix / 'bin') / 'qbox'
            assert entry.is_file()
            record = json.loads((prefix / '.qbox-install.json').read_text())
            assert record['state'] == 'ready' and record['wheel_sha256'] == wheel_sha
            assert record['venv_python'] == str(prefix / 'venv/bin/python')
            if bin_dir:
                assert not (prefix / 'bin/qbox').exists()
            records.append(record)
            recorder.emit({'type': 'installation', 'record': record})
            return str(entry), result.stdout

        def workflow(user, entry, label, shared=False):
            entry = Path(entry)
            record = next(record for record in records if record['bin_dir'] == str(entry.parent))
            installed_python = record['venv_python']
            work = Path(f'/home/{user}/calculation {label}')
            run_as(user, ['mkdir', '-p', str(work)])
            run_as(user, [python, '-c', 'from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])', str(work / 'input with spaces.cif'), CIF])
            assert '--task' in run_as(user, [str(entry), '--help'], cwd=work).stdout
            assert 'cif-to-vasp' in run_as(user, [str(entry), '--list'], cwd=work).stdout
            assert run_as(user, [str(entry), '--version'], cwd=work).stdout.strip() == 'qbox 0.1.0'
            run_as(user, [str(entry), '--task', 'cif-to-vasp', 'input with spaces.cif'], cwd=work)
            converted = work / 'input with spaces.vasp'
            assert converted.stat().st_size and 'Si' in converted.read_text()
            # Exercise a shipped plotting module with the same per-user default
            # cache used by qbox's shell workflow, after real CLI conversion.
            cache = Path(f'/tmp/.qbox-mpl-cache-{pwd.getpwnam(user).pw_uid}')
            assert cache.is_dir()
            plot = "from pathlib import Path; import matplotlib; from qbox.postprocess.convergence_plot import main; Path('energy.dat').write_text('1 -1\\n2 -2\\n3 -3\\n'); main(['energy.dat','energy.dat','convergence']); print(matplotlib.get_cachedir())"
            output = run_as(user, ['env', 'MPLCONFIGDIR=' + str(cache), installed_python, '-I', '-c', plot], cwd=work)
            assert output.stdout.strip() == str(cache)
            assert (work / 'convergence.png').stat().st_size > 1000
            assert (work / 'convergence.svg').stat().st_size > 1000
            uid = pwd.getpwnam(user).pw_uid
            for base in (work, cache):
                assert all(p.stat().st_uid == uid for p in [base, *base.rglob('*')])
            if shared:
                for path in (installed_python, record['prefix'], entry, Path(record['prefix']) / '.qbox-install.json'):
                    run_as(user, ['test', '-w', str(path)], failure=True)
                prefix = Path(record['prefix'])
                assert all(p.lstat().st_uid == 0 and not (p.lstat().st_mode & 0o022)
                           for p in [prefix, *prefix.rglob('*')] if not p.is_symlink())
            recorder.emit({'type': 'workflow', 'user': user, 'entry': str(entry), 'output': str(work),
                           'output_owner': uid, 'cache': str(cache), 'cache_owner': cache.stat().st_uid})
            case(label + ': ' + user + ' clean shell, real conversion/plot, private outputs/cache' + (', shared files read-only' if shared else ''))

        user_variants = [
            ('user-default', ['--user'], '/home/alice/.local/share/qbox', None),
            ('user-prefix', ['--user', '--prefix', '/home/alice/科学 qbox'], '/home/alice/科学 qbox', None),
            ('user-bin', ['--bin-dir', '/home/alice/命令 tools', '--user', '--prefix', '/home/alice/separate qbox'], '/home/alice/separate qbox', '/home/alice/命令 tools'),
        ]
        for label, options, prefix, bin_dir in user_variants:
            entry, output = install('alice', options, prefix, bin_dir)
            path_line = next(line for line in output.splitlines() if line.startswith('export PATH='))
            assert run_as('alice', ['sh', '-lc', path_line + '; command -v qbox']).stdout.strip() == entry
            workflow('alice', entry, label)
        # Actual old-entry and unwritable shared-directory failures.
        conflict = Path('/home/alice/old commands')
        run_as('alice', ['mkdir', str(conflict)])
        run_as('alice', ['sh', '-c', 'printf old-command > "$1"', 'sh', str(conflict / 'qbox')])
        for name in ('qbox', 'qbox-link'):
            if name == 'qbox-link':
                run_as('alice', ['mv', str(conflict / 'qbox'), str(conflict / 'old')])
                run_as('alice', ['ln', '-s', 'old', str(conflict / 'qbox')])
            result = run_as('alice', installer + ['--user', '--prefix', '/home/alice/conflict-' + name,
                                                  '--bin-dir', str(conflict), '--python', python], failure=True)
            assert 'already exists' in result.stderr
            assert (conflict / 'qbox').read_text() == 'old-command'
        result = run_as('alice', installer + ['--user', '--prefix', '/opt/user-forbidden', '--python', python], failure=True)
        assert 'Permission denied' in result.stderr or 'writable' in result.stderr
        run_as('root', installer + ['--user', '--python', python], failure=True)
        run_as('alice', installer + ['--system', '--python', python], failure=True)
        case('existing file/symlink preserved; user shared-directory failure; actual UID guards')

        system_variants = [
            ('system-default', ['--system'], '/opt/qbox', None),
            ('system-prefix', ['--system', '--prefix', '/opt/科学 qbox'], '/opt/科学 qbox', None),
            ('system-bin', ['--bin-dir', '/opt/共享 commands', '--system', '--prefix', '/opt/lab qbox'], '/opt/lab qbox', '/opt/共享 commands'),
        ]
        for label, options, prefix, bin_dir in system_variants:
            entry, output = install('root', options, prefix, bin_dir)
            if label == 'system-default':
                recorder.run(['useradd', '-m', '-s', '/bin/bash', 'bob'])
                assert recorder.run(['id', '-u', 'bob']).stdout.strip() != '0'
            # Execute exactly the administrator example printed by this archive.
            profile = Path('/etc/profile.d/qbox.sh')
            assert not profile.exists()
            recorder.run(['bash', '-c', profile_example(output)])
            for user in ('alice', 'bob'):
                assert run_as(user, ['sh', '-lc', 'command -v qbox']).stdout.strip() == entry
                workflow(user, entry, label, shared=True)
            profile.unlink()  # only the exact profile created by this test
            before = sha(entry)
            reused, _ = install('root', options, prefix, bin_dir)
            assert reused == entry and sha(entry) == before
            case(label + ': printed profile.d existing/new login users and matching reuse')

        for directory, mode in (('/opt/private-parent', 0o700), ('/opt/writable-parent', 0o777)):
            Path(directory).mkdir(mode=mode)
            Path(directory).chmod(mode)  # defeat the container's default umask for the negative fixture
            result = run_as('root', installer + ['--system', '--prefix', directory + '/qbox', '--python', python], failure=True)
            assert 'travers' in result.stderr or 'writ' in result.stderr
            assert not Path(directory + '/qbox').exists()
        Path('/opt/private-python').mkdir(mode=0o700)
        Path('/opt/private-python/python').symlink_to(python)
        result = run_as('root', installer + ['--system', '--prefix', '/opt/rejected-python', '--python', '/opt/private-python/python'], failure=True)
        assert 'travers' in result.stderr
        assert not Path('/opt/rejected-python').exists()
        case('actual inaccessible prefix/interpreter and writable system ancestor rejected')
        default = Path('/usr/bin/python3')
        if default.exists():
            version = recorder.run([str(default), '-c', 'import sys; print(sys.version_info[:2])']).stdout.strip()
            if version in ('(3, 6)', '(3, 9)'):
                result = run_as('root', installer + ['--system', '--prefix', '/opt/old-python'], failure=True)
                assert '3.10' in result.stderr
                assert not Path('/opt/old-python').exists()
                case('actual old default Python rejected before mutation')
        recorder.emit({'type': 'result', 'status': 'passed', 'cases': cases, 'installations': len(records),
                       'archive_sha256': sha(archive), 'wheel_sha256': wheel_sha})
        return 0
    except BaseException as error:
        recorder.emit({'type': 'result', 'status': 'failed', 'cases': cases,
                       'error': str(error), 'traceback': traceback.format_exc()})
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = args.output / 'commands.jsonl'
    # Do not overwrite evidence from a previous run.
    with log_path.open('x', encoding='utf-8') as log:
        recorder = Recorder(log)
        info = {'archive': str(archive), 'archive_sha256': sha(archive), 'archive_size': archive.stat().st_size,
                'image': args.image, 'harness_sha256': sha(__file__), 'status': 'failed'}
        name = 'qbox-acceptance-' + uuid.uuid4().hex[:12]
        try:
            inspected = recorder.run(['docker', 'image', 'inspect', args.image])
            image = json.loads(inspected.stdout)[0]
            info.update(image_id=image['Id'], image_repo_digests=image.get('RepoDigests', []))
            python = recorder.run(['docker', 'run', '--rm', args.image, 'sh', '-c',
                                  'command -v python3.11 || command -v python3']).stdout.strip()
            command = ['docker', 'run', '--rm', '--name', name,
                       '-e', 'QBOX_ACCEPTANCE_CONTAINER=1',
                       '--mount', f'type=bind,source={archive},target=/input/installer.tar.gz,readonly',
                       '--mount', f'type=bind,source={Path(__file__).resolve()},target=/run-acceptance.py,readonly',
                       args.image, python, '/run-acceptance.py', '--inside']
            process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Container events are streamed to disk so interruption retains evidence.
            assert process.stdout is not None
            results = []
            for line in process.stdout:
                log.write(line)
                log.flush()
                event = json.loads(line)
                if event['type'] == 'case':
                    print(event['name'], flush=True)
                if event['type'] == 'result':
                    results.append(event)
            stderr = process.communicate()[1]
            recorder.emit({'type': 'container_exit', 'argv': command, 'returncode': process.returncode, 'stderr': stderr})
            assert process.returncode == 0 and len(results) == 1 and results[0]['status'] == 'passed', str(results)
            info.update(status='passed', result=results[0])
        except BaseException as error:
            info['error'] = str(error)
            # Stop only our uniquely named disposable container on failures.
            result = subprocess.run(['docker', 'rm', '-f', name], text=True, capture_output=True)
            recorder.emit({'type': 'cleanup', 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        (args.output / 'result.json').write_text(json.dumps(info, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0 if info['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(inside() if sys.argv[1:] == ['--inside'] else main())
