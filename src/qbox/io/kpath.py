"""Generate a QE K_POINTS crystal_b path from a CIF file."""

import argparse
import math
import re
import shlex
import sys
import warnings


import seekpath

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="从 CIF 文件生成 Quantum ESPRESSO K_POINTS {crystal_b} 高对称路径。"
    )
    parser.add_argument("cif", help="输入 CIF 文件路径")
    parser.add_argument(
        "-n",
        "--points",
        default=20,
        type=int,
        help="每段高对称路径的插值点数，默认：20",
    )
    parser.add_argument(
        "--mode",
        choices=("fixed", "spacing"),
        default="fixed",
        help="K 路径采样方式：fixed 为每段固定插值点数；spacing 为按倒空间间距自动决定每段点数。",
    )
    parser.add_argument(
        "--spacing",
        default=0.02,
        type=float,
        help="--mode spacing 时使用的目标 K 点间距，单位 1/Angstrom，默认：0.02",
    )
    return parser.parse_args(argv)


def load_with_pymatgen(cif_path):
    try:
        from pymatgen.core import Structure
    except Exception:
        try:
            from pymatgen.core.structure import Structure
        except Exception as exc:
            raise ImportError("pymatgen Structure API 不可用") from exc

    structure = Structure.from_file(cif_path)
    lattice = structure.lattice.matrix
    positions = structure.frac_coords
    numbers = [site.specie.number for site in structure]
    return lattice, positions, numbers


def load_with_ase(cif_path):
    try:
        from ase.io import read
    except Exception as exc:
        raise ImportError("ASE 不可用，无法读取 CIF 文件") from exc

    atoms = read(cif_path)
    lattice = atoms.cell.array
    positions = atoms.get_scaled_positions()
    numbers = atoms.get_atomic_numbers()
    return lattice, positions, numbers


def parse_cif_number(value):
    value = value.strip().strip("'\"")
    value = re.sub(r"\([0-9]+\)$", "", value)
    return float(value)


def load_with_basic_cif(cif_path):
    symbols = [
        "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
        "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
        "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
        "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
        "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
        "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
        "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
        "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
        "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
        "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
        "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
    ]
    atomic_numbers = {symbol: index for index, symbol in enumerate(symbols) if symbol}
    lines = open(cif_path, encoding="utf-8", errors="replace").readlines()
    scalars = {}
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("_"):
            continue
        fields = shlex.split(stripped, comments=True, posix=True)
        if len(fields) >= 2:
            scalars[fields[0].lower()] = fields[1]

    required_cell = (
        "_cell_length_a", "_cell_length_b", "_cell_length_c",
        "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma",
    )
    missing = [key for key in required_cell if key not in scalars]
    if missing:
        raise ValueError("CIF 缺少晶胞参数: " + ", ".join(missing))

    positions = []
    numbers = []
    index = 0
    while index < len(lines):
        if lines[index].strip().lower() != "loop_":
            index += 1
            continue
        index += 1
        headers = []
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped.startswith("_"):
                break
            headers.append(stripped.split()[0].lower())
            index += 1
        header_index = {name: idx for idx, name in enumerate(headers)}
        coord_keys = (
            "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z",
        )
        if not all(key in header_index for key in coord_keys):
            continue
        symbol_key = "_atom_site_type_symbol"
        if symbol_key not in header_index:
            symbol_key = "_atom_site_label"
        if symbol_key not in header_index:
            continue
        while index < len(lines):
            stripped = lines[index].strip()
            lower = stripped.lower()
            if lower == "loop_" or lower.startswith("data_") or stripped.startswith("_"):
                break
            index += 1
            if not stripped or stripped.startswith("#"):
                continue
            fields = shlex.split(stripped, comments=True, posix=True)
            if len(fields) < len(headers):
                continue
            raw_symbol = fields[header_index[symbol_key]]
            match = re.match(r"([A-Z][a-z]?)", raw_symbol)
            if not match or match.group(1) not in atomic_numbers:
                raise ValueError(f"无法从 CIF 原子标签识别元素: {raw_symbol}")
            symbol = match.group(1)
            positions.append(tuple(parse_cif_number(fields[header_index[key]]) for key in coord_keys))
            numbers.append(atomic_numbers[symbol])
        if positions:
            break

    if not positions:
        raise ValueError("CIF 中未找到分数坐标原子表")

    a = parse_cif_number(scalars["_cell_length_a"])
    b = parse_cif_number(scalars["_cell_length_b"])
    c = parse_cif_number(scalars["_cell_length_c"])
    alpha = math.radians(parse_cif_number(scalars["_cell_angle_alpha"]))
    beta = math.radians(parse_cif_number(scalars["_cell_angle_beta"]))
    gamma = math.radians(parse_cif_number(scalars["_cell_angle_gamma"]))
    sin_gamma = math.sin(gamma)
    if abs(sin_gamma) < 1.0e-12:
        raise ValueError("CIF 晶胞 gamma 角无效")
    cx = c * math.cos(beta)
    cy = c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sin_gamma
    cz_sq = c * c - cx * cx - cy * cy
    if cz_sq < -1.0e-8:
        raise ValueError("CIF 晶胞参数无法构造有效晶格")
    lattice = (
        (a, 0.0, 0.0),
        (b * math.cos(gamma), b * sin_gamma, 0.0),
        (cx, cy, math.sqrt(max(0.0, cz_sq))),
    )
    return lattice, positions, numbers


