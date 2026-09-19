import argparse
import re
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt


BANDS_FILE = Path("bands.dat.gnu")
NSCF_FILE = Path("nscf.out")
SCF_FILE = Path("scf.out")
PARENT_NSCF_FILE = Path("../nscf.out")
PARENT_SCF_FILE = Path("../scf.out")


def normalize_klabel(label):
    label = label.strip()
    replacements = {
        "GAMMA": r"$\Gamma$",
        "Gamma": r"$\Gamma$",
        "gamma": r"$\Gamma$",
        "\\Gamma": r"$\Gamma$",
        "Γ": r"$\Gamma$",
    }
    return replacements.get(label, label)


def set_nature_style():
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "font.size": 7,
        "axes.labelsize": 7,
        "xtick.labelsize": 6,
        "ytick.labelsize": 6,
        "legend.fontsize": 6,
        "axes.linewidth": 0.8,
        "axes.spines.top": True,
        "axes.spines.right": True,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "lines.solid_capstyle": "round",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })


def candidate_files(patterns):
    seen = set()
    files = []
    for pattern in patterns:
        for path in sorted(Path(".").glob(pattern)):
            if path.is_file() and path not in seen:
                files.append(path)
                seen.add(path)
    return files


def find_band_input_file():
    patterns = ("*.bands.in", "*band*.in", "*.in")
    for filename in candidate_files(patterns):
        text = filename.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^\s*K_POINTS\s*(?:\{|\()?crystal_b(?:\}|\))?", text, re.IGNORECASE | re.MULTILINE):
            return filename
    return None


def find_bands_output_file():
    patterns = ("bands.out", "band.out", "*bands*.out", "*band*.out")
    for filename in candidate_files(patterns):
        text = filename.read_text(encoding="utf-8", errors="ignore")
        if "high-symmetry point:" in text and "x coordinate" in text:
            return filename
    return None


def read_high_symmetry_labels(filename):
    if filename is None or not filename.exists():
        return [], None

    lines = filename.read_text(encoding="utf-8", errors="ignore").splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"^\s*K_POINTS\s*(?:\{|\()?crystal_b(?:\}|\))?", line, re.IGNORECASE):
            continue

        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            return [], filename

        try:
            npoints = int(lines[j].split()[0])
        except (ValueError, IndexError):
            return [], filename

        labels = []
        for raw in lines[j + 1:j + 1 + npoints]:
            if "!" in raw:
                label = raw.split("!", 1)[1].strip().split()[0]
            else:
                label = ""
            labels.append(normalize_klabel(label))
        return labels, filename

    return [], filename


def read_high_symmetry_xcoords(filename):
    if filename is None or not filename.exists():
        return [], None

    xcoords = []
    pattern = re.compile(r"high-symmetry point:.*?x coordinate\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)")
    with filename.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            match = pattern.search(line)
            if match:
                xcoords.append(float(match.group(1)))
    return xcoords, filename


def read_high_symmetry_points(band_input, bands_output):
    if band_input is None:
        band_input = find_band_input_file()
    if bands_output is None:
        bands_output = find_bands_output_file()

    labels, label_file = read_high_symmetry_labels(band_input)
    xcoords, xcoord_file = read_high_symmetry_xcoords(bands_output)

    if not xcoords:
        return [], [], label_file, xcoord_file

    if labels and len(labels) != len(xcoords):
        print(
            f"警告：高对称点标签数({len(labels)})与横坐标数({len(xcoords)})不一致，"
            "将仅绘制竖向参考线。"
        )
        labels = []

    if not labels:
        labels = [""] * len(xcoords)

    return labels, xcoords, label_file, xcoord_file


def read_fermi_energy(*filenames):
    for filename in filenames:
        if not filename.exists():
            continue
        with filename.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if "the Fermi energy is" in line:
                    try:
                        return float(line.split()[-2]), filename
                    except (ValueError, IndexError):
                        print(f"警告：解析费米能级失败：{line.strip()}")
                        break
                if "highest occupied" in line:
                    match = re.search(r"([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)", line)
                    if match:
                        return float(match.group(1)), filename
    return None, None


