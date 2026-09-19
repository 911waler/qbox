#!/usr/bin/env python3
"""
脚本名称：
    qbox-dopant-pdos.py

作用：
    从 QE projwfc.x 的原始 pdos_atm 文件中分析掺杂原子及其周围近邻
    原子的局域 PDOS。脚本会自动读取结构、寻找掺杂原子的最近邻，
    并输出“元素单原子平均”“掺杂原子自身”“近邻原子平均”以及
    “轨道分解”的 PDOS 数据和图。

适用问题：
    研究掺杂元素如何影响周围局域环境，例如：
      1. Al 自身的 s/p 轨道贡献是否明显；
      2. Al 最近邻 C 的 s/p 轨道是否相对普通 C 发生增强或削弱；
      3. 掺杂导致的能带变化主要来自掺杂原子，还是来自周围 C/Si 骨架态。

使用方法：
    1. 先完成 projwfc.x 计算，并保留原始 pdos.dat.pdos_atm#* 文件。
    2. 进入包含脚本的目录，通常是 ATOM_PDOS：
           cd ATOM_PDOS
    3. 运行最近邻分析：
           python3 qbox-dopant-pdos.py --structure ../333-Si95-wz.scf.in --dopant Al --nearest 4
    4. 如果原始 pdos_atm 文件在子目录中，例如 ATOM_PDOS/ATOM_PDOS：
           python3 qbox-dopant-pdos.py --structure ../333-Si95-wz.scf.in --pdos-dir ./ATOM_PDOS --dopant Al --nearest 4
    5. 也可以用距离截断选择近邻：
           python3 qbox-dopant-pdos.py --structure ../333-Si95-wz.scf.in --dopant Al --cutoff 2.3

主要参数：
    --structure FILE
        QE 输入文件或 CIF 结构文件。
    --pdos-dir DIR
        原始 pdos.dat.pdos_atm#* 文件所在目录。默认：当前目录。
    --dopant Al
        掺杂元素符号。默认：Al。
    --nearest 4
        选择距离掺杂原子最近的 N 个原子。
    --cutoff 2.3
        选择距离掺杂原子指定半径内的原子，单位 Angstrom。
    --output-dir DIR
        输出目录。默认：dopant_pdos_analysis。

输出文件含义：
    neighbor_report.txt
        掺杂原子编号、近邻原子编号、元素和距离，用于确认近邻壳层是否正确。
    avg_<元素>_per_atom.dat
        某元素所有原子的总 PDOS 除以该元素原子数，即该元素单原子平均 PDOS。
    avg_<元素>_<轨道>_per_atom.dat
        某元素某轨道的单原子平均 PDOS，例如 avg_C_p_per_atom.dat。
    dopant_<元素><编号>_total.dat
        掺杂原子自身所有轨道求和后的 PDOS，例如 dopant_Al216_total.dat。
    dopant_<元素><编号>_<轨道>.dat
        掺杂原子指定轨道 PDOS，例如 dopant_Al216_p.dat。
    nearest<N>_total.dat / nearest<N>_avg.dat
        最近 N 个近邻原子的 PDOS 总和 / 单原子平均。
    nearest<N>_<元素>_avg.dat
        最近邻中某种元素的单原子平均 PDOS，例如 nearest4_C_avg.dat。
    nearest<N>_<元素>_<轨道>_avg.dat
        最近邻中某种元素某轨道的单原子平均 PDOS，例如 nearest4_C_p_avg.dat。
    pdos_per_atom_average.png
        各元素单原子平均 PDOS 对比图。
    pdos_dopant_neighbors.png
        掺杂原子、近邻平均和整体平均 PDOS 对比图。
    pdos_orbital_environment.png
        掺杂原子和近邻原子的轨道分解 PDOS 对比图。
"""

from __future__ import annotations