def load_crystal_structure(cif_path):
    try:
        return load_with_pymatgen(cif_path)
    except Exception as pymatgen_error:
        try:
            return load_with_ase(cif_path)
        except Exception as ase_error:
            try:
                return load_with_basic_cif(cif_path)
            except Exception as basic_error:
                raise RuntimeError(
                    "无法读取 CIF 文件。pymatgen、ASE 和内置 CIF 解析均失败："
                    f"pymatgen: {pymatgen_error}; ASE: {ase_error}; "
                    f"内置解析: {basic_error}"
                ) from basic_error


def count_qe_path_lines(path_segments):
    line_count = 0
    for index, (_, end_label) in enumerate(path_segments):
        line_count += 1
        if index < len(path_segments) - 1:
            next_start_label = path_segments[index + 1][0]
            if end_label != next_start_label:
                line_count += 1
        else:
            line_count += 1
    return line_count


def cross(u, v):
    return (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )


def dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def reciprocal_lattice_vectors(lattice):
    a1, a2, a3 = lattice
    volume = dot(a1, cross(a2, a3))
    if abs(volume) < 1.0e-12:
        raise ValueError("晶胞体积过小，无法计算倒格矢。")
    factor = 2.0 * math.pi / volume
    b1 = tuple(factor * x for x in cross(a2, a3))
    b2 = tuple(factor * x for x in cross(a3, a1))
    b3 = tuple(factor * x for x in cross(a1, a2))
    return b1, b2, b3


def segment_length_inverse_angstrom(start_coords, end_coords, reciprocal_vectors):
    delta = [end_coords[i] - start_coords[i] for i in range(3)]
    cart = [
        delta[0] * reciprocal_vectors[0][i]
        + delta[1] * reciprocal_vectors[1][i]
        + delta[2] * reciprocal_vectors[2][i]
        for i in range(3)
    ]
    return math.sqrt(sum(value * value for value in cart))


def segment_points(start_coords, end_coords, reciprocal_vectors, args):
    if args.mode == "fixed":
        return max(1, int(args.points))
    if args.spacing <= 0:
        raise ValueError("K 点间距必须大于 0。")
    length = segment_length_inverse_angstrom(start_coords, end_coords, reciprocal_vectors)
    return max(1, int(math.ceil(length / args.spacing)))


def print_qe_kpoints(crystal_structure, args):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        path_data = seekpath.get_explicit_k_path(crystal_structure)
    point_coords = path_data["point_coords"]
    path_segments = path_data["path"]
    reciprocal_vectors = reciprocal_lattice_vectors(crystal_structure[0])

    print()
    print("K_POINTS {crystal_b}")
    print(count_qe_path_lines(path_segments))

    for index, (start_label, end_label) in enumerate(path_segments):
        start_coords = point_coords[start_label]
        end_coords = point_coords[end_label]
        points_to_next = segment_points(start_coords, end_coords, reciprocal_vectors, args)

        print(
            f"{start_coords[0]:.6f} {start_coords[1]:.6f} {start_coords[2]:.6f}"
            f"  {points_to_next:2d}    ! {start_label}"
        )

        if index < len(path_segments) - 1:
            next_start_label = path_segments[index + 1][0]
            if end_label != next_start_label:
                print(
                    f"{end_coords[0]:.6f} {end_coords[1]:.6f} {end_coords[2]:.6f}"
                    f"  1    ! {end_label}"
                )
        else:
            print(
                f"{end_coords[0]:.6f} {end_coords[1]:.6f} {end_coords[2]:.6f}"
                f"  1    ! {end_label}"
            )


def main(argv=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.showwarning = lambda *args, **kwargs: None
        args = parse_args(argv)
        try:
            crystal_structure = load_crystal_structure(args.cif)
            print_qe_kpoints(crystal_structure, args)
        except FileNotFoundError:
            print(f"错误：文件 {args.cif} 不存在，请检查路径是否正确。", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"处理失败：{exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
