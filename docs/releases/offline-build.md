# Maintainer offline release procedure

The user deliverable is the tar.gz and external SHA256 file. Images, QEMU and
build tools are maintainer infrastructure and never installation requirements.
Use a clean committed source tree, an explicitly chosen Python and isolated output
directories. Do not update shared production installations.

1. Resolve fixed inputs using `python -m tools.offline resolve --policy packaging/offline/policy.json --cache build/offline/cache` in the pinned builder. Review every runtime, wheel, tool and source hash and corresponding license before accepting locks. Resolution is the only acquisition phase.
2. Run `python -m tools.offline audit --cache build/offline/cache --output build/offline/audit`. Preserve full license/source and native-byte records. Static audit is not CPU execution evidence.
3. With reviewed locks and complete local cache, run `python -m tools.offline build --cache build/offline/cache --output dist/offline/candidate-1`, then the same with `candidate-2`. Builds must use the pinned maintainer builder, disabled network and identical clean source commit. Compare actual archive SHA256 values and retain both logs and command arrays.
4. Run `python -m tools.offline matrix --candidate dist/offline/candidate-1/candidate.json --engine docker --output build/offline/evidence`. The output directory must be new. All five pinned images must already be cached (`--pull=never`). No live source, host HOME, development venv or host /opt is mounted. The immutable test driver is separate from product source. Actual engine inspect captures image identity and isolation.
5. Add strict CPU VM, native loader, regression, offline unit, reproducibility and documentation evidence below; run `python -m tools.offline gate --candidate dist/offline/candidate-1/candidate.json --evidence build/offline/evidence`.

Only complete passing evidence creates `dist/offline/release-ready.json`. This is a
local verdict, not authorization to publish, push, merge or deploy. A later pure
report commit must retain the actual product source commit; any bundled changes
require a new build and acceptance of its new SHA. Evidence is never inserted back
into the tested archive.

## Minimum image preparation

`packaging/offline/images.lock.json` pins upstream image manifests. No derived
scientific image is used: the supplied Ubuntu images retain mawk, Rocky retains
its default gawk. No additional packages are needed for the target harness. The
actual full dpkg/rpm base package inventory is collected per run; OS-owned Python
is not uninstalled. Failing Python/pip/compiler/downloader/bc substitutes prove
qbox did not invoke them. A diagnostic environment may use OS loader tools; it
must remain separate from the target user prerequisites.

## Evidence contract

Each platform report contains schema, OS/image/kernel/architecture/CPU facts,
base-package inventory, actual network and UID, artifact/manifest/source identity,
committed harness identity, timestamps, each of the 13 required cases and raw
results/inspect references with SHA256. Container kernel facts describe the host.
All twelve reviewed Task10 groups must run; real upgrades at before/after-current
SIGINT/SIGTERM boundaries must use the corrected harness.

`baseline-cpu.json` binds the same candidate to a fresh private Ubuntu20 or Rocky8
VM, a verified QEMU8.2 TCG baseline model, actual flags, independent guest kernel,
network none, ordinary product UID, full smoke, actual archive installation,
SSE3 HADDPS SIGILL negative control and actual noexec. Preserve console and command
records. Original cloud image remains pristine; expand only a private overlay.
Do not claim unexecuted fault groups in this narrower supplemental VM run.

`regressions.json`, `offline_tests.json`, `reproducibility.json`, `elf_loads.json`
and `documentation.json` each bind artifact_sha256, manifest_sha256 and
source_commit, status=passed, failures=[], skipped=[], explicit passed cases and
SHA256 references to real logs. Reproducibility records both archive_sha256s.
ELF loads record exact expected_count/resolved_count=249 and unresolved=[] plus
all member paths/hashes and resolved library origins in the minimal diagnostic
container. The accepted diagnostic runs the actual bundled Python with `-I -B`,
imports extension prerequisites, and records `LD_DEBUG=libs` plus actual mapped
file SHA256 values. Do not replace this with running an extension as a standalone
main ELF, or force success with a global `LD_LIBRARY_PATH`. Each tested member
must actually appear among the mapped bytes; system providers must match the
previously locked baseline hashes. Gate rejection is expected for missing, failed,
skipped or not_run records. JSON reports are local evidence, not cryptographic third-party attestations.
