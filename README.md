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
qbox --task 12 sample.cif
```

Task IDs 0–10 are unchanged. New task 11 generates Wannier90 inputs; previous
IDs 11–37 move to 12–38. Named tasks, legacy argument positions and PW presets
(such as `qbox sample.cif 00`) are preserved. See the [number migration table](docs/releases/wannier-inputs.md). `--task` removes ambiguity between
a numeric filename and a task ID; the remaining arguments are input paths, not
legacy selectors. Tasks may still ask for workflow-specific choices. The module
entry `python -m qbox` is also available after installation.

## Wannier90 inputs

The source-tree launcher also reads an optional `.qbox-local.sh` beside `qbox`
before starting the menu or a direct task. Keep workstation defaults there with
exported fallback assignments (for example,
`export QBOX_PSEUDO_ROOT="${QBOX_PSEUDO_ROOT:-/path/to/pseudopotentials}"`).
This file is Git-ignored and is not bundled. Direct `python -m qbox` and sourcing
`qbox` do not load it.

```bash
qbox --task wannier-input sample.cif
qbox --task wannier-input sample.scf.in
qbox --task wannier-input --config settings.json --conflict cancel
qbox kmesh 4 4 2 --format qe
```

Select one of six directions, then edit tasks, source/run directory, seed/version,
grid, bands/projections, energy windows and task parameters. The menu preserves
common settings when changing direction and replaces task selections. Target
Wannier90 3.1.0 inputs are validated and previewed before writing to the current
directory; conflicts offer backup, rename or cancel. Generation does not run QE
or Wannier90. After direction selection, CIF sources first reuse a matching SCF
input in the current directory. The QE input wizard opens only when no matching
SCF is found; no completed SCF calculation is required. New SCF inputs are also
saved in the current directory, with rename or
cancel on conflicts. See [usage and migration notes](docs/releases/wannier-inputs.md).

## Phonon calculations

Execution menu **40 / phonons** currently offers phonon dispersion calculations:

```bash
qbox --task phonons model.cif
qbox --task phonons model.scf.in
```

The existing input wizard prepares SCF and dispersion inputs, then qbox runs
SCF → `ph.x` → `q2r.x` → `matdyn.x` → plotting. A CIF without a companion SCF
input enters the SCF wizard first. SCF and PH have separate MPI process counts;
q2r and matdyn run serially. All working inputs, `scf.out`, `ph.out`, `q2r.out`,
`matdyn.out`, `plot.out`, scratch data, frequency tables and PNG/SVG plots stay
inside the current project's `PHONON/` directory.

The original SCF input is preserved. Its working copy redirects scratch into
`PHONON/` while resolving pseudopotentials against the original source directory.
On a subsequent run, reuse the prepared inputs and completed stages or request a
full recalculation. Completion records track inputs and required products;
upstream changes invalidate downstream stages. Calculation or plotting failures
stop subsequent stages and return a nonzero status. Gamma-only frequencies, IR
and Raman execution are not yet offered.

After loading QE/MPI, maintainers can run
`tools/verify-phonon-native.py --pseudo /path/to/Si.UPF` to exercise the public
qbox entry point from an empty calculation directory, then test resumption and
input invalidation. Small meshes and cutoffs test orchestration, not converged
material properties. This verification requires neither Codex nor a network service.
Add `--from-cif` to start with only a CIF in a long directory path and also
exercise real Multiwfn conversion and the SCF input wizard; this mode requires
Multiwfn to be configured.

## Phonon dispersion plots

Menu **39 / plot-phonons** scans all `*.freq.gp` files in the current directory
and writes a separate `<prefix>_phonon.png` and `<prefix>_phonon.svg` for each:

```bash
qbox --task plot-phonons
qbox --task plot-phonons sic.freq.gp
```

During automatic detection, matching `.path.json` metadata takes precedence.
Explicit companion files override automatic detection. For external QE data, qbox
also looks for associated MATDYN inputs and reads path vertices, interpolation
counts, explicit breaks, and trailing labels such as `! Gamma` or `! X`.
The input's `flfrq` and expanded point count must match the data. Frequencies
remain in cm⁻¹, including negative values; disconnected segments are drawn
separately. A standalone `.freq.gp` is plotted with a numeric x axis, without
inventing high-symmetry labels.

Newly generated MATDYN inputs include endpoint labels and `qbox:path-v1`
comments describing segment boundaries and Gamma guard rows. This preserves
labels, disconnected segments, and guard exclusions even without JSON, without
changing QE's numeric input. Existing inputs are not rewritten automatically.
Labels map to `.freq.gp` positions by sample index; a companion `.freq` provides
q-coordinate and frequency consistency checks. Repeated Gamma rows can encode
different directional limits and must not be deduplicated by q coordinate.

The interactive menu accepts another path file or manual labels and breaks.
Manual settings replace automatic path settings and use one-based numeric
data rows, excluding comments and blank lines. A break identifies the first
row of the next segment:

```bash
python -m qbox.postprocess.phonon_plot -i sic.freq.gp --ticks '1:Gamma,21:X,22:M,42:Gamma' --breaks 22
```

The Python module also accepts `--directory` for batch plotting, `--matdyn`
or `--path` for explicit companion files, and the existing `.freq` plus
`.path.json` interface. Invalid files do not prevent other batch members
from being plotted; any failures are summarized and produce a nonzero status.

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
