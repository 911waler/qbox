#!/usr/bin/env python3
"""Exercise the public phonon workflow with real QE, including safe resumption.

Load a supported QE/MPI environment first, then run with a Si PBE NC UPF:
  python tools/verify-phonon-native.py --pseudo /path/to/Si.UPF
Add --from-cif to exercise the real Multiwfn/SCF wizard in a long project path.

The small cutoffs/meshes verify orchestration, not converged material properties.
No previous .save, dynamical matrix, force constant or frequency data are reused.
All inputs, terminal transcripts and results remain in a new temporary directory.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import tempfile
import time


SCF = """&CONTROL
 calculation='scf', prefix='phonon_smoke', outdir='./external scratch',
 pseudo_dir='./pseudos'
/
&SYSTEM
 ibrav=2, celldm(1)=10.26, nat=2, ntyp=1,
 ecutwfc=15, ecutrho=60, occupations='fixed'
/
&ELECTRONS
 conv_thr=1d-8
/
ATOMIC_SPECIES
 Si 28.0855 Si.UPF
ATOMIC_POSITIONS alat
 Si 0.0 0.0 0.0
 Si 0.25 0.25 0.25
K_POINTS automatic
 2 2 2 0 0 0
"""

CIF = """data_silicon
_cell_length_a 3.8393867
_cell_length_b 3.8393867
_cell_length_c 3.8393867
_cell_angle_alpha 60
_cell_angle_beta 60
_cell_angle_gamma 60
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_terminal(command, directory, environment, steps, transcript):
    """Answer prompts through a terminal, as a user does (no stdin read-ahead)."""
    master, slave = pty.openpty()
    child = subprocess.Popen(command, cwd=directory, env=environment, stdin=slave,
                             stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    pending, buffer = list(steps), ''
    deadline = time.monotonic() + 600
    try:
        with transcript.open('wb') as output:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(f'Workflow timed out; next prompt: {pending[:1]}; {transcript}')
                ready, _, _ = select.select([master], [], [], .2)
                if not ready:
                    if child.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output.write(chunk)
                output.flush()
                buffer += chunk.decode('utf-8', errors='replace')
                if pending and pending[0][0] in buffer:
                    prompt, answer = pending.pop(0)
                    buffer = buffer.split(prompt, 1)[1]
                    os.write(master, (answer + '\n').encode())
        status = child.wait(timeout=5)
        assert status == 0, f'Workflow failed ({status}): {transcript}'
        assert not pending, f'Unanswered prompts: {pending}; {transcript}'
    finally:
        os.close(master)
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)


