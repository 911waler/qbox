# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox is a command-line toolkit for preparing, running, and post-processing
Quantum ESPRESSO workflows. It supports common SCF, relaxation, NSCF, band,
PDOS, phonon, molecular-dynamics, and convergence-scan tasks.

## Installation (recommended)

Use the same lightweight `qbox-<version>-linux-installer.tar.gz` for personal
and administrator installations. Supply Python 3.10+ with venv/pip support,
Bash 4.4+ and network access for scientific dependencies. Verify the downloaded
archive's `.sha256`, extract it, and enter its directory:

```bash
# Normal account: default $HOME/.local/share/qbox/bin/qbox
bash install.sh --user

# Custom prefix: command becomes $HOME/software/qbox/bin/qbox
bash install.sh --user --prefix "$HOME/software/qbox" --python /absolute/path/to/python3

# Administrator: default /opt/qbox/bin/qbox
sudo bash install.sh --system
```

Choose `--user` or `--system` explicitly. The installer creates a dedicated
fixed-path venv, installs the bundled qbox wheel plus analysis/structure
scientific dependencies, verifies workflows, and publishes `<prefix>/bin/qbox`.
It prints a shell-quoted PATH line and, for administrators, a `/etc/profile.d/`
example. Apply that PATH setting once; new terminals can run qbox without
activating Python. No shell files are changed automatically. `command -v qbox`
checks which command is selected. Keep the venv and its underlying Python in place.

An optional `--bin-dir PATH` selects a separate command directory. Existing
unrelated entries are never overwritten. For an existing self-managed Python
environment, the original `python -m qbox.install --bin-dir PATH` remains
available after installing the local wheel. See the [installation guide](docs/installation.md)
and [bundled guide](packaging/lightweight/README.zh-CN.md) for both modes,
Python preparation, PATH, verification, upgrades and ownership-checked removal.
The installer does not replace system Python or run apt/dnf. Checksums detect
corruption; they are not signatures or proof of origin.

QE, MPI, Multiwfn, unfold.x and pseudopotentials are external. The repository's
[optional Multiwfn download](third_party/Multiwfn/README.md) contains an original
ZIP, license and checksum. Download and extract it separately, then set
`QBOX_MULTIWFN_HOME`. It is excluded from every qbox installation archive,
wheel and sdist, and is never installed automatically.

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

Maintainers can build the wheel and unified installer with:

```bash
python -m pip wheel --no-deps . -w dist/lightweight
python tools/build-lightweight-installer.py --wheel dist/lightweight/qbox-0.1.0-py3-none-any.whl --output dist/lightweight
```

The builder reads the version from wheel metadata and emits a deterministic
installer archive and its `.sha256` file; differing existing outputs are rejected.
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

You may `module load` your chosen QE version before starting qbox. Before an
automatic calculation, qbox checks the commands and shared libraries needed by
that workflow. If the current environment meets those requirements, qbox keeps
its QE/MPI without calling module or loading configured environment scripts.
Generating input files alone does not load an environment.

`QBOX_QE_ENV_SCRIPT` and `QBOX_ONEAPI_ENV_SCRIPT` are optional fallbacks. Only when
the current environment is insufficient does qbox try the configured QE script,
module selection, and compiler/MPI script. `QE_MODULE` selects a fallback module;
it does not override an environment that already meets the requirements.

Workflows requiring `pw.x` still require QE strictly newer than 7.0. The version
probe waits at most 5 seconds and cleans up its processes. If direct startup
does not return a version, qbox retries once through the current `mpirun -np 1`,
also with a 5-second limit; this supports MPI builds that cannot start as
singleton processes. A captured version is checked normally; if neither probe
returns one, qbox stops the calculation while preserving the current environment.

Automatic calculations confirm the QE environment first (selecting a CPU/GPU
module when loading is needed), then ask for parallelism. Before those prompts,
CPU mode shows the online physical core count without counting SMT siblings twice,
plus estimated idle physical cores from a 0.25-second sample. The estimate uses
each core's busiest logical CPU, sums its remaining capacity, and rounds down.
GPU mode instead shows only the machine's GPU count and idle GPU count, using a
bounded `nvidia-smi` snapshot. An idle GPU has no compute process, zero sampled
utilization, and an enabled compute mode. These counts describe physical devices
reported by the driver, not CUDA cores or scheduler allocations. Resource counts
change with load and are guidance only; unavailable information is shown as
unknown. Resource mode follows the active QE executable/module, including a
preloaded environment, rather than an unused `QE_MODULE` fallback.
The entered counts are MPI processes passed to `mpirun -np`. Reusing
completed results for all calculation stages skips environment loading and these
parallelism prompts.

Automatic band calculations run SCF, `pw.x` bands, and `bands.x` from the project
directory, so their relative `outdir` paths resolve to the same SCF save data.
Band inputs, output logs, data, and plots remain under `BAND/`.

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
