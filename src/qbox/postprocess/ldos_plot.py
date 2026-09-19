import argparse
import re
import sys
from pathlib import Path

import numpy as np

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap


def read_fermi(paths):
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        matches = re.findall(
            r"the Fermi energy is\s+([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+ev",
            text,
            re.I,
        )
        if matches:
            return float(matches[-1]), path
    return None, None


def read_edges(paths):
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        matches = re.findall(
            r"highest occupied,\s*lowest unoccupied level\s*\(ev\):\s*"
            r"([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+"
            r"([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)",
            text,
            re.I,
        )
        if matches:
            vbm, cbm = matches[-1]
            return float(vbm), float(cbm), path
        parsed = estimate_edges_from_bands(text)
        if parsed is not None:
            vbm, cbm = parsed
            return vbm, cbm, path
    return None, None, None


def estimate_edges_from_bands(text):
    nelec_match = re.search(r"number of electrons\s*=\s*([-+]?\d+(?:\.\d*)?)", text, re.I)
    if not nelec_match:
        return None
    nelec = float(nelec_match.group(1))
    nocc = int(round(nelec / 2.0))
    if nocc <= 0:
        return None

    vbm = None
    cbm = None
    for match in re.finditer(r"bands \(ev\):\s*\n((?:\s*[-+0-9.]+(?:\s+[-+0-9.]+)*\s*\n)+)", text, re.I):
        values = [float(x) for x in re.findall(r"[-+]?\d+\.\d+", match.group(1))]
        if len(values) <= nocc:
            continue
        occ_edge = values[nocc - 1]
        unocc_edge = values[nocc]
        vbm = occ_edge if vbm is None else max(vbm, occ_edge)
        cbm = unocc_edge if cbm is None else min(cbm, unocc_edge)

    if vbm is None or cbm is None:
        return None
    return vbm, cbm


def estimate_edge_from_ldos(energy, total, fermi, edge):
    if fermi is None or total.size == 0:
        return None
    finite_total = total[np.isfinite(total)]
    if finite_total.size == 0:
        return None
    max_total = float(np.nanmax(finite_total))
    if not np.isfinite(max_total) or max_total <= 0:
        return None
    threshold = max_total * 1e-3
    if edge == "cbm":
        idx = np.where((energy >= fermi) & (total > threshold))[0]
        return float(energy[idx[0]]) if idx.size else None
    idx = np.where((energy <= fermi) & (total > threshold))[0]
    return float(energy[idx[-1]]) if idx.size else None


def matlab_parula_colormap():
    return LinearSegmentedColormap.from_list(
        "matlab_parula",
        [
            "#352a87", "#0f5cdd", "#1481d6", "#06a7c6",
            "#38b99e", "#92bf73", "#d9ba56", "#f9fb0e",
        ],
        N=256,
    )


def main(argv=None):
    matplotlib.use("Agg")
    parser = argparse.ArgumentParser(description="Plot QE projwfc.x LDOS boxes data.")
    parser.add_argument("input", help="*.pdos.ldos_boxes or *.pdos.ldos_boxes.dat")
    parser.add_argument("--output-prefix", default=None)
    parser.add_argument("--zero-reference", choices=("fermi", "cbm", "vbm", "none"), default="fermi")
    parser.add_argument("--fermi-from", nargs="*", default=[])
    args = parser.parse_args(argv)

    infile = Path(args.input)
    if not infile.is_file():
        raise SystemExit(f"找不到 LDOS 数据文件：{infile}")

    data = np.loadtxt(infile, comments="#")
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 4:
        raise SystemExit("LDOS 数据列数不足：需要 E, tot(E), totldos 和至少一个 box 列。")

    energy = data[:, 0]
    total = data[:, 2]
    ldos = data[:, 3:].T
    total = np.where(np.isfinite(total), total, np.nan)
    ldos = np.where(np.isfinite(ldos), ldos, np.nan)
    boxes = np.arange(1, ldos.shape[0] + 1)

    fermi, fermi_path = read_fermi(args.fermi_from)
    reference = 0.0
    ref_label = "absolute"
    vbm, cbm, edge_path = read_edges(args.fermi_from)
    if args.zero_reference == "fermi":
        if fermi is None:
            raise SystemExit("未能读取 Fermi level，无法执行 Fermi 归零。")
        reference = fermi
        ref_label = f"E_F from {fermi_path.name}"
    elif args.zero_reference in {"cbm", "vbm"}:
        target = cbm if args.zero_reference == "cbm" else vbm
        if target is None:
            target = estimate_edge_from_ldos(energy, total, fermi, args.zero_reference)
        if target is None:
            raise SystemExit(f"未能确定 {args.zero_reference.upper()}，无法归零。")
        reference = target
        ref_label = args.zero_reference.upper() if edge_path is None else f"{args.zero_reference.upper()} from {edge_path.name}"

    shifted_energy = energy - reference

    positive_ldos = ldos[np.isfinite(ldos) & (ldos > 0)]
    if positive_ldos.size == 0:
        raise SystemExit("LDOS 数据没有有限正值；请检查 ldos.in 中是否设置了有限 degauss，并重新运行 projwfc.x。")
    vmax = float(np.nanmax(positive_ldos))
    if vmax <= 0.01:
        levels = np.linspace(0.0, vmax, 80)
    else:
        levels = np.linspace(0.01, vmax, 256)

    ldos_cmap = matlab_parula_colormap()
    ldos_cmap.set_under("white")

    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    contour = ax.contourf(
        shifted_energy,
        boxes,
        ldos,
        levels=levels,
        cmap=ldos_cmap,
        extend="min",
        antialiased=True,
    )
    ax.set_xlabel("Energy (eV)" if args.zero_reference == "none" else f"Energy - {args.zero_reference.upper()} (eV)")
    ax.set_ylabel("LDOS box index")
    ax.set_title("QE LDOS")
    fig.colorbar(contour, ax=ax, label="LDOS")
    ax.axvline(0.0, color="white", linewidth=0.8, alpha=0.8)
    if vbm is not None and cbm is not None and cbm > vbm:
        vbm_shifted = vbm - reference
        cbm_shifted = cbm - reference
        ax.axvline(vbm_shifted, color="white", linestyle="--", linewidth=0.8, alpha=0.9)
        ax.axvline(cbm_shifted, color="white", linestyle="--", linewidth=0.8, alpha=0.9)
        ymin, ymax = ax.get_ylim()
        ax.text(vbm_shifted, ymax, " VBM", ha="left", va="top", fontsize=8, color="white")
        ax.text(cbm_shifted, ymax, " CBM", ha="left", va="top", fontsize=8, color="white")
    ax.text(0.99, 0.02, ref_label, transform=ax.transAxes, ha="right", va="bottom", fontsize=8, color="white")
    fig.tight_layout()

    output_prefix = args.output_prefix or infile.with_suffix("").name
    png = Path(f"{output_prefix}.png")
    pdf = Path(f"{output_prefix}.pdf")
    fig.savefig(png, dpi=300)
    fig.savefig(pdf)
    print(f"已生成：{png}")
    print(f"已生成：{pdf}")


if __name__ == "__main__":
    main()