def verify(qbox, pseudo, *, from_cif=False):
    work = Path(tempfile.mkdtemp(prefix='qbox phonon native '))
    if from_cif:
        # Reproduce nested workflow paths beyond Multiwfn's 200-character limit.
        work = work / ('long calculation ' + 'p' * 55)
        work.mkdir()
    print(f'Native verification directory: {work}', flush=True)
    (work / 'pseudos').mkdir()
    shutil.copyfile(pseudo, work / 'pseudos/Si.UPF')
    source = work / ('phonon_smoke.cif' if from_cif else 'silicon source.scf.in')
    source.write_text(CIF if from_cif else SCF)
    original = digest(source)
    environment = os.environ.copy()
    for key in ('QBOX_TEST_MODE', 'QE_DIRECT_ACTION', 'QBOX_TASK_ID'):
        environment.pop(key, None)
    environment.update(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    environment.setdefault('I_MPI_FABRICS', 'shm')
    wizard_steps = []
    if from_cif:
        library = work / 'pseudos/QE/SSSP'
        library.mkdir(parents=True)
        shutil.copyfile(pseudo, library / 'Si.UPF')
        environment.update(QBOX_PSEUDO_ROOT=str(work / 'pseudos'),
                           PWIN_DEFAULT_PSEUDOLIB='SSSP')
        wizard_steps = [
            ('14) 返回', '8'), ('布里渊区会进行Gamma点的单点计算', '2,2,2'),
            ('14) 返回', '11'), ('4) 返回', '1'), ('请输入 ecutwfc，', '15'),
            ('4) 返回', '2'), ('请输入 ecutrho，', '60'), ('4) 返回', '4'),
            ('14) 返回', '0'),
        ]

    def run(name, steps):
        transcript = work / f'{name}.log'
        run_terminal([str(qbox), '--task', 'phonons', str(source)], work,
                     environment, steps, transcript)
        assert digest(source) == original, 'The source input was modified'
        assert not (work / 'external scratch').exists(), 'SCF wrote into source scratch'
        return transcript

    # Dispersion submenu; nonpolar solid; advanced q-grid, threshold, path count;
    # generate; one MPI rank for SCF and PH. No input is repaired during execution.
    run('fresh', [('2) 返回', '1'), *wizard_steps, ('选择体系：', '3'), ('选择操作：', '1'),
                  ('选择参数：', '1'), ('（回车保留，b 返回）：', '2 2 2'),
                  ('选择参数：', '2'), ('（回车保留，b 返回）：', '1d-10'),
                  ('选择参数：', '6'), ('（回车保留，b 返回）：', '5'),
                  ('选择参数：', '0'), ('选择操作：', '0'),
                  ('请输入 SCF pw.x 使用的 MPI 进程数。', '1'),
                  ('请输入 ph.x 使用的 MPI 进程数。', '1')])
    directory = work / 'PHONON'
    for name in ('scf.out', 'ph.out', 'q2r.out', 'matdyn.out'):
        assert 'JOB DONE' in (directory / name).read_text(), f'Missing completion: {name}'
    assert (directory / 'phonon_smoke.freq.gp').stat().st_size > 0
    assert (directory / 'phonon_smoke_phonon.png').read_bytes().startswith(b'\x89PNG')
    assert '<svg' in (directory / 'phonon_smoke_phonon.svg').read_text()
    assert {path.name for path in work.iterdir()} == {
        'pseudos', source.name, 'fresh.log', 'PHONON'}, 'Workflow polluted project root'
    unchanged = ('scf.out', 'ph.out', 'q2r.out', 'matdyn.out', 'phonon_smoke.freq.gp')
    times = {name: (directory / name).stat().st_mtime_ns for name in unchanged}
    reuse = [('2) 返回', '1'), ('2) 返回：', '0'), ('是，全部重新计算', '1')]
    run('resume', reuse)
    assert all((directory / name).stat().st_mtime_ns == value for name, value in times.items()), \
        'Unchanged completed stages were rerun'

    # A harmless input edit must invalidate its stage and all downstream stages.
    q2r = directory / 'phonon_smoke.q2r.in'
    q2r.write_text(q2r.read_text() + '\n! Native acceptance: changed input\n')
    run('edited-input', reuse)
    for name in ('scf.out', 'ph.out'):
        assert (directory / name).stat().st_mtime_ns == times[name], f'Unexpected rerun: {name}'
    for name in ('q2r.out', 'matdyn.out', 'phonon_smoke.freq.gp'):
        assert (directory / name).stat().st_mtime_ns != times[name], f'Stale result reused: {name}'
    print('PASS: fresh SCF -> PH -> Q2R -> MATDYN -> plot; resume; input invalidation.', flush=True)
    print(f'Inputs, plots and transcripts: {work}', flush=True)
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pseudo', required=True, type=Path, help='Si PBE NC pseudopotential')
    parser.add_argument('--qbox', type=Path, default=Path(__file__).resolve().parents[1] / 'qbox')
    parser.add_argument('--from-cif', action='store_true',
                        help='start with CIF only; requires real Multiwfn as well as QE')
    args = parser.parse_args()
    if not args.pseudo.is_file() or not args.qbox.is_file():
        parser.error('--pseudo and --qbox must name existing files')
    verify(args.qbox.resolve(), args.pseudo.resolve(), from_cif=args.from_cif)


if __name__ == '__main__':
    main()
