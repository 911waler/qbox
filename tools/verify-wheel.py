#!/usr/bin/env python3
"""Install a local wheel in a temporary target and exercise it away from source.

Usage: python tools/verify-wheel.py dist/qbox-0.1.0-py3-none-any.whl
Requires pip plus the analysis dependencies in this Python; never runs QE/MPI.
"""

import json
import os
import re
from email.parser import BytesParser
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


CIF = """data_Si
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0 0 0
"""


def verify(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata = next(name for name in names if name.endswith(".dist-info/METADATA"))
        version = BytesParser().parsebytes(archive.read(metadata))["Version"]
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        for resource in ("qbox/registry.py", "qbox/legacy/load.sh",
                         "qbox/legacy/entry.sh", "qbox/bin/qbox",
                         "qbox/bin/qbox-dopant-pdos.py",
                         "qbox/postprocess/effective_mass_vasp.py",
                         "qbox/io/kmesh.py", "qbox/io/wannier_menu.py",
                         "qbox/io/wannier_profiles.py", "qbox/io/wannier_inputs.py",
                         "qbox/io/wannier_workflow.py", "qbox/io/wannier_publish.py",
                         "qbox/legacy/wannier.sh",
                         "qbox/io/phonon_inputs.py", "qbox/io/phonon_menu.py",
                         "qbox/io/phonon_paths.py", "qbox/io/qe_lattice.py",
                         "qbox/io/phonon_workflow.py",
                         "qbox/postprocess/phonon_plot.py",
                         "qbox/postprocess/phonon_plot_data.py",
                         "qbox/legacy/input_phonon.sh",
                         "qbox/legacy/phonon_workflows.sh"):
            assert resource in names, f"Missing wheel resource: {resource}"
        licenses = [name for name in names if name.endswith("/LICENSE")]
        assert licenses and b"MIT License" in archive.read(licenses[0])
        assert archive.getinfo("qbox/bin/qbox").external_attr >> 16 & 0o111

    with tempfile.TemporaryDirectory(prefix="qbox wheel smoke ") as directory:
        base = Path(directory)
        target = base / "installed package"
        work = base / "calculation directory"
        work.mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("QBOX_", "BASH_FUNC_")) and key != "PYTHONPATH"}
        env.update(PYTHONPATH=str(target), PYTHONNOUSERSITE="1",
                   QBOX_PYTHON=sys.executable, MPLBACKEND="Agg")

        def run(*command, input="", expected=0):
            result = subprocess.run(command, cwd=work, env=env, input=input,
                                    text=True, capture_output=True, timeout=60)
            assert result.returncode == expected, (
                f"{command}: expected {expected}, got {result.returncode}\n"
                f"{result.stdout}\n{result.stderr}"
            )
            return result.stdout

        run(sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
            "--target", str(target), str(wheel))
        origin = run(sys.executable, "-c", "import qbox; print(qbox.__file__)").strip()
        assert Path(origin).is_relative_to(target), f"Source checkout leaked into test: {origin}"
        installed_cli = str(target / "bin/qbox")
        assert "--task" in run(installed_cli, "--help")
        assert "cif-to-vasp" in run(installed_cli, "--list")
        assert any(line.split()[1:2] == ["phonons"]
                   for line in run(installed_cli, "--list").splitlines())
        assert run(installed_cli, "--version").strip() == f"qbox {version}"
        run(installed_cli, "--task", "unknown-task", expected=2)
        package_cli = str(target / "qbox/bin/qbox")
        assert run(package_cli, "--version").strip() == f"qbox {version}"
        assert "请输入功能编号" in run(installed_cli, input="", expected=1)

        assert "wannier-input" in run(installed_cli, "--list")
        assert len(run(installed_cli, "kmesh", "1", "2", "1", "--format", "wannier").splitlines()) == 2
        (work / "source.scf.in").write_text("""&CONTROL calculation='scf', prefix='si' /
&SYSTEM ibrav=0, nat=1, ntyp=1, nbnd=4, ecutwfc=40 /
&ELECTRONS /
CELL_PARAMETERS angstrom
4 0 0
0 4 0
0 0 4
ATOMIC_SPECIES
Si 28 Si.upf
ATOMIC_POSITIONS crystal
Si 0 0 0
K_POINTS automatic
2 2 2 0 0 0
""")
        (work / "wannier settings.json").write_text(json.dumps({
            "source": "source.scf.in", "seed": "si", "mode": "new", "version": "3.1.0",
            "grid": [2, 1, 1], "nbnd": 4, "num_wann": 1, "projections": ["Si:s"],
            "tasks": ["model"], "parameters": {}}))
        run(installed_cli, "--task", "wannier-input", "--config", "wannier settings.json", "--conflict", "cancel")
        assert re.search(r"(?m)^\s*write_hr\s*=\s*true\s*$", (work / "si.win").read_text())
        assert (work / "si.nscf.in").is_file()
        assert not (work / "WANNIER").exists()

        (work / "sample.cif").write_text(CIF)
        run(installed_cli, "--task", "cif-to-vasp", "sample.cif")
        assert (work / "sample.vasp").stat().st_size > 0
        run(installed_cli, "38", "sample.vasp")
        assert "_cell_length_a" in (work / "sample.cif").read_text()
        run(sys.executable, "-m", "qbox.io.convert_basic", "cif2vasp", "sample.cif", "basic.vasp")
        assert "Si" in (work / "basic.vasp").read_text()
        (work / "36").write_text(CIF)
        run(installed_cli, "--task", "37", "36", input="missing-input\n")
        assert (work / "36.vasp").stat().st_size > 0
        run(sys.executable, str(target / "qbox/bin/qbox-dopant-pdos.py"), "--help")
        run("bash", "-c", 'source "$1" || exit; qe_write_builtin_calc_em_vasp_script "$2"',
            "wheel-test", str(target / "qbox/legacy/load.sh"), str(work / "effective-mass.py"))
        run(sys.executable, str(work / "effective-mass.py"), "--help")
    print("PASS: wheel license/resources, isolated install, entrypoints, task dispatch, Wannier inputs, structure conversion and standalone analysis")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify-wheel.py PATH_TO_WHEEL")
    verify(Path(sys.argv[1]).resolve(strict=True))
