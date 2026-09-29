"""CPU guidance counts physical cores, never SMT siblings as extra cores."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qbox.cpu_resources import estimate_idle_cores, physical_core_groups, read_cpu_times


ROOT = Path(__file__).resolve().parents[2]


class CpuResourceTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name)
        self.cpuinfo = self.root / "cpuinfo"
        self.cpuinfo.write_text("")

    def topology(self, online, siblings):
        (self.root / "online").write_text(online)
        for cpu, sibling_list in siblings.items():
            directory = self.root / f"cpu{cpu}" / "topology"
            directory.mkdir(parents=True)
            (directory / "thread_siblings_list").write_text(sibling_list)

    def test_smt_siblings_are_one_physical_core(self):
        self.topology("0-3", {0: "0,2", 1: "1,3", 2: "0,2", 3: "1,3"})
        self.assertEqual(physical_core_groups(self.root, self.cpuinfo), [(0, 2), (1, 3)])

    def test_disabled_smt_and_offline_cpus_do_not_inflate_count(self):
        self.topology("0-1", {0: "0,2", 1: "1,3"})
        self.assertEqual(physical_core_groups(self.root, self.cpuinfo), [(0,), (1,)])

    def test_cpuinfo_fallback_distinguishes_sockets_and_deduplicates_smt(self):
        self.cpuinfo.write_text("\n\n".join(
            f"processor : {cpu}\nphysical id : {socket}\ncore id : {core}"
            for cpu, socket, core in ((0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0))
        ))
        self.assertEqual(physical_core_groups(self.root, self.cpuinfo), [(0, 2), (1, 3)])

    def test_unknown_topology_is_not_reported_as_logical_cpu_count(self):
        self.cpuinfo.write_text("processor : 0\n\nprocessor : 1\n")
        self.assertIsNone(physical_core_groups(self.root, self.cpuinfo))

    def test_one_busy_smt_sibling_consumes_the_physical_core(self):
        before = {cpu: (100, 100) for cpu in range(4)}
        after = {0: (200, 100), 1: (200, 200), 2: (200, 200), 3: (200, 200)}
        self.assertEqual(estimate_idle_cores([(0, 2), (1, 3)], before, after), 1)

    def test_idle_estimate_is_conservative_whole_physical_cores(self):
        before = {cpu: (0, 0) for cpu in range(3)}
        after = {0: (100, 90), 1: (100, 80), 2: (100, 40)}
        self.assertEqual(estimate_idle_cores([(0,), (1,), (2,)], before, after), 2)
        after = {cpu: (100, 0) for cpu in range(3)}
        self.assertEqual(estimate_idle_cores([(0,), (1,), (2,)], before, after), 0)
        after = {cpu: (100, 100) for cpu in range(3)}
        self.assertEqual(estimate_idle_cores([(0,), (1,), (2,)], before, after), 3)

    def test_missing_or_invalid_samples_are_unknown(self):
        for after in ({}, {0: (10, 5)}, {0: (9, 6)}, {0: (20, 4)}):
            with self.subTest(after=after):
                self.assertIsNone(estimate_idle_cores([(0,)], {0: (10, 5)}, after))

    def test_stat_excludes_double_counted_guest_time(self):
        stat = self.root / "stat"
        stat.write_text("cpu 0 0 0 0\ncpu0 10 2 3 40 5 1 2 7 8 1\nintr 3\n")
        self.assertEqual(read_cpu_times(stat), {0: (70, 45)})

    def test_shell_report_leaves_stdout_clean_for_numeric_prompts(self):
        env = dict(os.environ, QBOX_PYTHON=sys.executable)
        for key in ("BASH_FUNC_module%%", "BASH_FUNC_ml%%"):
            env.pop(key, None)
        result = subprocess.run(
            ["bash", "-c", 'QBOX_TEST_MODE=1 source "$1"; qe_report_cpu_resources; printf 4',
             "cpu-report", str(ROOT / "qbox")],
            env=env, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "4")
        self.assertRegex(result.stderr, r"\A 当前机器物理核心总数：(\d+|未知)\n 估算空闲物理核心数：(\d+|未知)\n\Z")


if __name__ == "__main__":
    unittest.main()
