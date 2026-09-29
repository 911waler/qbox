"""Machine GPU counts and a conservative snapshot of idle NVIDIA devices."""

import subprocess
import xml.etree.ElementTree as ET


def _is_idle(device):
    mode = device.findtext("compute_mode", "").strip().lower().replace("_", " ")
    if mode == "prohibited":
        return False
    if mode not in ("default", "exclusive process", "exclusive thread"):
        return None
    processes = device.find("processes")
    if processes is None or (processes.text or "").strip():
        return None
    for process in processes.findall("process_info"):
        kind = process.findtext("type", "").strip().upper()
        if "C" in kind or "M" in kind:
            # A compute context can be occupied even during a zero-utilization sample.
            return False
        if kind != "G":
            return None
    try:
        utilization = int(device.findtext("utilization/gpu_util", "").strip().removesuffix("%").strip())
    except ValueError:
        return None
    if not 0 <= utilization <= 100:
        return None
    return utilization == 0


def gpu_counts():
    """Count physical devices reported by the driver; unknown is never zero."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "-q", "-x"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=True, timeout=3,
        )
        root = ET.fromstring(result.stdout)
        if root.tag != "nvidia_smi_log":
            return None, None
    except (OSError, subprocess.SubprocessError, ET.ParseError, ValueError):
        return None, None
    devices = root.findall("gpu")
    idle = [_is_idle(device) for device in devices]
    return len(devices), None if None in idle else sum(idle)


def main():
    total, idle = gpu_counts()
    print(f" 当前机器 GPU 数量：{total if total is not None else '未知'}")
    print(f" 空闲 GPU 数量：{idle if idle is not None else '未知'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