import argparse
import math
import re
import shlex
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ORBITAL_ORDER = {"s": 0, "p": 1, "d": 2, "f": 3, "g": 4}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="分析 QE 掺杂体系中掺杂原子及近邻原子的 PDOS。")
    parser.add_argument("--structure", required=True, help="包含结构信息的 QE 输入文件或 CIF 文件。")
    parser.add_argument("--dopant", default="Al", help="掺杂元素符号。默认：Al。")
    parser.add_argument(
        "--nearest",
        type=int,
        default=4,
        help="每个掺杂原子周围选取的最近邻原子数。默认：4。",
    )
    parser.add_argument(
        "--cutoff",
        type=float,
        default=None,
        help="近邻距离截断，单位 Angstrom。设置后优先按截断半径选近邻。",
    )
    parser.add_argument(
        "--pdos-dir",
        default=".",
        help="包含原始 pdos.dat.pdos_atm#* 文件的目录。默认：当前目录。",
    )
    parser.add_argument(
        "--output-dir",
        default="dopant_pdos_analysis",
        help="输出目录。默认：dopant_pdos_analysis。",
    )
    parser.add_argument("--xmin", type=float, default=None, help="绘图 x 轴最小能量。")
    parser.add_argument("--xmax", type=float, default=None, help="绘图 x 轴最大能量。")
    parser.add_argument("--ymax", type=float, default=None, help="绘图 y 轴最大 DOS。")
    parser.add_argument("--dpi", type=int, default=300, help="输出图片 DPI。默认：300。")
    return parser.parse_args(argv)


def read_qe_structure(path: Path) -> tuple[np.ndarray, list[str], np.ndarray]:
    lines = path.read_text().splitlines()
    cell = None
    atoms: list[str] = []
    positions: list[list[float]] = []
    pos_unit = None

    for i, line in enumerate(lines):
        text = line.strip()
        upper = text.upper()
        if upper.startswith("CELL_PARAMETERS"):
            cell = np.array(
                [[float(x) for x in lines[i + j].split()[:3]] for j in range(1, 4)],
                dtype=float,
            )
        if upper.startswith("ATOMIC_POSITIONS"):
            pos_unit = "angstrom" if "ANGSTROM" in upper else "crystal" if "CRYSTAL" in upper else None
            j = i + 1
            while j < len(lines):
                row = lines[j].strip()
                if not row:
                    j += 1
                    continue
                key = row.split()[0].upper()
                if key in {"K_POINTS", "CELL_PARAMETERS", "ATOMIC_SPECIES", "ATOMIC_FORCES"} or row.startswith("&"):
                    break
                parts = row.split()
                if len(parts) >= 4:
                    atoms.append(parts[0])
                    positions.append([float(parts[1]), float(parts[2]), float(parts[3])])
                j += 1

    if cell is None:
        raise ValueError(f"未在结构文件中找到 CELL_PARAMETERS：{path}")
    if not atoms:
        raise ValueError(f"未在结构文件中找到 ATOMIC_POSITIONS：{path}")
    if pos_unit is None:
        raise ValueError("ATOMIC_POSITIONS 需要显式使用 angstrom 或 crystal 单位。")

    pos = np.array(positions, dtype=float)
    if pos_unit == "crystal":
        pos = pos @ cell
    return cell, atoms, pos


def cif_number(value: str) -> float:
    value = value.strip().strip("'\"")
    value = re.sub(r"\([^)]*\)$", "", value)
    return float(value)


