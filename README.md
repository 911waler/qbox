# qbox

qbox is a command-line toolkit for preparing, running, and post-processing
Quantum ESPRESSO workflows. It supports common SCF, relaxation, NSCF, band,
PDOS, phonon, molecular-dynamics, and convergence-scan tasks.

## Requirements

- Bash 4 or newer
- Quantum ESPRESSO for calculation workflows
- Python 3 for plotting and analysis features
- Multiwfn for workflows that use Multiwfn analysis

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

## Citation

If qbox supports your work, please cite the software using
[`CITATION.cff`](CITATION.cff).

Maintained by waler.

## License

qbox is released under the MIT License. See [`LICENSE`](LICENSE).
