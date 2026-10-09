#!/usr/bin/env python3
"""Reproduce small official W90 3.1.0 interface checks, without running QE.

Download/extract the upstream v3.1.0 source yourself. Build its w90chk2chk
utility for portable checkpoint conversion. All calculations run in a fresh
output directory; upstream data is read only. See docs/wannier-validation.md.
"""
import argparse
import bz2
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from qbox.io.wannier_inputs import build_bundle
from qbox.io.wannier_profiles import PROFILE_KEYS, TASKS, render_profile

PARAMS = dict(fermi_energy=4.2, kpoint_path=['G 0 0 0 X .5 0 0'],
              dos_energy_min=-5, dos_energy_max=8, dos_project=[1, 2],
              wannier_plot_list=[1], wannier_plot_supercell=[1, 1, 1],
              boltz_mu_min=4, boltz_mu_max=4, boltz_temp_min=300,
              boltz_temp_max=300, boltz_relax_time=10, boltz_tdf_energy_step=.1,
              kubo_freq_max=.1, kubo_freq_step=.05, kubo_eigval_max=12,
              gyrotropic_freq_max=.1, gyrotropic_freq_step=.05,
              kslice_corner=[0, 0, 0], kslice_b1=[1, 0, 0], kslice_b2=[0, 1, 0],
              dos_kmesh=[2, 2, 2], boltz_kmesh=[2, 2, 2], berry_kmesh=[2, 2, 2],
              gyrotropic_kmesh=[2, 2, 2], kslice_2dkmesh=[2, 2],
              kpath_num_points=3, bands_num_points=3, fermi_surface_num_points=3,
              dos_energy_step=1)
SCF = '''&CONTROL calculation='scf', prefix='validation' /
&SYSTEM ibrav=0, nat=2, ntyp=2, nbnd=12, ecutwfc=40 /
&ELECTRONS conv_thr=1d-8 /
CELL_PARAMETERS angstrom
3 0 0
0 3 0
0 0 3
ATOMIC_SPECIES
Fe1 55.8 Fe.upf
Fe2 55.8 Fe.upf
ATOMIC_POSITIONS crystal
Fe1 0 0 0
Fe2 .5 .5 .5
K_POINTS automatic
2 2 2 0 0 0
'''
FIXTURES = {
    'dos': ('example04_dos', 'copper'), 'projected_dos': ('example04_pdos', 'copper'),
    'boltzmann': ('boltzwann', 'silicon'), 'berry_path': ('fe_kpathcurv', 'Fe'),
    'berry_slice': ('fe_kslicecurv', 'Fe'), 'ahc': ('fe_ahc', 'Fe'),
    'shc': ('pt_shc', 'Pt'), 'optical': ('fe_kubo_Szz', 'Fe'),
    'shift_current': ('gaas_sc_xyz', 'gaas'),
    'orbital_magnetization': ('fe_morb', 'Fe'),
    'natural_optical_activity': ('te_gyrotropic_NOA', 'Te'),
    'current_induced_optical': ('te_gyrotropic_Dw', 'Te'),
    'current_induced_magnetization': ('te_gyrotropic_K', 'Te'),
}


