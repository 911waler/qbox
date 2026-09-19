# Maintainer baseline scientific wheels

The target remains an offline, wheel-only installation. NumPy 2.5.3 and SciPy
1.18.1 are rebuilt from their fixed official sdists with full GENERIC OpenBLAS
(ILP64 and LP64 respectively). Generic kernels trade newer-CPU BLAS performance
for the x86-64/SSE2 baseline; all four scalar types and BLAS/LAPACK stay enabled.
NumPy retains separate optional higher-ISA dispatch kernels. lxml 6.1.3 is
also rebuilt with the same locked libxml2/libxslt/iconv/zlib source versions. Its
upstream wheel executes SSE3 MOVDDUP during module initialization.

Acquire the explicit locked inputs, then compile twice in clean, network-disabled
containers and normalize twice in the same immutable builder image:

```sh
python -m tools.offline cpu-build --fetch --output build/offline/cpu-build-new
python -m tools.offline cpu-build --lock packaging/offline/cpu-lxml-build-inputs.lock.json --output build/offline/cpu-build-lxml-new
```

Omit `--fetch` to require already cached inputs. Commit recipe/helper changes
before building: provenance records the actual executed Git commit and SHA256 of
its code. Both clean runs must produce identical final wheel bytes. The immutable
image locks the OS/compiler/Python closure; `cpu-build-inputs.lock.json` additionally
locks the upstream source and Python build wheels. No target compilation occurs.

Reviewed output records belong in `dependencies.lock.json` and `requirements.lock`;
license/native byte rules must be refreshed before running `python -m tools.offline
audit`. Normal resolve/audit requires prebuilt, hash-matching `cache/cpu-wheelhouse`
files and fails if they are missing. It never falls back to an implicit build.

For completed independent runs, `cpu-finalize PROVENANCE --output NEW_DIRECTORY`
performs only the pinned normalization stage. It preserves the compile commit and
records a separate normalization commit. A differing existing cache wheel is an
error: preserve it explicitly before promoting a reviewed replacement.

The bundle builder and validator must deliver and verify:

* Component `scientific`: `checks/cpu-build-inputs.lock.json` and
  `checks/cpu-build-provenance.json`;
* Component `lxml`: `checks/cpu-lxml-build-inputs.lock.json` and
  `checks/cpu-lxml-build-provenance.json`;
* `checks/cpu-build/compile/<component>/<path>` for each top-level `recipe_files` member,
  retrieved from top-level `code_commit`;
* `checks/cpu-build/normalize/<component>/<path>` for each `normalization.recipe_files` member,
  retrieved from `normalization.code_commit`.

`dependencies.lock.json.cpu_build` is a list with stable `id`, `inputs`,
`inputs_sha256`, `provenance`, `provenance_sha256` fields per component. Reject
duplicate IDs, overlapping wheel outputs and uncovered custom wheels using
`validate_components`. Each component keeps its original actual build history.

Both commits must contain the actual executed code. Check the delivered recipe
SHA256 values, input lock digest, fixed image digest, source and build input
identities, both normalization input maps against `compilation_outputs`, and both
normalization/final output maps against the **actual delivered wheel bytes**.
`cpu_wheels.validate_provenance` validates the record relationships; callers must
rehash actual files first. Include all these checks in manifest `identity.checks`
and `files`. Do not merge the two recipe directories: the same repository path
can have different bytes in each stage. Wheel `source` is the actual official
sdist URL/hash; it is never the original upstream binary wheel's URL/hash.

`cpu_probe.py SITE --baseline --artifacts DIRECTORY` is a maintainer numerical
probe. The directory contains `inputs.json` (filename/SHA256 entries) and the
actual wheels/runtime/probe bytes. Run it as a non-root guest with strict x86-64
flags and an emulator which actually rejects the SSE3 negative-control opcode.
QEMU 6.2 hid CPUID while executing that opcode, so it is insufficient. This probe
covers real/complex matrix operations, decompositions and representative extras.
The lxml build applies its recorded maintainer-only buildlibxml.py patch: fixed
source locations and a QBOX_OFFLINE_BUILD=1 branch reject missing/corrupt archives
without any download fallback. Upstream archive hash checks remain mandatory.
The recipe asserts exact before/after source hashes and executes the actual
patched loader against valid, corrupt and missing inputs during both builds.
Static ELF/auditwheel checks alone are not CPU proof. Final installer validation
on all five supported OS images and strict CPU emulation is still required.
