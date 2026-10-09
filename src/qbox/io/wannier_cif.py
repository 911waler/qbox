"""Interactive CIF-to-SCF handoff for the Wannier input menu.

The existing pw.x input wizard runs in a private directory, with its terminal
streams inherited. Only its validated SCF input is published, without replacing
any existing filesystem entry. No QE or Wannier calculation is started here.
"""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from .wannier_inputs import parse_qe


_WIZARD = r'''
source "$1" || exit $?
qe_install_cleanup_traps
fname1="$2"
qbox_cif_result="$3"
PRESET_RTASK=energy
RETURN_TO_EXEC_CALC=1
unset NONINTERACTIVE_PWIN QBOX_INPUT_MENU_TIMEOUT pwin_arg QE_TASK_OUTPUT
pwin
qbox_cif_status=$?
if [ "$qbox_cif_status" -ne 0 ]; then
    if [ "${pwin_arg:-}" = 14 ]; then
        printf 'cancel\n' > "$qbox_cif_result"
        exit 0
    fi
    exit "$qbox_cif_status"
fi
[ "${QE_TASK_CALCULATION:-}" = scf ] && [ -n "${QE_TASK_OUTPUT:-}" ] || exit 1
printf 'ok\n%s\n' "$PWD/$QE_TASK_OUTPUT" > "$qbox_cif_result"
'''