def read_cif_structure(path: Path) -> tuple[np.ndarray, list[str], np.ndarray]:
    lines = path.read_text(errors="ignore").splitlines()
    scalar: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("_"):
            continue
        parts = shlex.split(stripped, comments=True, posix=True)
        if len(parts) >= 2:
            scalar[parts[0].lower()] = parts[1]

    required = (
        "_cell_length_a",
        "_cell_length_b",
        "_cell_length_c",
        "_cell_angle_alpha",
        "_cell_angle_beta",
        "_cell_angle_gamma",
    )
    missing = [key for key in required if key not in scalar]
    if missing:
        raise ValueError(f"CIF 缺少晶胞参数 {', '.join(missing)}：{path}")

    a, b, c = (cif_number(scalar[key]) for key in required[:3])
    alpha, beta, gamma = (math.radians(cif_number(scalar[key])) for key in required[3:])
    sin_gamma = math.sin(gamma)
    if abs(sin_gamma) < 1.0e-12:
        raise ValueError(f"CIF 晶胞 gamma 角无效：{path}")
    cx = c * math.cos(beta)
    cy = c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sin_gamma
    cz2 = c * c - cx * cx - cy * cy
    if cz2 <= 0:
        raise ValueError(f"CIF 晶胞参数无法构造三维晶格：{path}")
    cell = np.array(
        [
            [a, 0.0, 0.0],
            [b * math.cos(gamma), b * sin_gamma, 0.0],
            [cx, cy, math.sqrt(cz2)],
        ],
        dtype=float,
    )

    atoms: list[str] = []
    fractional: list[list[float]] = []
    i = 0
    while i < len(lines):
        if lines[i].strip().lower() != "loop_":
            i += 1
            continue
        i += 1
        headers: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("_"):
            headers.append(lines[i].strip().split()[0].lower())
            i += 1
        if not headers or "_atom_site_fract_x" not in headers:
            continue

        x_col = headers.index("_atom_site_fract_x")
        y_col = headers.index("_atom_site_fract_y")
        z_col = headers.index("_atom_site_fract_z")
        symbol_col = headers.index("_atom_site_type_symbol") if "_atom_site_type_symbol" in headers else None
        label_col = headers.index("_atom_site_label") if "_atom_site_label" in headers else None
        if symbol_col is None and label_col is None:
            raise ValueError(f"CIF 原子表缺少 type_symbol/label：{path}")

        while i < len(lines):
            row = lines[i].strip()
            if not row or row.startswith("#"):
                i += 1
                continue
            if row.lower() == "loop_" or row.startswith("_") or row.lower().startswith("data_"):
                break
            parts = shlex.split(row, comments=True, posix=True)
            if len(parts) >= len(headers):
                raw_symbol = parts[symbol_col if symbol_col is not None else label_col]
                match = re.match(r"([A-Z][a-z]?)", raw_symbol)
                if not match:
                    raise ValueError(f"CIF 中无法识别元素符号 '{raw_symbol}'：{path}")
                atoms.append(match.group(1))
                fractional.append(
                    [cif_number(parts[x_col]), cif_number(parts[y_col]), cif_number(parts[z_col])]
                )
            i += 1
        if atoms:
            break

    if not atoms:
        raise ValueError(f"未在 CIF 中找到分数坐标原子表：{path}")
    return cell, atoms, np.asarray(fractional, dtype=float) @ cell


def read_structure(path: Path) -> tuple[np.ndarray, list[str], np.ndarray]:
    text = path.read_text(errors="ignore")
    if re.search(r"(?im)^\s*CELL_PARAMETERS\b", text):
        return read_qe_structure(path)
    if path.suffix.lower() == ".cif" or "_cell_length_a" in text.lower():
        return read_cif_structure(path)
    raise ValueError(f"无法识别结构格式，需要 QE 输入或 CIF：{path}")


def minimum_image_distance(pos_i: np.ndarray, pos_j: np.ndarray, cell: np.ndarray) -> float:
    inv_cell = np.linalg.inv(cell)
    frac = (pos_j - pos_i) @ inv_cell
    frac -= np.rint(frac)
    disp = frac @ cell
    return float(np.linalg.norm(disp))


