#!/usr/bin/env python3
"""
脚本名称：
    plot-pdos-QE.py

作用：
    对 sumdos.sh 汇总得到的 QE PDOS 数据作图，用于快速比较不同元素
    以及不同元素-轨道对总态密度的贡献。

使用方法：
    1. 先运行 sumdos.sh，确保当前目录已有 *_tot.dat 和 元素_轨道.dat。
    2. 在该目录运行：
           python3 plot-pdos-QE.py
    3. 如果数据不在当前目录，可指定目录：
           python3 plot-pdos-QE.py --input-dir ATOM_PDOS
    4. 如果希望输出文件带前缀：
           python3 plot-pdos-QE.py --output-prefix SiC_Al

输入文件：
    *_tot.dat
        元素总 DOS，例如 Si_tot.dat、C_tot.dat、Al_tot.dat。
    元素_轨道.dat
        元素-轨道 DOS，例如 Si_s.dat、Si_p.dat、C_p.dat、Al_s.dat。

输出文件：
    element_dos.png
        元素 DOS 图。每个 *_tot.dat 文件对应一条线，所有元素画在同一张图。
    orbital_dos.png
        轨道 DOS 图。每个 元素_轨道.dat 文件对应一条线，所有元素和轨道画在同一张图。
    combined_pdos.png
        组合 PDOS 图。轨道 DOS 以线条显示；元素总 DOS 用半透明填充显示，
        用于同时观察总贡献和轨道分解贡献。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ORBITAL_ORDER = {"s": 0, "p": 1, "d": 2, "f": 3, "g": 4}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="绘制 sumdos.sh 输出的元素 DOS 和轨道 DOS。")
    parser.add_argument(
        "--input-dir",
        default=".",
        help="包含 *_tot.dat 和 元素_轨道.dat 的目录。默认：当前目录。",
    )
    parser.add_argument(
        "--output-prefix",
        default="",
        help="输出图片前缀。例如 SiC_Al 会生成 SiC_Al_element_dos.png。",
    )
    parser.add_argument(
        "--xmin",
        type=float,
        default=None,
        help="x 轴显示的最小能量。",
    )
    parser.add_argument(
        "--xmax",
        type=float,
        default=None,
        help="x 轴显示的最大能量。",
    )
    parser.add_argument(
        "--ymax",
        type=float,
        default=None,
        help="y 轴显示的最大 DOS。",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="输出图片 DPI。默认：300。",
    )
    parser.add_argument(
        "--format",
        default="png",
        choices=("png", "pdf", "svg"),
        help="输出图片格式。默认：png。",
    )
    parser.add_argument(
        "--fermi-energy",
        type=float,
        default=None,
        help="Fermi level，单位 eV。设置后横坐标绘制为 E - E_F。",
    )
    parser.add_argument(
        "--fermi-from",
        nargs="*",
        default=None,
        help="从 QE 输出文件读取 Fermi level，例如 ../../nscf.out ../../scf.out。",
    )
    parser.add_argument(
        "--no-shift-fermi",
        action="store_true",
        help="即使提供 Fermi level，也保留原始绝对能量坐标。",
    )
    parser.add_argument(
        "--zero-reference",
        default="fermi",
        choices=("fermi", "cbm", "vbm", "none"),
        help="能量零点：fermi 为 E_F 归零，cbm 为 CBM 归零，vbm 为 VBM 归零，none 保留绝对能量。默认：fermi。",
    )
    parser.add_argument(
        "--cbm-energy",
        type=float,
        default=None,
        help="手动指定 CBM 能量，单位 eV。设置 --zero-reference cbm 时优先使用。",
    )
    parser.add_argument(
        "--vbm-energy",
        type=float,
        default=None,
        help="手动指定 VBM 能量，单位 eV。设置 --zero-reference vbm 时优先使用。",
    )
    parser.add_argument(
        "--band-edge-from",
        nargs="*",
        default=None,
        help="从 QE 输出文件读取 VBM/CBM，例如 ../../nscf.out ../../scf.out。默认使用 --fermi-from。",
    )
    parser.add_argument(
        "--occupation-threshold",
        type=float,
        default=0.5,
        help="从 QE 占据数判断占据/未占据态的阈值。默认：0.5。",
    )
    parser.add_argument(
        "--cbm-threshold",
        type=float,
        default=1e-4,
        help="无法从 QE 本征值读取带边时，从 DOS 数据估计带边的最低绝对 DOS 阈值。默认：1e-4。",
    )
    return parser.parse_args(argv)


def natural_key(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def orbital_key(label: str) -> tuple[str, int, str]:
    element, orbital = label.split("_", 1)
    return (element, ORBITAL_ORDER.get(orbital, 99), orbital)


def read_dos_file(path: Path) -> tuple[np.ndarray, np.ndarray]:
    try:
        data = np.loadtxt(path, comments="#")
    except ValueError as exc:
        raise ValueError(f"无法读取数据文件：{path}") from exc

    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 2:
        raise ValueError(f"文件至少需要两列数据：{path}")

    return data[:, 0], data[:, 1]


def read_pdos_for_edge(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(path, comments="#")
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] >= 3:
        return data[:, 0], data[:, 2]
    if data.shape[1] >= 2:
        return data[:, 0], data[:, 1]
    raise ValueError(f"文件至少需要两列数据：{path}")


def read_edge_pdos_source(
    input_dir: Path,
    element_files: list[tuple[str, Path]],
) -> tuple[np.ndarray | None, np.ndarray | None, Path | None]:
    total_path = input_dir / "pdos.dat.pdos_tot"
    source_files = [total_path] if total_path.exists() else [path for _, path in element_files]
    for path in source_files:
        try:
            energy, dos = read_pdos_for_edge(path)
        except Exception:
            continue
        if energy.size and dos.size:
            return energy, dos, path
    return None, None, None


def read_fermi_energy(paths: list[str] | None) -> tuple[float | None, Path | None]:
    if not paths:
        return None, None

    patterns = (
        re.compile(r"the Fermi energy is\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)", re.IGNORECASE),
        re.compile(r"highest occupied.*?([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+ev", re.IGNORECASE),
    )

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            matches = pattern.findall(text)
            if matches:
                return float(matches[-1]), path

    return None, None


FLOAT_PATTERN = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[Ee][-+]?\d+)?")


def parse_floats(text: str) -> list[float]:
    return [float(value) for value in FLOAT_PATTERN.findall(text)]


def read_band_edges(
    paths: list[str] | None,
    occupation_threshold: float,
) -> tuple[float | None, float | None, Path | None]:
    if not paths:
        return None, None, None

    explicit_pattern = re.compile(
        r"highest occupied,\s*lowest unoccupied level\s*\(ev\):\s*"
        r"([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)",
        re.IGNORECASE,
    )

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8", errors="ignore")
        matches = explicit_pattern.findall(text)
        if matches:
            vbm, cbm = matches[-1]
            return float(vbm), float(cbm), path

        vbm: float | None = None
        cbm: float | None = None
        energies: list[float] = []
        occupations: list[float] = []
        mode: str | None = None

        for line in text.splitlines():
            lower = line.lower()
            if "bands (ev)" in lower:
                energies = []
                occupations = []
                mode = "bands"
                continue
            if mode == "bands" and "occupation numbers" in lower:
                mode = "occupations"
                continue
            if mode == "bands":
                values = parse_floats(line)
                if values:
                    energies.extend(values)
                continue
            if mode == "occupations":
                values = parse_floats(line)
                if values:
                    occupations.extend(values)
                if energies and len(occupations) >= len(energies):
                    for energy, occupation in zip(energies, occupations):
                        if occupation > occupation_threshold:
                            vbm = energy if vbm is None else max(vbm, energy)
                        else:
                            cbm = energy if cbm is None else min(cbm, energy)
                    energies = []
                    occupations = []
                    mode = None

        if vbm is not None or cbm is not None:
            return vbm, cbm, path

    return None, None, None


def dos_gap_width(energy: np.ndarray, dos: np.ndarray, fermi_coord: float, threshold: float) -> float:
    if not energy.size or not dos.size:
        return -1.0
    if fermi_coord < float(np.nanmin(energy)) or fermi_coord > float(np.nanmax(energy)):
        return -1.0

    max_dos = float(np.nanmax(dos)) if dos.size else 0.0
    effective_threshold = max(threshold, max_dos * 1e-3)
    idx = int(np.argmin(np.abs(energy - fermi_coord)))
    if dos[idx] > effective_threshold:
        return 0.0

    left = idx
    while left > 0 and dos[left - 1] <= effective_threshold:
        left -= 1
    right = idx
    last = len(dos) - 1
    while right < last and dos[right + 1] <= effective_threshold:
        right += 1
    return float(energy[right] - energy[left])


def infer_pdos_fermi_coordinate(
    input_dir: Path,
    fermi_energy: float,
    threshold: float,
    element_files: list[tuple[str, Path]],
) -> tuple[float, Path | None, str]:
    energy, dos, source = read_edge_pdos_source(input_dir, element_files)
    if energy is None or dos is None:
        return fermi_energy, None, "absolute"

    candidates: list[tuple[float, float, str]] = []
    for coord, label in ((fermi_energy, "absolute"), (0.0, "fermi_shifted")):
        width = dos_gap_width(energy, dos, coord, threshold)
        if width >= 0.0:
            candidates.append((width, coord, label))

    if not candidates:
        return fermi_energy, source, "absolute"

    width, coord, label = max(candidates, key=lambda item: item[0])
    return coord, source, label


def convert_absolute_edge_to_pdos_axis(
    edge_energy: float | None,
    fermi_energy: float,
    fermi_coord: float,
) -> float | None:
    if edge_energy is None:
        return None
    if abs(fermi_coord) < 1e-6 and abs(fermi_energy) > 1e-6:
        return edge_energy - fermi_energy
    return edge_energy


def estimate_dos_edge_energy(
    input_dir: Path,
    fermi_coord: float,
    threshold: float,
    element_files: list[tuple[str, Path]],
    edge: str,
) -> tuple[float | None, Path | None]:
    candidates: list[tuple[float, Path]] = []
    total_path = input_dir / "pdos.dat.pdos_tot"
    source_files = [total_path] if total_path.exists() else [path for _, path in element_files]

    for path in source_files:
        try:
            energy, dos = read_pdos_for_edge(path)
        except Exception:
            continue
        max_dos = float(np.nanmax(dos)) if dos.size else 0.0
        effective_threshold = max(threshold, max_dos * 1e-3)
        if edge == "cbm":
            mask = (energy >= fermi_coord) & (dos > effective_threshold)
        else:
            mask = (energy <= fermi_coord) & (dos > effective_threshold)
        if np.any(mask):
            indices = np.where(mask)[0]
            idx = int(indices[0] if edge == "cbm" else indices[-1])
            candidates.append((float(energy[idx]), path))

    if not candidates:
        return None, None

    if edge == "cbm":
        return min(candidates, key=lambda item: item[0])
    return max(candidates, key=lambda item: item[0])


def collect_files(input_dir: Path) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]]]:
    element_files: list[tuple[str, Path]] = []
    orbital_files: list[tuple[str, Path]] = []

    for path in input_dir.glob("*.dat"):
        name = path.name
        if name.endswith("_tot.dat"):
            label = name[: -len("_tot.dat")]
            element_files.append((label, path))
            continue

        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)_([A-Za-z0-9+-]+)\.dat", name)
        if match:
            label = f"{match.group(1)}_{match.group(2)}"
            orbital_files.append((label, path))

    element_files.sort(key=lambda item: natural_key(item[0]))
    orbital_files.sort(key=lambda item: orbital_key(item[0]))
    return element_files, orbital_files


def output_name(prefix: str, stem: str, fmt: str) -> str:
    return f"{prefix}_{stem}.{fmt}" if prefix else f"{stem}.{fmt}"


def plot_dos(
    files: list[tuple[str, Path]],
    title: str,
    output_path: Path,
    xmin: float | None,
    xmax: float | None,
    ymax: float | None,
    dpi: int,
    reference_energy: float | None,
    reference_label: str | None,
) -> None:
    if not files:
        print(f"跳过：未找到 {title} 对应的数据文件。")
        return

    plt.figure(figsize=(8, 5.5))

    for label, path in files:
        energy, dos = read_dos_file(path)
        if reference_energy is not None:
            energy = energy - reference_energy
        plt.plot(energy, dos, linewidth=1.6, label=label)

    plt.xlabel(f"Energy - {reference_label} (eV)" if reference_label else "Energy (eV)")
    plt.ylabel("DOS")
    plt.title(title)
    plt.xlim(left=xmin, right=xmax)
    if ymax is not None:
        plt.ylim(bottom=0, top=ymax)
    else:
        plt.ylim(bottom=0)
    plt.axvline(0.0, color="0.45", linestyle="--", linewidth=0.8)
    plt.legend(frameon=False, fontsize=9, ncol=2)
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi)
    plt.close()
    print(f"已保存：{output_path}")


def plot_combined_dos(
    element_files: list[tuple[str, Path]],
    orbital_files: list[tuple[str, Path]],
    output_path: Path,
    xmin: float | None,
    xmax: float | None,
    ymax: float | None,
    dpi: int,
    reference_energy: float | None,
    reference_label: str | None,
) -> None:
    if not element_files and not orbital_files:
        print("跳过：未找到组合 PDOS 图对应的数据文件。")
        return

    plt.figure(figsize=(8, 5.8))
    color_cycle = plt.rcParams["axes.prop_cycle"].by_key().get("color", [])

    for idx, (label, path) in enumerate(element_files):
        energy, dos = read_dos_file(path)
        if reference_energy is not None:
            energy = energy - reference_energy
        color = color_cycle[idx % len(color_cycle)] if color_cycle else None
        plt.plot(energy, dos, color=color, alpha=0.0, linewidth=0.1)
        plt.fill_between(
            energy,
            dos,
            0,
            color=color,
            alpha=0.18,
            linewidth=0,
            label=f"{label} total",
        )

    for label, path in orbital_files:
        energy, dos = read_dos_file(path)
        if reference_energy is not None:
            energy = energy - reference_energy
        plt.plot(energy, dos, linewidth=1.3, label=label)

    plt.xlabel(f"Energy - {reference_label} (eV)" if reference_label else "Energy (eV)")
    plt.ylabel("DOS")
    plt.title("Orbital-resolved DOS with Element Totals")
    plt.xlim(left=xmin, right=xmax)
    if ymax is not None:
        plt.ylim(bottom=0, top=ymax)
    else:
        plt.ylim(bottom=0)
    plt.axvline(0.0, color="0.45", linestyle="--", linewidth=0.8)
    plt.legend(frameon=False, fontsize=8, ncol=2)
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi)
    plt.close()
    print(f"已保存：{output_path}")


def main(argv=None) -> None:
    args = parse_args(argv)
    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.is_dir():
        raise SystemExit(f"错误：输入目录不存在：{input_dir}")

    element_files, orbital_files = collect_files(input_dir)
    if not element_files and not orbital_files:
        raise SystemExit(
            f"错误：未在 {input_dir} 中找到 sumdos.sh 输出文件：*_tot.dat 或 元素_轨道.dat"
        )

    element_output = input_dir / output_name(args.output_prefix, "element_dos", args.format)
    orbital_output = input_dir / output_name(args.output_prefix, "orbital_dos", args.format)
    combined_output = input_dir / output_name(args.output_prefix, "combined_pdos", args.format)

    zero_reference = "none" if args.no_shift_fermi else args.zero_reference
    reference_energy = None
    reference_label = None
    fermi_energy = args.fermi_energy
    fermi_file = None
    edge_paths = args.band_edge_from if args.band_edge_from is not None else args.fermi_from

    if zero_reference != "none":
        if fermi_energy is None:
            fermi_energy, fermi_file = read_fermi_energy(args.fermi_from)
        if fermi_energy is None:
            print("警告：未能读取 Fermi level，将保留原始绝对能量坐标。")
            zero_reference = "none"

    if zero_reference == "fermi":
        reference_energy = fermi_energy
        reference_label = "$E_F$"
        if fermi_file is not None:
            print(f"已读取 Fermi level: {fermi_energy:.6f} eV，来源：{fermi_file}")
        else:
            print(f"使用 Fermi level: {fermi_energy:.6f} eV")
        print("横坐标已平移为 E - E_F。")
    elif zero_reference in {"cbm", "vbm"}:
        vbm_energy = args.vbm_energy
        cbm_energy = args.cbm_energy
        edge_file = None
        dos_edge_file = None
        pdos_fermi_coord, pdos_axis_file, pdos_axis_mode = infer_pdos_fermi_coordinate(
            input_dir,
            fermi_energy,
            args.cbm_threshold,
            element_files,
        )

        if (zero_reference == "cbm" and cbm_energy is None) or (zero_reference == "vbm" and vbm_energy is None):
            parsed_vbm, parsed_cbm, edge_file = read_band_edges(edge_paths, args.occupation_threshold)
            if vbm_energy is None:
                vbm_energy = convert_absolute_edge_to_pdos_axis(parsed_vbm, fermi_energy, pdos_fermi_coord)
            if cbm_energy is None:
                cbm_energy = convert_absolute_edge_to_pdos_axis(parsed_cbm, fermi_energy, pdos_fermi_coord)

        target_label = "CBM" if zero_reference == "cbm" else "VBM"
        dos_edge_energy, dos_edge_file = estimate_dos_edge_energy(
            input_dir,
            pdos_fermi_coord,
            args.cbm_threshold,
            element_files,
            zero_reference,
        )
        target_energy = dos_edge_energy if dos_edge_energy is not None else (cbm_energy if zero_reference == "cbm" else vbm_energy)

        if target_energy is None:
            print(f"警告：未能读取或估计 {target_label}，将改为 Fermi level 归零。")
            reference_energy = pdos_fermi_coord
            reference_label = "$E_F$"
        else:
            reference_energy = target_energy
            reference_label = target_label
            if fermi_file is not None:
                print(f"已读取 Fermi level: {fermi_energy:.6f} eV，来源：{fermi_file}")
            if pdos_axis_file is not None:
                if pdos_axis_mode == "fermi_shifted":
                    print(f"检测到 PDOS 横坐标已接近 E - E_F 标尺，PDOS 中 Fermi 坐标按 0.000000 eV 处理，来源：{pdos_axis_file}")
                else:
                    print(f"检测到 PDOS 横坐标使用绝对能量标尺，PDOS 中 Fermi 坐标为 {pdos_fermi_coord:.6f} eV，来源：{pdos_axis_file}")
            if dos_edge_file is not None:
                print(f"已从 PDOS 曲线估计 {target_label}: {target_energy:.6f} eV，来源：{dos_edge_file}")
                eigen_edge = cbm_energy if zero_reference == "cbm" else vbm_energy
                if eigen_edge is not None and abs(eigen_edge - target_energy) > 0.2:
                    print(f"提示：QE 本征值/占据数给出的 {target_label} 为 {eigen_edge:.6f} eV，和 PDOS 曲线带边相差 {abs(eigen_edge - target_energy):.3f} eV。当前绘图按 PDOS 曲线带边对齐。")
            elif edge_file is not None:
                print(f"已从 QE 本征值/占据数读取 {target_label}: {target_energy:.6f} eV，来源：{edge_file}")
            else:
                print(f"使用 {target_label}: {target_energy:.6f} eV")
            print(f"横坐标已平移为 E - {target_label}。")

    plot_dos(
        element_files,
        "Element-resolved DOS",
        element_output,
        args.xmin,
        args.xmax,
        args.ymax,
        args.dpi,
        reference_energy,
        reference_label,
    )
    plot_dos(
        orbital_files,
        "Orbital-resolved DOS",
        orbital_output,
        args.xmin,
        args.xmax,
        args.ymax,
        args.dpi,
        reference_energy,
        reference_label,
    )
    plot_combined_dos(
        element_files,
        orbital_files,
        combined_output,
        args.xmin,
        args.xmax,
        args.ymax,
        args.dpi,
        reference_energy,
        reference_label,
    )


if __name__ == "__main__":
    main()
