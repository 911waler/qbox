# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox is a command-line toolkit for preparing, running, and post-processing
Quantum ESPRESSO workflows. It supports common SCF, relaxation, NSCF, band,
PDOS, phonon, molecular-dynamics, and convergence-scan tasks.

## Offline installation (normal users)

The supported delivery format is the complete `qbox-0.1.0-linux-x86_64-offline.tar.gz`
with its SHA256 file. It includes a private CPython 3.12 and all scientific Python
runtime dependencies. Requires x86_64 Linux, glibc 2.28+, Bash 4.4+, GNU coreutils,
grep, sed, system awk, tar and gzip. No system Python, compiler, sudo or network is
needed. QE, MPI, Multiwfn, unfold.x and pseudopotentials remain external.

```bash
sha256sum -c qbox-0.1.0-linux-x86_64-offline.tar.gz.sha256
mkdir unpacked
tar -xzf qbox-0.1.0-linux-x86_64-offline.tar.gz -C unpacked
bash unpacked/install.sh
export PATH="$HOME/.local/bin:$PATH"
qbox --help
```

See the [bundled guide](packaging/offline/README.zh-CN.md) for custom paths,
read-only installations, self-checks, owned-lock recovery, rollback and removal.
See [actual validation](docs/releases/offline-validation.md) before making a
platform compatibility claim. GENERIC BLAS favors baseline CPU compatibility and
can be slower than a CPU-optimized scientific environment.

## Source and wheel development

A complete source checkout or ordinary wheel uses a Python 3.10+ environment
managed by the developer. Build a wheel with `python -m pip wheel --no-deps . -w dist`
and install the local wheel with its separately supplied dependencies. The
`analysis` and `structure` extras select the scientific dependencies. A wheel alone
is not the complete offline distribution. Source/wheel mode preserves
`QBOX_PYTHON` and `QBOX_SHARED_ROOT`; offline mode rejects a conflicting
`QBOX_PYTHON` and uses its private runtime. Do not add private Python/library paths
to global PATH or LD_LIBRARY_PATH.

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