def read_pdos(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(path, comments="#")
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 2:
        raise ValueError(f"PDOS 文件至少需要两列：{path}")
    return data[:, 0], data[:, 1]


def collect_atom_pdos(pdos_dir: Path) -> dict[int, dict[str, object]]:
    pattern = re.compile(r".*pdos_atm#(\d+)\(([A-Za-z][A-Za-z0-9]*)\)_wfc#\d+\(([^)]+)\)$")
    atom_data: dict[int, dict[str, object]] = {}

    for path in sorted(pdos_dir.glob("*.pdos_atm#*")):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        atom_id = int(match.group(1))
        element = match.group(2)
        energy, dos = read_pdos(path)
        if atom_id not in atom_data:
            atom_data[atom_id] = {
                "element": element,
                "energy": energy,
                "dos": np.zeros_like(dos),
                "orbitals": defaultdict(lambda: np.zeros_like(dos)),
            }
        atom_data[atom_id]["dos"] = atom_data[atom_id]["dos"] + dos
        atom_data[atom_id]["orbitals"][match.group(3)] = atom_data[atom_id]["orbitals"][match.group(3)] + dos

    if not atom_data:
        raise ValueError(f"未找到可解析的 pdos_atm 文件：{pdos_dir}")
    return atom_data


def sum_atoms(atom_data: dict[int, dict[str, object]], atom_ids: list[int]) -> tuple[np.ndarray, np.ndarray]:
    if not atom_ids:
        raise ValueError("atom_ids 为空，无法求和。")
    energy = atom_data[atom_ids[0]]["energy"]
    total = np.zeros_like(energy)
    for atom_id in atom_ids:
        total += atom_data[atom_id]["dos"]
    return energy, total


def sum_atoms_orbital(
    atom_data: dict[int, dict[str, object]], atom_ids: list[int], orbital: str
) -> tuple[np.ndarray, np.ndarray]:
    if not atom_ids:
        raise ValueError("atom_ids 为空，无法求和。")
    energy = atom_data[atom_ids[0]]["energy"]
    total = np.zeros_like(energy)
    for atom_id in atom_ids:
        total += atom_data[atom_id]["orbitals"].get(orbital, np.zeros_like(energy))
    return energy, total


def orbitals_for_atoms(atom_data: dict[int, dict[str, object]], atom_ids: list[int]) -> list[str]:
    orbitals = set()
    for atom_id in atom_ids:
        orbitals.update(atom_data[atom_id]["orbitals"].keys())
    return sorted(orbitals, key=lambda orb: (ORBITAL_ORDER.get(orb, 99), orb))


def write_dat(path: Path, energy: np.ndarray, dos: np.ndarray) -> None:
    data = np.column_stack([energy, dos])
    np.savetxt(path, data, fmt="%12.6f %18.10e", header="E(eV) DOS", comments="# ")


def plot_curves(curves: list[tuple[str, np.ndarray, np.ndarray]], path: Path, title: str, args: argparse.Namespace) -> None:
    if not curves:
        return
    plt.figure(figsize=(8, 5.5))
    for label, energy, dos in curves:
        plt.plot(energy, dos, linewidth=1.5, label=label)
    plt.xlabel("Energy (eV)")
    plt.ylabel("DOS")
    plt.title(title)
    plt.xlim(left=args.xmin, right=args.xmax)
    if args.ymax is not None:
        plt.ylim(bottom=0, top=args.ymax)
    else:
        plt.ylim(bottom=0)
    plt.axvline(0.0, color="0.45", linestyle="--", linewidth=0.8)
    plt.legend(frameon=False, fontsize=9, ncol=2)
    plt.tight_layout()
    plt.savefig(path, dpi=args.dpi)
    plt.close()


def main(argv=None) -> None:
    args = parse_args(argv)
    structure = Path(args.structure).expanduser().resolve()
    pdos_dir = Path(args.pdos_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cell, atoms, positions = read_structure(structure)
    atom_data = collect_atom_pdos(pdos_dir)

    element_to_ids: dict[str, list[int]] = defaultdict(list)
    for atom_id, item in atom_data.items():
        element_to_ids[str(item["element"])].append(atom_id)

    dopant_ids = [i + 1 for i, element in enumerate(atoms) if element == args.dopant]
    if not dopant_ids:
        raise SystemExit(f"错误：结构中没有找到掺杂元素 {args.dopant}")

    structure_label = structure.name or "<structure>"
    pdos_label = pdos_dir.name or "<pdos>"
    report_lines = [
        f"结构文件: {structure_label}",
        f"PDOS目录: {pdos_label}",
        f"掺杂元素: {args.dopant}",
        "",
    ]

    average_curves = []
    orbital_curves = []
    for element in sorted(element_to_ids):
        ids = sorted(element_to_ids[element])
        energy, total = sum_atoms(atom_data, ids)
        avg = total / len(ids)
        write_dat(output_dir / f"avg_{element}_per_atom.dat", energy, avg)
        average_curves.append((f"{element} avg/atom", energy, avg))

        for orbital in orbitals_for_atoms(atom_data, ids):
            energy, orbital_total = sum_atoms_orbital(atom_data, ids, orbital)
            orbital_avg = orbital_total / len(ids)
            write_dat(output_dir / f"avg_{element}_{orbital}_per_atom.dat", energy, orbital_avg)

    neighbor_curves = []
    all_selected_neighbors: list[int] = []

    for dopant_id in dopant_ids:
        if dopant_id not in atom_data:
            report_lines.append(f"警告：掺杂原子 #{dopant_id} 没有对应 PDOS 文件。")
            continue

        distances = []
        dopant_pos = positions[dopant_id - 1]
        for atom_id, element in enumerate(atoms, start=1):
            if atom_id == dopant_id:
                continue
            dist = minimum_image_distance(dopant_pos, positions[atom_id - 1], cell)
            distances.append((dist, atom_id, element))
        distances.sort()

        if args.cutoff is not None:
            neighbors = [(d, i, e) for d, i, e in distances if d <= args.cutoff]
            tag = f"cutoff{args.cutoff:g}A"
        else:
            neighbors = distances[: args.nearest]
            tag = f"nearest{args.nearest}"

        neighbor_ids = [atom_id for _, atom_id, _ in neighbors if atom_id in atom_data]
        all_selected_neighbors.extend(neighbor_ids)

        energy, dopant_dos = sum_atoms(atom_data, [dopant_id])
        write_dat(output_dir / f"dopant_{args.dopant}{dopant_id}_total.dat", energy, dopant_dos)
        neighbor_curves.append((f"{args.dopant}{dopant_id}", energy, dopant_dos))

        for orbital in orbitals_for_atoms(atom_data, [dopant_id]):
            energy, dopant_orbital = sum_atoms_orbital(atom_data, [dopant_id], orbital)
            write_dat(output_dir / f"dopant_{args.dopant}{dopant_id}_{orbital}.dat", energy, dopant_orbital)
            orbital_curves.append((f"{args.dopant}{dopant_id}-{orbital}", energy, dopant_orbital))

        report_lines.append(f"掺杂原子 #{dopant_id} ({args.dopant})")
        report_lines.append("近邻原子:")
        for dist, atom_id, element in neighbors:
            report_lines.append(f"  #{atom_id:4d}  {element:2s}  distance = {dist:8.4f} A")
        report_lines.append("")

        if neighbor_ids:
            energy, neighbor_total = sum_atoms(atom_data, neighbor_ids)
            write_dat(output_dir / f"{tag}_total.dat", energy, neighbor_total)
            write_dat(output_dir / f"{tag}_avg.dat", energy, neighbor_total / len(neighbor_ids))
            neighbor_curves.append((f"{tag} avg", energy, neighbor_total / len(neighbor_ids)))

            by_element: dict[str, list[int]] = defaultdict(list)
            for _, atom_id, element in neighbors:
                if atom_id in atom_data:
                    by_element[element].append(atom_id)
            for element, ids in sorted(by_element.items()):
                energy, total = sum_atoms(atom_data, ids)
                avg = total / len(ids)
                write_dat(output_dir / f"{tag}_{element}_avg.dat", energy, avg)
                neighbor_curves.append((f"{tag} {element} avg", energy, avg))

                for orbital in orbitals_for_atoms(atom_data, ids):
                    energy, orbital_total = sum_atoms_orbital(atom_data, ids, orbital)
                    orbital_avg = orbital_total / len(ids)
                    write_dat(output_dir / f"{tag}_{element}_{orbital}_avg.dat", energy, orbital_avg)
                    orbital_curves.append((f"{tag} {element}-{orbital} avg", energy, orbital_avg))

    for label, energy, dos in average_curves:
        neighbor_curves.append((label, energy, dos))

    (output_dir / "neighbor_report.txt").write_text("\n".join(report_lines) + "\n")
    plot_curves(average_curves, output_dir / "pdos_per_atom_average.png", "Per-atom averaged PDOS", args)
    plot_curves(neighbor_curves, output_dir / "pdos_dopant_neighbors.png", "Dopant and nearest-neighbor PDOS", args)
    plot_curves(orbital_curves, output_dir / "pdos_orbital_environment.png", "Orbital-resolved dopant environment PDOS", args)

    print(f"分析完成，输出目录：{output_dir}")
    print(f"近邻报告：{output_dir / 'neighbor_report.txt'}")
    print("建议重点比较：")
    print(f"  dopant_{args.dopant}<编号>_total.dat")
    print(f"  nearest{args.nearest}_avg.dat 或 cutoff<距离>A_avg.dat")
    print("  avg_C_per_atom.dat / avg_Si_per_atom.dat 等整体平均结果")


if __name__ == "__main__":
    main()
