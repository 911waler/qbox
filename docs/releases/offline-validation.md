# Offline validation index

Local acceptance passed for the artifact below. No release was pushed, published,
merged or deployed. The complete machine-readable record is
[offline-evidence-index.json](offline-evidence-index.json).

- Artifact SHA256: `341d8a7abd74af0c404d1a7c6b47dac6b70c4a09de42e0272e60aecf9988057d`
- Manifest SHA256: `5a477de5296b1557b65c01167fd107910e79045e7c09802a75d12f8eb6800e64`
- Product source: `9020693e5dbe3979b91216b8b775866021bd958c`
- Actual target driver SHA256: `c49a6a5efa70efbe10dc327806fa301699efcee64bd345bfa3cd97bfe6bc1e98`
- Gate code: `e3238da`; offline unit code: `7dc2b0c`. These later changes affect
  external acceptance tooling only; the product was built from `9020693`.

| Executed target | glibc | awk | Full target cases | Kernel scope |
| --- | --- | --- | --- | --- |
| ubuntu-20.04 (20.04) | glibc 2.31 | /usr/bin/mawk | 13/13 | shared host kernel |
| ubuntu-22.04 (22.04) | glibc 2.35 | /usr/bin/mawk | 13/13 | shared host kernel |
| ubuntu-24.04 (24.04) | glibc 2.39 | /usr/bin/mawk | 13/13 | shared host kernel |
| rocky-8 (8.10) | glibc 2.28 | /usr/bin/gawk | 13/13 | shared host kernel |
| rocky-9 (9.8) | glibc 2.34 | /usr/bin/gawk | 13/13 | shared host kernel |

All five runs used the same archive, ordinary UID 1000, no network, read-only
rootfs, executable private temporary storage and a separate real noexec mount.
The engine inspect records bind the requested immutable manifest to the actual
image ID and mounts. Ubuntu retained mawk; Rocky retained its default gawk.
Each ran all 12 reviewed Task10 groups (including 14 real INT/TERM phase scenarios,
distinct upgrades at both current publication boundaries, SIGKILL/recovery,
read-only/cache behavior, lock contention and shared command-link races) plus
target-side extraction and installation of the actual delivered archive.

The separate Ubuntu 20.04 VM used kernel `5.4.0-216-generic` with QEMU 8.2.2
TCG and the exact baseline CPU model in the JSON index. The final archive was
installed as UID 1000 with no guest network interface except loopback. All 11
scientific smoke checks passed. HADDPS actually raised SIGILL; a real noexec
mount denied execution and installation failed safely. This VM does not claim
the full container failure matrix or other distributions’ native kernels.

Supplemental evidence passed:

- 241 original shell assertions and 49 Python tests.
- 203 offline unit tests with no skips; 15 focused gate/documentation tests.
- Two clean offline builds with identical archive SHA.
- Exact 249 ELF members and 13 native-wheel static reports; all 249 members loaded
  in actual isolated bundled-Python processes on minimal Rocky 8, with LD_DEBUG
  and mapped-library byte hashes. Libraries resolved only to the delivered
  runtime/dependencies or the previously locked OS baseline providers; zlib came
  from the release. 64 corresponding-source archives remain delivered.
- Actual bundled guide default/custom-space installs, full self-checks, owned-lock
  rollback, preexisting temporary-link collision preservation, and guarded
  uninstall without relying on errexit. User sentinels remained unchanged.
- Final gate exited 0 and generated `dist/offline/release-ready.json` only after
  all required raw evidence was present and passing. An earlier incomplete
  invocation exited 1 and created no ready marker.

Large logs and archives remain in the ignored local directories named in the
JSON index; report and log SHA256 references make them retrievable and verifiable
from this workspace. There is no public download channel yet. No host-private
raw logs are committed. Historical Task3/Task10 and the terminated e9a43fa...
Task11 candidate are not substituted for this final artifact.

The retained ATOMICs_VELOCITIES warning and numeric-filename backend fallback
diagnostics are known test output; they were not suppressed. GENERIC BLAS may
be slower than CPU-optimized libraries. This evidence does not promise future
Ubuntu/Rocky releases, ARM, every native API, or real external QE/MPI calculations.
