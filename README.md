# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox is a command-line toolkit for preparing, running, and post-processing
Quantum ESPRESSO workflows. It supports common SCF, relaxation, NSCF, band,
PDOS, phonon, molecular-dynamics, and convergence-scan tasks.

## Installation (recommended)

The default distribution is a lightweight wheel. Supply your own Python 3.10+
and scientific dependencies, with Bash 4.4+ and the Linux command-line tools
used by your workflows. Create a virtual environment and install a local wheel:

```bash
python3 -m venv "$HOME/.venvs/qbox"
source "$HOME/.venvs/qbox/bin/activate"
python -m pip install './qbox-0.1.0-py3-none-any.whl[analysis,structure]'
python -m qbox.install
deactivate
export PATH="$HOME/.local/bin:$PATH"
qbox --help
```

The one-time `qbox.install` step binds `~/.local/bin/qbox` to this Python environment.
Add `export PATH="$HOME/.local/bin:$PATH"` once to `~/.bashrc` if needed. New terminals
can then run `qbox` directly without activating Python. Existing commands are never
overwritten; `--bin-dir` selects another directory. This command pins its own Python
even if `QBOX_PYTHON` was set elsewhere. Keep the environment at its installed path.

Run the install command from the directory containing the downloaded wheel.
pip downloads the scientific dependencies. An existing Conda or other Python
3.10+ environment also works. See the [installation guide](docs/installation.md)
for Ubuntu/Rocky preparation, dependency checks, source installation and removal.
qbox does not replace the system Python.

QE, MPI, Multiwfn, unfold.x and pseudopotentials are external. The repository's
[optional Multiwfn download](third_party/Multiwfn/README.md) contains an original
ZIP, its license and checksum. Download and extract it separately, then set
`QBOX_MULTIWFN_HOME`. It is excluded from qbox wheels and source distributions
(sdists), and is never installed automatically.

## Complete offline bundle (optional)

Use `qbox-0.1.0-linux-x86_64-offline.tar.gz` and its SHA256 file when the target
has no network or suitable Python. It includes private CPython 3.12 and fixed
scientific dependencies, making it substantially larger; Multiwfn remains external.
See the [offline guide](packaging/offline/README.zh-CN.md) and
[recorded validation](docs/releases/offline-validation.md). Those results apply
only to the identified offline archive, not arbitrary external Python environments.

## Source installation and builds

From a complete checkout in your activated Python environment:

```bash
python -m pip install '.[analysis,structure]'
python -m qbox.install
```

Maintainers can build a lightweight wheel with
`python -m pip wheel --no-deps . -w dist/lightweight`.
The `analysis` and `structure` extras select analysis and structure dependencies.
Ordinary installation preserves `QBOX_PYTHON` / `QBOX_SHARED_ROOT`; offline mode
uses its private interpreter.

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

Examples below use the installed `qbox` command. From a source checkout, use `./qbox` instead.

Show the available command-line options:

```bash
qbox --help
```

Start the interactive workflow menu:

```bash
qbox
```

Run an available workflow action directly:

```bash
qbox ACTION [INPUT ...]
```

Use `qbox --version` to display the release version.

Discover all task IDs and readable names, or select a task explicitly:

```bash
qbox --list
qbox --task scf sample.cif
qbox --task 11 sample.cif
```

Task IDs 0–37, interactive menus, legacy argument positions and PW presets
(such as `qbox sample.cif 00`) are preserved. `--task` removes ambiguity between
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

The separately downloadable Multiwfn archive retains its original license; it is not covered by the qbox MIT license.