def read_bands(filename):
    if not filename.exists():
        raise FileNotFoundError(f"未找到能带数据文件：{filename}")

    bands = []
    kpoints = []
    energies = []

    with filename.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                if kpoints and energies:
                    bands.append((kpoints, energies))
                    kpoints = []
                    energies = []
                continue

            parts = line.split()
            if len(parts) < 2:
                continue
            kpoints.append(float(parts[0]))
            energies.append(float(parts[1]))

    if kpoints and energies:
        bands.append((kpoints, energies))

    if not bands:
        raise ValueError(f"未能从 {filename} 中读取到能带数据。")

    return bands


def ask_zero_reference(default="fermi"):
    choices = {
        "1": "fermi",
        "2": "cbm",
        "3": "vbm",
        "4": "none",
        "fermi": "fermi",
        "cbm": "cbm",
        "vbm": "vbm",
        "none": "none",
    }
    print("请选择能量零点：")
    print("  1) Fermi level 归零")
    print("  2) CBM 归零")
    print("  3) VBM 归零")
    print("  4) 不平移")
    answer = input(f"直接回车使用：{default} ").strip().lower()
    if not answer:
        return default
    return choices.get(answer, default)


def estimate_cbm_energy(bands, fermi_energy):
    if fermi_energy is None:
        return None
    candidates = [
        value
        for _, energies in bands
        for value in energies
        if value > fermi_energy + 1e-8
    ]
    if not candidates:
        return None
    return min(candidates)


def estimate_vbm_energy(bands, fermi_energy):
    if fermi_energy is None:
        return None
    candidates = [
        value
        for _, energies in bands
        for value in energies
        if value < fermi_energy - 1e-8
    ]
    if not candidates:
        return None
    return max(candidates)


def decide_zero_reference(args, fermi_energy):
    if args.zero_fermi:
        return "fermi"
    if args.no_zero_fermi:
        return "none"
    if args.zero_reference:
        return args.zero_reference
    if fermi_energy is None:
        return "none"
    if sys.stdin.isatty():
        return ask_zero_reference(default="fermi")

    print("非交互环境：默认将 Fermi level 归零。可用 --zero-reference cbm/vbm/none 调整。")
    return "fermi"


