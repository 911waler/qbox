"""Cancelling a runtime check must not leave its isolated MPI probe running."""

import os
import itertools
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RuntimeProbeTests(unittest.TestCase):
    def test_hanging_singleton_uses_existing_mpi_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            executable = work / "pw.x"
            executable.write_text(
                '#!/bin/sh\nif [ "${QBOX_TEST_MPI:-}" = 1 ]; then\n'
                " printf 'Program PWSCF v.7.5\\n'; exit 1\nfi\n"
                'echo $$ > direct.pid\nexec sleep 30\n'
            )
            executable.chmod(0o755)
            launcher = work / "mpirun"
            launcher.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > mpi.args\n'
                '[ "$1" = -np ] && [ "$2" = 1 ] || exit 9\n'
                'shift 2\nexport QBOX_TEST_MPI=1\nexec "$@"\n'
            )
            launcher.chmod(0o755)
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
            result = subprocess.run(
                [sys.executable, "-m", "qbox.runtime", str(executable), directory, str(launcher)],
                env=env, capture_output=True, text=True, timeout=12,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Program PWSCF v.7.5", result.stdout)
            self.assertEqual((work / "mpi.args").read_text().splitlines(),
                             ["-np", "1", str(executable), "-version"])
            with self.assertRaises(ProcessLookupError):
                os.kill(int((work / "direct.pid").read_text()), 0)

    def test_detected_direct_version_does_not_launch_mpi(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            executable = work / "pw.x"
            executable.write_text("#!/bin/sh\nprintf 'Program PWSCF v.7.0\\n'\nexit 1\n")
            executable.chmod(0o755)
            launcher = work / "mpirun"
            launcher.write_text("#!/bin/sh\ntouch unexpected-mpi\n")
            launcher.chmod(0o755)
            result = subprocess.run(
                [sys.executable, "-m", "qbox.runtime", str(executable), directory, str(launcher)],
                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                capture_output=True, text=True, timeout=3,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("v.7.0", result.stdout)
            self.assertFalse((work / "unexpected-mpi").exists())

    def test_timeout_cleans_up_rank_in_separate_session(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            executable = work / "pw.x"
            executable.write_text("#!/bin/sh\nexit 1\n")
            executable.chmod(0o755)
            launcher = work / "mpirun"
            launcher.write_text(
                "#!" + sys.executable + "\n"
                "import subprocess, pathlib, time, sys\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)\n"
                "pathlib.Path('rank.pid').write_text(str(child.pid))\n"
                "time.sleep(30)\n"
            )
            launcher.chmod(0o755)
            rank = None
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "qbox.runtime", str(executable), directory, str(launcher)],
                    env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                    capture_output=True, text=True, timeout=12,
                )
                rank = int((work / "rank.pid").read_text())
                self.assertEqual(result.returncode, 124, result.stderr)
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    stat = Path(f"/proc/{rank}/stat")
                    if not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("MPI rank in its own session survived probe timeout")
            finally:
                if rank is not None:
                    try:
                        os.kill(rank, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_cancellation_during_cleanup_still_stops_rank(self):
        root = ROOT
        with tempfile.TemporaryDirectory(prefix='qbox-cleanup-cancel-review-') as directory:
            work = Path(directory)
            executable = work / 'pw.x'
            executable.write_text('#!/bin/sh\nexit 1\n')
            executable.chmod(0o755)
            launcher = work / 'mpirun'
            launcher.write_text(
                '#!' + sys.executable + '\nimport os, pathlib, signal, subprocess, sys, time\n'
                'signal.signal(signal.SIGTERM, lambda *_: pathlib.Path("cleanup.started").write_text("started"))\n'
                'pathlib.Path("launcher.pid").write_text(str(os.getpid()))\n'
                'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)\n'
                'pathlib.Path("rank.pid").write_text(str(child.pid))\n'
                'time.sleep(30)\n'
            )
            launcher.chmod(0o755)
            env = dict(os.environ, PYTHONPATH=str(root / 'src'), PYTHONDONTWRITEBYTECODE='1')
            probe = subprocess.Popen(
                [sys.executable, '-m', 'qbox.runtime', str(executable), directory, str(launcher)],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
            )
            live = []
            try:
                deadline = time.monotonic() + 7
                while not (work / 'cleanup.started').exists() and time.monotonic() < deadline:
                    time.sleep(.005)
                assert (work / 'cleanup.started').exists(), 'cleanup marker missing'
                os.kill(probe.pid, signal.SIGTERM)
                stdout, stderr = probe.communicate(timeout=3)
                for name in ('launcher', 'rank'):
                    pid = int((work / (name + '.pid')).read_text())
                    path = Path('/proc') / str(pid) / 'stat'
                    deadline = time.monotonic() + 1
                    while True:
                        state = path.read_text().rsplit(')', 1)[1].split()[0] if path.exists() else 'absent'
                        if state in ('absent', 'Z', 'X') or time.monotonic() >= deadline:
                            break
                        time.sleep(.01)
                    if state not in ('absent', 'Z', 'X'):
                        live.append(name)
                assert probe.returncode == 128 + signal.SIGTERM, 'cancellation status changed'
            finally:
                for name in ('rank', 'launcher'):
                    path = work / (name + '.pid')
                    if path.exists():
                        try:
                            os.kill(int(path.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                if probe.poll() is None:
                    probe.kill()
                probe.communicate(timeout=2)
            assert not live, f'Cleanup cancellation leaked {live}; test has killed them'

    def test_termination_signals_clean_up_probe(self):
        for signum, mpi_fallback in itertools.product((signal.SIGTERM, signal.SIGHUP), (False, True)):
            with self.subTest(signal=signum, mpi=mpi_fallback), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                executable = work / "pw.x"
                executable.write_text('#!/bin/sh\necho $$ > probe.pid\nexec sleep 30\n')
                executable.chmod(0o755)
                args = [sys.executable, "-m", "qbox.runtime", str(executable), directory]
                if mpi_fallback:
                    launcher = work / "mpirun"
                    launcher.write_text(executable.read_text())
                    launcher.chmod(0o755)
                    executable.write_text('#!/bin/sh\nexit 1\n')
                    args.append(str(launcher))
                env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
                probe = subprocess.Popen(
                    args,
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                child_pid = None
                try:
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        if (work / "probe.pid").exists():
                            pid_text = (work / "probe.pid").read_text().strip()
                            if pid_text:
                                child_pid = int(pid_text)
                                break
                        time.sleep(0.01)
                    self.assertIsNotNone(child_pid, "probe did not start")
                    os.killpg(probe.pid, signum)
                    stdout, stderr = probe.communicate(timeout=2)
                    with self.assertRaises(ProcessLookupError, msg="cancelled QE probe survived"):
                        os.kill(child_pid, 0)
                    self.assertEqual(probe.returncode, 128 + signum, (stdout, stderr))
                finally:
                    # Keep the regression safe even when testing the broken implementation.
                    for pid in (child_pid, probe.pid):
                        if pid is not None:
                            try:
                                os.killpg(pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                    probe.communicate(timeout=2)


if __name__ == "__main__":
    unittest.main()
