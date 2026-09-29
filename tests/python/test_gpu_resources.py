"""GPU guidance reports devices and idle devices, never CPU capacity."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from qbox.gpu_resources import gpu_counts


ROOT = Path(__file__).resolve().parents[2]


def gpu(utilization="0", processes="", mode="Default"):
    return (f"<gpu><compute_mode>{mode}</compute_mode>"
            f"<utilization><gpu_util>{utilization} %</gpu_util></utilization>"
            f"<processes>{processes}</processes></gpu>")


def snapshot(*devices):
    return "<nvidia_smi_log>" + "".join(devices) + "</nvidia_smi_log>"


class GpuResourceTests(unittest.TestCase):
    def query(self, xml):
        with patch("qbox.gpu_resources.subprocess.run") as run:
            run.return_value.stdout = xml
            result = gpu_counts()
            self.assertEqual(run.call_args.args[0], ["nvidia-smi", "-q", "-x"])
            self.assertLessEqual(run.call_args.kwargs["timeout"], 5)
            self.assertTrue(run.call_args.kwargs["check"])
            return result

    def test_idle_requires_zero_utilization_and_no_compute_process(self):
        busy_process = "<process_info><type>C</type><pid>42</pid></process_info>"
        self.assertEqual(self.query(snapshot(
            gpu(), gpu(processes=busy_process), gpu("50"), gpu(mode="Prohibited")
        )), (4, 1))

    def test_graphics_compute_process_is_busy_even_when_utilization_is_zero(self):
        process = "<process_info><type>C+G</type><pid>42</pid></process_info>"
        self.assertEqual(self.query(snapshot(gpu(processes=process))), (1, 0))

    def test_empty_device_list_means_zero_gpus(self):
        self.assertEqual(self.query(snapshot()), (0, 0))

    def test_unsupported_utilization_and_missing_process_data_are_unknown(self):
        for device in (gpu("N/A"), gpu().replace("<processes></processes>", ""),
                       gpu(processes="N/A"), gpu(processes="<process_info/>")):
            with self.subTest(device=device):
                self.assertEqual(self.query(snapshot(device)), (1, None))

    def test_malformed_output_is_unknown_not_zero(self):
        for xml in ("", "permission denied", "<unexpected/>"):
            with self.subTest(xml=xml):
                self.assertEqual(self.query(xml), (None, None))

    def test_missing_driver_query_failure_and_timeout_are_unknown(self):
        for error in (FileNotFoundError(), subprocess.CalledProcessError(1, "nvidia-smi"),
                      subprocess.TimeoutExpired("nvidia-smi", 3)):
            with self.subTest(error=error), patch("qbox.gpu_resources.subprocess.run", side_effect=error):
                self.assertEqual(gpu_counts(), (None, None))

    def test_gpu_shell_prompt_uses_gpu_counts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "nvidia-smi"
            binary.write_text("#!/bin/sh\ncat <<'XML'\n" + snapshot(gpu(), gpu("40")) + "\nXML\n")
            binary.chmod(0o755)
            env = dict(os.environ, QBOX_PYTHON=sys.executable,
                       PATH=directory + os.pathsep + os.environ["PATH"])
            for key in ("BASH_FUNC_module%%", "BASH_FUNC_ml%%"):
                env.pop(key, None)
            result = subprocess.run(
                ["bash", "-c", 'QBOX_TEST_MODE=1 source "$1"; '
                 'qe_runtime_accelerator() { echo gpu; }; qe_report_compute_resources; printf 4',
                 "gpu-report", str(ROOT / "qbox")],
                env=env, capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "4")
            self.assertEqual(result.stderr, " 当前机器 GPU 数量：2\n 空闲 GPU 数量：1\n")

    def test_gpu_probe_failure_never_falls_back_to_cpu_information(self):
        env = dict(os.environ, QBOX_PYTHON=sys.executable)
        for key in ("BASH_FUNC_module%%", "BASH_FUNC_ml%%"):
            env.pop(key, None)
        result = subprocess.run(
            ["bash", "-c", 'QBOX_TEST_MODE=1 source "$1"; '
             'qe_runtime_accelerator() { echo gpu; }; qbox_python() { return 1; }; '
             'qe_report_compute_resources', "gpu-report", str(ROOT / "qbox")],
            env=env, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, " 当前机器 GPU 数量：未知\n 空闲 GPU 数量：未知\n")


if __name__ == "__main__":
    unittest.main()
