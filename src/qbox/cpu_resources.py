"""Physical CPU capacity and a short, conservative idle-capacity estimate."""

import argparse
from fractions import Fraction
from pathlib import Path
import time


def _cpu_list(text):
    cpus = set()
    for part in text.strip().split(","):
        bounds = [int(value) for value in part.split("-")]
        if len(bounds) not in (1, 2) or min(bounds) < 0 or bounds[0] > bounds[-1]:
            raise ValueError("invalid CPU list")
        cpus.update(range(bounds[0], bounds[-1] + 1))
    return cpus


def physical_core_groups(sys_cpu=Path("/sys/devices/system/cpu"), cpuinfo=Path("/proc/cpuinfo")):
    """Group online logical CPUs by physical core; return None if unknown."""
    try:
        online = _cpu_list((sys_cpu / "online").read_text())
    except (OSError, ValueError):
        online = None
    try:
        if not online:
            raise ValueError("online CPU list unavailable")
        groups = set()
        for cpu in online:
            siblings = _cpu_list((sys_cpu / f"cpu{cpu}/topology/thread_siblings_list").read_text())
            if cpu not in siblings:
                raise ValueError("inconsistent CPU topology")
            groups.add(tuple(sorted(siblings & online)))
        if sum(map(len, groups)) != len(online):
            raise ValueError("overlapping CPU topology")
        return sorted(groups)
    except (OSError, ValueError):
        pass

    # /proc/cpuinfo retains socket/core identifiers on systems without sysfs.
    # Never substitute nproc/os.cpu_count(): those can include SMT siblings.
    try:
        by_core = {}
        seen = set()
        for block in cpuinfo.read_text().strip().split("\n\n"):
            fields = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
            fields = {key.strip(): value.strip() for key, value in fields.items()}
            cpu = int(fields["processor"])
            if online is not None and cpu not in online:
                continue
            key = (int(fields["physical id"]), int(fields["core id"]))
            by_core.setdefault(key, []).append(cpu)
            seen.add(cpu)
        if not seen or (online is not None and seen != online):
            return None
        return sorted(tuple(sorted(cpus)) for cpus in by_core.values())
    except (OSError, ValueError, KeyError):
        return None


def read_cpu_times(stat=Path("/proc/stat")):
    times = {}
    for line in stat.read_text().splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith("cpu") or not fields[0][3:].isdigit():
            continue
        values = [int(value) for value in fields[1:9]]
        if len(values) < 4 or min(values) < 0:
            raise ValueError("incomplete CPU counters")
        # guest/guest_nice already contribute to user/nice; exclude them.
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        times[int(fields[0][3:])] = (sum(values), idle)
    return times


def estimate_idle_cores(groups, before, after):
    """Sum idle core equivalents, rounded down; the busiest SMT sibling wins."""
    idle_cores = Fraction(0)
    for group in groups:
        idle_fractions = []
        for cpu in group:
            if cpu not in before or cpu not in after:
                return None
            total = after[cpu][0] - before[cpu][0]
            idle = after[cpu][1] - before[cpu][1]
            if total <= 0 or idle < 0 or idle > total:
                return None
            idle_fractions.append(Fraction(idle, total))
        idle_cores += min(idle_fractions)
    return int(idle_cores)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--physical-count", action="store_true")
    args = parser.parse_args()
    groups = physical_core_groups()
    total = len(groups) if groups else None
    if args.physical_count:
        if total is None:
            return 1
        print(total)
        return 0

    idle = None
    if groups:
        try:
            before = read_cpu_times()
            time.sleep(0.25)
            idle = estimate_idle_cores(groups, before, read_cpu_times())
        except (OSError, ValueError):
            pass
    print(f" 当前机器物理核心总数：{total if total is not None else '未知'}")
    print(f" 估算空闲物理核心数：{idle if idle is not None else '未知'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
