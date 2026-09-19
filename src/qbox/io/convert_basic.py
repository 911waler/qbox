"""io.convert basic: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import math
    import re
    import shlex
    import sys
    from pathlib import Path

    mode, infile, outfile = _argv[1], Path(_argv[2]), Path(_argv[3])


    def number(value):
        return float(re.sub(r"\([^)]*\)$", "", value.strip().strip("'\"")))


    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))


    def norm(a):
        return math.sqrt(dot(a, a))


    def inverse3(matrix):
        a, b, c = matrix
        det = (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        )
        if abs(det) < 1.0e-14:
            raise ValueError("晶格矩阵不可逆")
        return [
            [(b[1] * c[2] - b[2] * c[1]) / det, (a[2] * c[1] - a[1] * c[2]) / det, (a[1] * b[2] - a[2] * b[1]) / det],
            [(b[2] * c[0] - b[0] * c[2]) / det, (a[0] * c[2] - a[2] * c[0]) / det, (a[2] * b[0] - a[0] * b[2]) / det],
            [(b[0] * c[1] - b[1] * c[0]) / det, (a[1] * c[0] - a[0] * c[1]) / det, (a[0] * b[1] - a[1] * b[0]) / det],
        ]


    def cart_to_frac(cart, lattice):
        inv = inverse3(lattice)
        return [sum(cart[j] * inv[j][i] for j in range(3)) for i in range(3)]


    def read_cif(path):
        lines = path.read_text(errors="ignore").splitlines()
        scalars = {}
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("_"):
                fields = shlex.split(stripped, comments=True, posix=True)
                if len(fields) >= 2:
                    scalars[fields[0].lower()] = fields[1]
        keys = ("_cell_length_a", "_cell_length_b", "_cell_length_c", "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma")
        if not all(key in scalars for key in keys):
            raise ValueError("CIF 缺少完整晶胞参数")
        a, b, c = (number(scalars[key]) for key in keys[:3])
        alpha, beta, gamma = (math.radians(number(scalars[key])) for key in keys[3:])
        sg = math.sin(gamma)
        cx = c * math.cos(beta)
        cy = c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sg
        cz = math.sqrt(max(0.0, c * c - cx * cx - cy * cy))
        lattice = [[a, 0.0, 0.0], [b * math.cos(gamma), b * sg, 0.0], [cx, cy, cz]]

        atoms = []
        i = 0
        while i < len(lines):
            if lines[i].strip().lower() != "loop_":
                i += 1
                continue
            i += 1
            headers = []
            while i < len(lines) and lines[i].strip().startswith("_"):
                headers.append(lines[i].strip().split()[0].lower())
                i += 1
            hmap = {name: idx for idx, name in enumerate(headers)}
            xyz = ("_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z")
            if not all(key in hmap for key in xyz):
                continue
            symbol_key = "_atom_site_type_symbol" if "_atom_site_type_symbol" in hmap else "_atom_site_label"
            while i < len(lines):
                row = lines[i].strip()
                if row.lower() == "loop_" or row.startswith("_") or row.lower().startswith("data_"):
                    break
                i += 1
                if not row or row.startswith("#"):
                    continue
                fields = shlex.split(row, comments=True, posix=True)
                if len(fields) < len(headers):
                    continue
                match = re.match(r"([A-Z][a-z]?)", fields[hmap[symbol_key]])
                if not match:
                    raise ValueError("CIF 原子标签中无法识别元素")
                atoms.append((match.group(1), [number(fields[hmap[key]]) for key in xyz]))
            if atoms:
                break
        if not atoms:
            raise ValueError("CIF 中未找到分数坐标")
        return lattice, atoms


    def write_poscar(path, lattice, atoms):
        species = []
        for symbol, _ in atoms:
            if symbol not in species:
                species.append(symbol)
        grouped = [(symbol, frac) for symbol in species for atom_symbol, frac in atoms if atom_symbol == symbol]
        counts = [sum(1 for symbol, _ in atoms if symbol == item) for item in species]
        lines = ["Converted by qbox", "1.0"]
        lines.extend("  " + "  ".join(f"{value:18.12f}" for value in vector) for vector in lattice)
        lines.append("  " + "  ".join(species))
        lines.append("  " + "  ".join(str(value) for value in counts))
        lines.append("Direct")
        lines.extend("  " + "  ".join(f"{value:18.12f}" for value in frac) for _, frac in grouped)
        path.write_text("\n".join(lines) + "\n")


    def read_poscar(path):
        lines = [line.strip() for line in path.read_text(errors="ignore").splitlines() if line.strip()]
        if len(lines) < 8:
            raise ValueError("POSCAR/VASP 文件过短")
        scale = float(lines[1].split()[0])
        if scale <= 0:
            raise ValueError("内置转换暂不支持负的 POSCAR 缩放因子")
        lattice = [[float(value) * scale for value in lines[i].split()[:3]] for i in range(2, 5)]
        symbols = lines[5].split()
        if all(re.fullmatch(r"\d+", value) for value in symbols):
            raise ValueError("旧式 POSCAR 不含元素符号，无法可靠写出 CIF")
        counts = [int(value) for value in lines[6].split()]
        if len(symbols) != len(counts):
            raise ValueError("POSCAR 元素与计数不匹配")
        index = 7
        if lines[index].lower().startswith("s"):
            index += 1
        direct = lines[index].lower().startswith("d")
        cartesian = lines[index].lower().startswith(("c", "k"))
        if not direct and not cartesian:
            raise ValueError("POSCAR 缺少 Direct/Cartesian 坐标类型")
        index += 1
        atoms = []
        for symbol, count in zip(symbols, counts):
            for _ in range(count):
                coords = [float(value) for value in lines[index].split()[:3]]
                index += 1
                if cartesian:
                    coords = cart_to_frac([value * scale for value in coords], lattice)
                atoms.append((symbol, coords))
        return lattice, atoms


    def write_cif(path, lattice, atoms):
        lengths = [norm(vector) for vector in lattice]
        angles = [
            math.degrees(math.acos(max(-1.0, min(1.0, dot(lattice[1], lattice[2]) / (lengths[1] * lengths[2]))))),
            math.degrees(math.acos(max(-1.0, min(1.0, dot(lattice[0], lattice[2]) / (lengths[0] * lengths[2]))))),
            math.degrees(math.acos(max(-1.0, min(1.0, dot(lattice[0], lattice[1]) / (lengths[0] * lengths[1]))))),
        ]
        lines = [
            "data_qbox", "_symmetry_space_group_name_H-M 'P 1'", "_symmetry_Int_Tables_number 1",
            f"_cell_length_a {lengths[0]:.10f}", f"_cell_length_b {lengths[1]:.10f}", f"_cell_length_c {lengths[2]:.10f}",
            f"_cell_angle_alpha {angles[0]:.10f}", f"_cell_angle_beta {angles[1]:.10f}", f"_cell_angle_gamma {angles[2]:.10f}",
            "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z",
        ]
        counters = {}
        for symbol, frac in atoms:
            counters[symbol] = counters.get(symbol, 0) + 1
            lines.append(f"{symbol}{counters[symbol]} {symbol} " + " ".join(f"{value % 1.0:.12f}" for value in frac))
        path.write_text("\n".join(lines) + "\n")


    if mode == "cif2vasp":
        lattice, atoms = read_cif(infile)
        write_poscar(outfile, lattice, atoms)
    else:
        lattice, atoms = read_poscar(infile)
        write_cif(outfile, lattice, atoms)


if __name__ == "__main__":
    main()