def run(binary, args, directory, log):
    env = {**os.environ, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
    proc = subprocess.run([str(binary), *args], cwd=directory, env=env,
                          text=True, capture_output=True, timeout=90)
    (directory / log).write_text(proc.stdout + proc.stderr)
    return proc.returncode


def copy_fixture(source, target, seed):
    target.mkdir()
    for file in source.iterdir():
        if file.is_file() and file.name.startswith((seed + '.', 'UNK')):
            if file.suffix == '.bz2':
                (target / file.stem).write_bytes(bz2.decompress(file.read_bytes()))
            else:
                shutil.copyfile(file, target / file.name)


def fixture_basis(text):
    """Remove fixture response settings, retaining its exact model and formats."""
    text = re.sub(r'(?ims)^\s*begin\s+kpoint_path.*?^\s*end\s+kpoint_path[^\n]*', '', text)
    result = []
    for line in text.splitlines():
        match = re.match(r'\s*(\w+)\s*(?:=|:|\s)', line)
        key = match[1].lower() if match else ''
        if key in PROFILE_KEYS or key.startswith(('berry', 'boltz', 'gyrotropic', 'kubo',
                'kpath', 'kslice', 'dos_', 'fermi_energy', 'sc_')) or key in ('spin_moment', 'kmesh'):
            continue
        result.append(line)
    return '\n'.join(result) + '\n'


def completed(directory, seed, suffix):
    file = directory / (seed + suffix)
    return file.is_file() and 'All done:' in file.read_text() and not (directory / (seed + '.werr')).exists()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, help='official extracted wannier90-3.1.0 source tree')
    parser.add_argument('--wannier90', default='wannier90.x')
    parser.add_argument('--postw90', default='postw90.x')
    parser.add_argument('--chk2chk', type=Path, help='official w90chk2chk.x (default: DATA_ROOT/w90chk2chk.x)')
    parser.add_argument('--output-dir', type=Path, help='new directory (must not already exist)')
    args = parser.parse_args()
    if args.output_dir:
        out = args.output_dir.absolute(); out.mkdir(parents=True, exist_ok=False)
    else:
        out = Path(tempfile.mkdtemp(prefix='qbox-wannier-native-'))
    report = {'output_dir': str(out), 'preprocessing': {}, 'postprocessing': {}, 'local_outputs': {}}
    pre = out / 'preprocessing'; pre.mkdir()
    for task in TASKS:
        spinor = task == 'shc'
        source = SCF.replace('ibrav=0', 'noncolin=.true., ibrav=0') if spinor else SCF
        config = dict(seed=task, tasks=[task], parameters=PARAMS, grid=[2, 2, 2],
                      nbnd=12, num_wann=4 if spinor else 2, projections=['Fe1:s', 'Fe2:s'])
        bundle = build_bundle(source, config, run_root=pre, output_dir=pre)
        (pre / (task + '.win')).write_text(bundle[task + '.win'])
        code = run(args.wannier90, ['-pp', task], pre, task + '.log')
        ok = code == 0 and (pre / (task + '.nnkp')).exists() and not (pre / (task + '.werr')).exists()
        report['preprocessing'][task] = ok
    if args.data_root:
        root = args.data_root.absolute()
        converter = args.chk2chk or root / 'w90chk2chk.x'
        for task, (fixture, seed) in FIXTURES.items():
            dst = out / task
            copy_fixture(root / 'test-suite/tests' / ('testpostw90_' + fixture), dst, seed)
            file = dst / (seed + '.win'); old = file.read_text()
            mode = 'spinor' if re.search(r'spinors\s*[:=]\s*\.?true', old, re.I) else 'scalar'
            profile = render_profile([task], PARAMS, mode)
            file.write_text(fixture_basis(old) + '\n'.join(profile.win_lines) + '\n')
            run(converter, ['-f2u', seed], dst, 'checkpoint-conversion.log')
            code = run(args.postw90, [seed], dst, 'postw90.log')
            report['postprocessing'][task] = code == 0 and completed(dst, seed, '.wpout')
        for fmt in ('cube', 'xsf'):
            dst = out / ('orbitals-' + fmt)
            copy_fixture(root / 'test-suite/tests/testw90_cube_format', dst, 'gaas')
            file = dst / 'gaas.win'
            profile = render_profile(['orbitals', 'centres'], {**PARAMS, 'wannier_plot_format': fmt}, 'scalar')
            file.write_text(fixture_basis(file.read_text()) + '\n'.join(profile.win_lines) + '\n')
            code = run(args.wannier90, ['gaas'], dst, 'wannier90.log')
            report['local_outputs']['orbitals-' + fmt] = code == 0 and completed(dst, 'gaas', '.wout') and (dst / ('gaas_00001.' + fmt)).exists() and (dst / 'gaas_centres.xyz').exists()
        # Use a matching Te checkpoint/eigenvalue set for model/bands/Fermi output.
        dst = out / 'model-bands-fermi'
        copy_fixture(root / 'test-suite/tests/testpostw90_te_gyrotropic_NOA', dst, 'Te')
        file = dst / 'Te.win'
        profile = render_profile(['model', 'bands', 'fermi_surface'], PARAMS, 'scalar')
        file.write_text(fixture_basis(file.read_text()) + 'restart = plot\n' + '\n'.join(profile.win_lines) + '\n')
        run(converter, ['-f2u', 'Te'], dst, 'checkpoint-conversion.log')
        code = run(args.wannier90, ['Te'], dst, 'wannier90.log')
        report['local_outputs']['model-bands-fermi'] = code == 0 and completed(dst, 'Te', '.wout') and all((dst / name).exists() for name in ('Te_hr.dat', 'Te_band.kpt', 'Te.bxsf'))
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if all(value for section in ('preprocessing', 'postprocessing', 'local_outputs') for value in report[section].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
