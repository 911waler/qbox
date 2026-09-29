"""Bounded subprocess probes for the inherited QE runtime."""

import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


def _process_snapshot():
    processes = {}
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            processes[int(entry.name)] = (int(fields[1]), int(fields[3]), fields[19])
        except (OSError, ValueError, IndexError):
            continue
    return processes


def _stop_process_tree(process):
    # Open MPI ranks can have their own process groups. Remember descendants
    # before asking the launcher to stop, including any that start a session.
    tracked = {}

    def collect():
        snapshot = _process_snapshot()
        roots = {process.pid} | {
            pid for pid, identity in tracked.items()
            if pid in snapshot and snapshot[pid][2] == identity
        }
        while True:
            found = {pid for pid, (parent, session, _) in snapshot.items()
                     if parent in roots or session == process.pid}
            if found <= roots:
                break
            roots.update(found)
        for pid in roots:
            if pid in snapshot:
                tracked[pid] = snapshot[pid][2]
        return snapshot

    collect()
    if process.poll() is None:
        process.terminate()
        deadline = time.monotonic() + 0.5
        while process.poll() is None and time.monotonic() < deadline:
            collect()
            time.sleep(0.02)
    snapshot = collect()
    for pid, identity in tracked.items():
        if pid in snapshot and snapshot[pid][2] == identity:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)


def _capture_probe(command, directory):
    # Some QE builds initialize MPI and read input even with -version. Isolate
    # the probe's process group so a stuck MPI child cannot keep it alive.
    process = subprocess.Popen(
        command, cwd=directory, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        try:
            output, _ = process.communicate(timeout=5)
            # QE may print its banner then exit nonzero because stdin is empty.
            return output, 0
        except subprocess.TimeoutExpired as error:
            return error.output or b"", 124
    finally:
        # A second cancellation during the TERM grace period must not skip
        # the KILL fallback. Deliver it after all probe processes are stopped.
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGHUP, signal.SIGINT},
        )
        try:
            _stop_process_tree(process)
        finally:
            process.stdout.close()
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def capture_qe_version_output(executable, directory, launcher=None):
    output, status = _capture_probe([executable, "-version"], directory)
    version = rb"Program PWSCF v\.[0-9]+(?:\.[0-9]+)+"
    if not launcher or re.search(version, output):
        return output, status
    # Some HPC-X/Open MPI builds cannot initialize as singleton processes.
    # Reuse the caller's launcher with one rank, after reaping the first probe.
    mpi_output, mpi_status = _capture_probe(
        [os.path.abspath(launcher), "-np", "1", executable, "-version"], directory,
    )
    output += b"\n" + mpi_output
    return output, 0 if re.search(version, mpi_output) else max(status, mpi_status)


def _stop_probe(signum, _frame):
    # Exit through Python's finally blocks so cancellation also reaps MPI.
    raise SystemExit(128 + signum)


def main():
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, _stop_probe)
    try:
        launcher = sys.argv[3] if len(sys.argv) > 3 else None
        output, status = capture_qe_version_output(sys.argv[1], sys.argv[2], launcher)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"qbox: QE version probe failed: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(output)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