def _regular(path):
    """Reject links and non-regular results before interpreting their contents."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        raise ValueError(f'SCF 向导输出不是非空普通文件：{path.name}')


def _runtime_environment():
    """Preserve caller-relative tools before entering a private directory."""
    environment = os.environ.copy()
    environment['QBOX_PYTHON'] = environment.get('QBOX_PYTHON') or sys.executable
    for key in ('QBOX_SHARED_ROOT', 'QBOX_MULTIWFN_HOME', 'QBOX_PSEUDO_ROOT'):
        if environment.get(key):
            environment[key] = str(Path(environment[key]).expanduser().resolve())
    if '/' in environment['QBOX_PYTHON']:
        # Resolving the executable symlink would discard a virtual environment.
        environment['QBOX_PYTHON'] = os.path.abspath(os.path.expanduser(environment['QBOX_PYTHON']))
    if 'PATH' in environment:
        environment['PATH'] = os.pathsep.join(os.path.abspath(part or '.')
                                              for part in environment['PATH'].split(os.pathsep))
    for key in ('NONINTERACTIVE_PWIN', 'QBOX_INPUT_MENU_TIMEOUT'):
        environment.pop(key, None)
    return environment


def _child_environment(input_fn, output):
    """Configure missing pseudos only when a new SCF input is needed."""
    environment = _runtime_environment()
    if not environment.get('QBOX_PSEUDO_ROOT'):
        output('尚未配置赝势总目录 QBOX_PSEUDO_ROOT。请输入包含 QE/SSSP、'
               'QE/NCPP-PD04-PBE 或 PWmat/NCPP-SG15-PBE 的已有目录。')
        output('相对路径按调用时的当前目录解析；此次选择仅用于本次 SCF 向导。')
        while True:
            try:
                answer = input_fn('赝势总目录（回车或 b 取消）：').strip()
            except EOFError:
                return None
            if answer in ('', 'b'):
                return None
            try:
                candidate = Path(answer).expanduser().resolve()
                valid = candidate.is_dir() and any((candidate / subdir).is_dir() for subdir in
                            ('QE/SSSP', 'QE/NCPP-PD04-PBE', 'PWmat/NCPP-SG15-PBE'))
            except (OSError, RuntimeError, ValueError):
                valid = False
            if valid:
                environment['QBOX_PSEUDO_ROOT'] = str(candidate)
                break
            output('目录无效：须为已有赝势总目录，并包含上述至少一个库子目录，请重新输入。')
    return environment


def _validate_published_paths(qe, directory, stage):
    """The published input must survive removal of its private staging tree."""
    for key in ('pseudo_dir', 'outdir', 'wfcdir'):
        raw = qe.get('control', key)
        if raw is None:
            if key == 'pseudo_dir':
                raise ValueError('SCF 输入缺少赝势目录 pseudo_dir。')
            continue
        path = (directory / Path(raw).expanduser()).resolve()
        if path == stage or stage in path.parents:
            raise ValueError(f'SCF 输入的 {key} 引用了将被清理的暂存目录。')
        if key == 'pseudo_dir':
            pseudo_dir = path
    start, end, _ = qe.cards['ATOMIC_SPECIES']
    for row in qe.text[start:end].splitlines()[1:]:
        columns = row.split('!', 1)[0].split()
        if not columns:
            continue
        pseudo = pseudo_dir / columns[2]
        if not pseudo.is_file() or not os.access(pseudo, os.R_OK):
            raise ValueError(f'缺少或无法读取 {columns[0]} 的赝势文件：{pseudo}；'
                             '请检查赝势总目录及向导中选择的赝势库。')


def _publish(staged, directory, name, input_fn, output):
    while True:
        target = directory / name
        try:
            # Same-filesystem hard-link creation is atomic and cannot clobber a
            # regular file, directory, dangling link, or late competing writer.
            os.link(staged, target, follow_symlinks=False)
        except FileExistsError:
            output(f'已有同名文件，未覆盖：{target}')
            try:
                answer = input_fn('请输入新的 SCF 文件名（例如 model-new.scf.in；回车或 b 取消）：').strip()
            except EOFError:
                return None
            if answer in ('', 'b'):
                return None
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.scf\.in', answer)
                    or '..' in answer):
                output('文件名须以 .scf.in 结尾，只含字母、数字、下划线、连字符或单个点，不含路径。')
                continue
            name = answer
        else:
            output(f'已生成 SCF 输入：{target}')
            return target


def generate_scf_from_cif(source, output_dir=None, input_fn=input, output=print):
    """Run the SCF input wizard and return its published absolute path.

    Return ``None`` for an explicit wizard cancellation or a cancelled filename
    collision. Generation failures raise ``ValueError`` or ``OSError``. The
    parent working directory and original CIF are never changed. ``input_fn``
    handles pseudopotential setup and publication conflicts; the legacy wizard
    uses the real terminal.
    """
    source = Path(source).expanduser()
    if source.suffix.lower() != '.cif':
        raise ValueError('结构来源必须是 CIF 文件。')
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError('结构来源必须是普通 CIF 文件。')
    directory = Path(output_dir or Path.cwd()).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError('SCF 输出位置必须是已有目录。')
    prefix = re.sub(r'[^A-Za-z0-9_-]', '_', source.stem).strip('_')[:180] or 'structure'
    loader = Path(__file__).resolve().parents[1] / 'legacy' / 'load.sh'
    environment = _child_environment(input_fn, output)
    if environment is None:
        output('已取消 SCF 输入生成，未写入新的输入文件。')
        return None
    with tempfile.TemporaryDirectory(prefix='.qbox-wannier-scf-', dir=directory) as temporary:
        stage = Path(temporary)
        staged_cif = stage / (prefix + '.cif')
        shutil.copyfile(source, staged_cif)
        result_path = stage / 'wizard-result.txt'
        result = subprocess.run(['bash', '-c', _WIZARD, 'qbox-cif-scf', str(loader),
                                 str(staged_cif), str(result_path)],
                                cwd=stage, env=environment, check=False)
        if result.returncode != 0:
            raise ValueError(f'CIF → SCF 输入生成失败（退出码 {result.returncode}）；未发布 SCF 输入，请查看向导错误。')
        _regular(result_path)
        record = result_path.read_text(encoding='utf-8').splitlines()
        if record == ['cancel']:
            output('已取消 SCF 输入生成，未写入新的输入文件。')
            return None
        if len(record) != 2 or record[0] != 'ok':
            raise ValueError('SCF 向导未返回唯一的输出文件。')
        staged_output = Path(record[1])
        if not staged_output.is_absolute() or staged_output.parent != stage or staged_output.suffix != '.in':
            raise ValueError('SCF 向导返回了暂存目录之外或无效的输出文件。')
        _regular(staged_output)
        qe = parse_qe(staged_output.read_text(encoding='utf-8'))
        if str(qe.get('control', 'calculation', '')).lower() != 'scf':
            raise ValueError('CIF 向导必须生成 calculation=scf 的 QE 输入。')
        _validate_published_paths(qe, directory, stage)
        return _publish(staged_output, directory, prefix + '.scf.in', input_fn, output)