def plot_bands(bands, fermi_energy, reference_energy, reference_label, output_prefix, high_symmetry):
    set_nature_style()

    fig, ax = plt.subplots(figsize=(3.35, 4.2), constrained_layout=True)

    band_color = "#202124"
    fermi_color = "#B24A48"
    guide_color = "#8A8A8A"

    labels, xcoords = high_symmetry

    for kpoints, energies in bands:
        if reference_energy is not None:
            energies = [value - reference_energy for value in energies]
        ax.plot(kpoints, energies, color=band_color, linewidth=0.65)

    if reference_energy is not None:
        ax.axhline(0.0, color=fermi_color, linestyle=(0, (3, 2)), linewidth=0.8)
        ax.set_ylim(-5, 5)
    elif fermi_energy is not None:
        ax.axhline(fermi_energy, color=fermi_color, linestyle=(0, (3, 2)), linewidth=0.8)
        ax.set_ylim(fermi_energy - 5, fermi_energy + 5)

    if xcoords:
        ax.set_xticks(xcoords)
        ax.set_xticklabels(labels)
        ax.set_xlim(xcoords[0], xcoords[-1])
        for xpos in xcoords:
            ax.axvline(xpos, ymin=0, ymax=1, color=guide_color, linewidth=0.45, zorder=0)
        ax.set_xlabel("")
    else:
        all_k = [k for band_k, _ in bands for k in band_k]
        if all_k:
            ax.set_xlim(min(all_k), max(all_k))
        ax.set_xlabel("Wave vector")

    if reference_energy is not None and reference_label == "fermi":
        ax.set_ylabel(r"Energy - $E_F$ (eV)")
    elif reference_energy is not None and reference_label == "cbm":
        ax.set_ylabel("Energy - CBM (eV)")
    elif reference_energy is not None and reference_label == "vbm":
        ax.set_ylabel("Energy - VBM (eV)")
    else:
        ax.set_ylabel("Energy (eV)")

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)

    ax.tick_params(axis="both", which="major", pad=2, top=True, right=True)
    ax.grid(False)

    for ext in ("png", "svg"):
        dpi = 600 if ext == "png" else None
        fig.savefig(f"{output_prefix}.{ext}", dpi=dpi)

    plt.close(fig)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Plot Quantum ESPRESSO bands.dat.gnu in a Nature-style format."
    )
    parser.add_argument("-i", "--input", default=str(BANDS_FILE), help="Input bands.dat.gnu file.")
    parser.add_argument("-o", "--output", default="band_structure", help="Output filename prefix.")
    parser.add_argument("--band-input", default=None, help="pw.x bands input file containing K_POINTS crystal_b labels.")
    parser.add_argument("--bands-output", default=None, help="bands.x output file containing high-symmetry x coordinates.")
    parser.add_argument("--zero-reference", choices=("fermi", "cbm", "vbm", "none"), default=None, help="Energy zero reference.")
    parser.add_argument("--zero-fermi", action="store_true", help="Shift Fermi level to 0 eV.")
    parser.add_argument("--no-zero-fermi", action="store_true", help="Keep absolute energy scale.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.zero_fermi and args.no_zero_fermi:
        raise SystemExit("错误：--zero-fermi 和 --no-zero-fermi 不能同时使用。")

    fermi_energy, fermi_file = read_fermi_energy(NSCF_FILE, SCF_FILE, PARENT_NSCF_FILE, PARENT_SCF_FILE)
    if fermi_energy is None:
        print("警告：未在 nscf.out、scf.out 或上一级目录中找到费米能级。")
    else:
        print(f"成功读取费米能级：{fermi_energy:.6f} eV，来源：{fermi_file}")

    bands = read_bands(Path(args.input))
    zero_reference = decide_zero_reference(args, fermi_energy)
    labels, xcoords, label_file, xcoord_file = read_high_symmetry_points(
        Path(args.band_input) if args.band_input else None,
        Path(args.bands_output) if args.bands_output else None,
    )
    if labels and xcoords:
        print(f"高对称点标签来源：{label_file}")
        print(f"高对称点横坐标来源：{xcoord_file}")
        print("高对称路径：" + " | ".join(label or "?" for label in labels))
    else:
        print("警告：未能完整读取高对称点信息，将使用普通横坐标绘图。")

    reference_energy = None
    reference_label = None
    if zero_reference == "fermi" and fermi_energy is not None:
        reference_energy = fermi_energy
        reference_label = "fermi"
    elif zero_reference == "cbm" and fermi_energy is not None:
        reference_energy = estimate_cbm_energy(bands, fermi_energy)
        reference_label = "cbm" if reference_energy is not None else None
        if reference_energy is None:
            print("警告：未能从能带数据估计 CBM，将保留绝对能量坐标。")
    elif zero_reference == "vbm" and fermi_energy is not None:
        reference_energy = estimate_vbm_energy(bands, fermi_energy)
        reference_label = "vbm" if reference_energy is not None else None
        if reference_energy is None:
            print("警告：未能从能带数据估计 VBM，将保留绝对能量坐标。")

    plot_bands(bands, fermi_energy, reference_energy, reference_label, args.output, (labels, xcoords))

    if reference_label == "fermi":
        print("已将 Fermi level 归零为 0 eV。")
    elif reference_label == "cbm":
        print(f"已将 CBM 归零为 0 eV。CBM = {reference_energy:.6f} eV。")
    elif reference_label == "vbm":
        print(f"已将 VBM 归零为 0 eV。VBM = {reference_energy:.6f} eV。")
    elif fermi_energy is not None:
        print("保留绝对能量坐标，未进行能量零点平移。")

    print(f"能带图已保存为 {args.output}.png/.svg")


if __name__ == "__main__":
    main()
