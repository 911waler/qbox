# Offline validation index

Local acceptance passed for the artifact below. No release was pushed, published,
merged or deployed. The complete machine-readable record is
[offline-evidence-index.json](offline-evidence-index.json).

- Artifact SHA256: `e0f94e7cc7f7c2e4fab752e952778bf60aa9564f99cf8aa208821a9146c59e05`
- Manifest SHA256: `257d5bb338e1acf4f794ad9434818638e4f9a470694ce0e519c407bd82814e9a`
- Product source: `d1e8c2888c6b00fa2249c006ce3d9e2c02dd1272`
- Actual target driver SHA256: `c49a6a5efa70efbe10dc327806fa301699efcee64bd345bfa3cd97bfe6bc1e98`
- Gate and offline unit code use the same final fix commit as the product.

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
- 212 offline unit tests with no skips; 15 focused gate/documentation tests.
- Two clean offline builds with identical archive SHA.
- Exact 249 ELF members and 13 native-wheel static reports; all 249 members loaded
  in actual isolated bundled-Python processes on minimal Rocky 8, with LD_DEBUG
  and mapped-library byte hashes. Libraries resolved only to the delivered
  runtime/dependencies or the previously locked OS baseline providers; zlib came
  from the release. 64 corresponding-source archives remain delivered.
- Actual bundled guide default/custom-space installs and both self-check/rollback
  blocks under DISPLAY=:0; 13 ownership conflict cases preserved current and user
  sentinels, including regular/directory/unmanaged current, replaced locks/root
  markers and six temporary collision/replacement variants. Guarded uninstall
  passed without relying on errexit.
- Final gate exited 0 and generated `dist/offline/release-ready.json` only after
  all required raw evidence was present and passing. An earlier incomplete
  invocation exited 1 and created no ready marker.

Large logs and archives remain in the ignored local directories named in the
JSON index; report and log SHA256 references make them retrievable and verifiable
from this workspace. There is no public download channel yet. No host-private
raw logs are committed. Historical Task3/Task10 and both earlier Task11 candidates
(including archive341d8a...) are not substituted for this final fix artifact.

The retained ATOMICs_VELOCITIES warning and numeric-filename backend fallback
diagnostics are known test output; they were not suppressed. GENERIC BLAS may
be slower than CPU-optimized libraries. This evidence does not promise future
Ubuntu/Rocky releases, ARM, every native API, or real external QE/MPI calculations.
