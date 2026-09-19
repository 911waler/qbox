# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox is a command-line toolkit for preparing, running, and post-processing
Quantum ESPRESSO workflows. It supports common SCF, relaxation, NSCF, band,
PDOS, phonon, molecular-dynamics, and convergence-scan tasks.

## Requirements

- Bash 4 or newer
- Quantum ESPRESSO for calculation workflows
- Python 3.10 or newer for the entry point; scientific Python packages for analysis
- Multiwfn for workflows that use Multiwfn analysis

## Installation

Run `./qbox` directly from a complete checkout, or install the package into a
Python environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[analysis,structure]'
qbox --help
```

`pip install .` installs the lightweight entry point without scientific extras.
The `analysis` extra provides NumPy, Matplotlib, SciPy and seekpath; `structure`
provides pymatgen and ASE. QE, MPI, Multiwfn and pseudopotentials remain external.
Use a Python environment you control; do not install into a shared system Python.

For offline distribution, build a wheel with `python -m pip wheel --no-deps . -w dist`
and install that local wheel in the target environment. The wheel includes the
Python modules, Bash workflow resources, compatibility launchers and MIT license;
dependencies must already be available or installed separately. Copying only the
root `qbox` script no longer constitutes a complete installation.

## Configuration

qbox discovers standard command-line tools from `PATH`. Set configuration
variables only when your installation needs explicit locations:

```bash
export QBOX_SHARED_ROOT=/path/to/shared-dependencies
export QBOX_PYTHON=/path/to/python3
export QBOX_MULTIWFN_HOME=/path/to/multiwfn
export QBOX_PSEUDO_ROOT=/path/to/pseudopotentials
export QBOX_QE_ENV_SCRIPT=/path/to/qe-environment.sh
export QBOX_ONEAPI_ENV_SCRIPT=/path/to/compiler-mpi-environment.sh
```

`QBOX_QE_ENV_SCRIPT` and `QBOX_ONEAPI_ENV_SCRIPT` are optional. qbox loads an
environment script only when you set its variable.

When `QBOX_PYTHON` or `QBOX_MULTIWFN_HOME` is not set, `QBOX_SHARED_ROOT`
derives them from `python/bin/python3` and `multiwfn` below the shared root.
Explicit per-dependency settings always take precedence.

## Usage

Show the available command-line options:

```bash
./qbox --help
```

Start the interactive workflow menu:

```bash
./qbox
```

Run an available workflow action directly:

```bash
./qbox ACTION [INPUT ...]
```

Use `./qbox --version` to display the release version.

Discover all task IDs and readable names, or select a task explicitly:

```bash
./qbox --list
./qbox --task scf sample.cif
./qbox --task 11 sample.cif
```

Task IDs 0–37, interactive menus, legacy argument positions and PW presets
(such as `./qbox sample.cif 00`) are preserved. `--task` removes ambiguity between
a numeric filename and a task ID; the remaining arguments are input paths, not
legacy selectors. Tasks may still ask for workflow-specific choices. The module
entry `python -m qbox` is also available after installation.

## Module layout and development

- `qbox`: source-tree launcher with Bash `source` compatibility.
- `src/qbox/cli.py`, `registry.py`: entry options and the shared task catalog.
- `src/qbox/io/`: structure conversion, QE input parsing/preparation and validation.
- `src/qbox/postprocess/`: bands, DOS, optics, effective mass and unfolding algorithms.
- `src/qbox/legacy/`: domain-separated Bash workflow adapters, including the
  established QE/MPI runner, transactions and interactive prompts.

The Python algorithms are importable and expose `main(argv=None)` entry points.
This is a staged migration: calculation orchestration still uses Bash, rather than
claiming a complete Python rewrite. New scientific code should live in Python
modules, not heredocs in the launcher. See [module boundaries](docs/architecture.md).

Run the regression suite with a scientific Python environment:

```bash
QBOX_PYTHON=/path/to/python3 bash tests/run.sh
```

Tests cover file outputs, menus, dispatch, failure propagation, cleanup and Python
module behavior using fixtures; they do not launch production QE calculations.
After building a wheel, run `python tools/verify-wheel.py dist/qbox-0.1.0-py3-none-any.whl`
with the analysis dependencies available to check an isolated local installation.

## Citation

If qbox supports your work, please cite the software using
[`CITATION.cff`](CITATION.cff).

Maintained by waler.

## License

qbox is released under the MIT License. See [`LICENSE`](LICENSE).
