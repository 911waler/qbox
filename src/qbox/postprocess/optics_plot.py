import argparse
import math
import re
from pathlib import Path

import numpy as np

import matplotlib
import matplotlib.pyplot as plt


def load_eps_file(path):
    data = np.loadtxt(path, comments="#")
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 4:
        raise SystemExit(f"{path} 至少需要 4 列：energy, x, y, z")
    return data[:, 0], data[:, 1:4]


def find_pair(directory, prefix):
    directory = Path(directory)
    if prefix:
        candidates = [(directory / f"epsr_{prefix}.dat", directory / f"epsi_{prefix}.dat")]
    else:
        candidates = []
    for epsr in sorted(directory.glob("epsr_*.dat")):
        suffix = epsr.name[len("epsr_"):]
        candidates.append((epsr, directory / f"epsi_{suffix}"))
    for epsr, epsi in candidates:
        if epsr.is_file() and epsi.is_file():
            return epsr, epsi
    return None, None


def sanitize_label(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


def compute_quantity(kind, energy_ev, eps1, eps2, thickness_nm):
    modulus = np.sqrt(eps1 * eps1 + eps2 * eps2)
    n = np.sqrt(np.maximum((modulus + eps1) / 2.0, 0.0))
    kappa = np.sqrt(np.maximum((modulus - eps1) / 2.0, 0.0))

    if kind == "dielectric":
        return eps1, eps2, "epsilon", "Dielectric function"
    if kind == "n":
        return n, None, "n", "Refractive index"
    if kind == "kappa":
        return kappa, None, "kappa", "Extinction coefficient"
    if kind == "alpha":
        # alpha = 2 omega kappa / c. For photon energy E in eV:
        # omega = E*e/hbar, alpha[cm^-1] = 2*E[eV]*e*kappa/(hbar*c*100).
        alpha_cm = 2.0 * energy_ev[:, None] * 1.602176634e-19 * kappa / (1.054571817e-34 * 299792458.0 * 100.0)
        return alpha_cm, None, "alpha_cm-1", "Absorption coefficient (cm$^{-1}$)"
    if kind == "absorptance":
        alpha_cm = 2.0 * energy_ev[:, None] * 1.602176634e-19 * kappa / (1.054571817e-34 * 299792458.0 * 100.0)
        thickness_cm = thickness_nm * 1.0e-7
        absorptance = 1.0 - np.exp(-alpha_cm * thickness_cm)
        return absorptance, None, f"absorptance_{thickness_nm:g}nm", "Absorptance"
    if kind == "reflectance":
        reflectance = ((n - 1.0) ** 2 + kappa ** 2) / ((n + 1.0) ** 2 + kappa ** 2)
        return reflectance, None, "reflectance", "Normal-incidence reflectance"
    raise SystemExit(f"未知绘图类型：{kind}")


def add_average(values):
    avg = values.mean(axis=1, keepdims=True)
    return np.hstack([values, avg])


def plot_lines(energy, values, ylabel, title, output_prefix, second_values=None):
    labels = ["x", "y", "z", "avg"]
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    for idx, label in enumerate(labels):
        ax.plot(energy, values[:, idx], label=label, linewidth=1.4 if label == "avg" else 1.0)
    if second_values is not None:
        for idx, label in enumerate(labels):
            ax.plot(energy, second_values[:, idx], linestyle="--", label=f"{label} imag", linewidth=1.0)
        ylabel = "epsilon"
    ax.set_xlabel("Photon energy (eV)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    png = Path(f"{output_prefix}.png")
    svg = Path(f"{output_prefix}.svg")
    fig.savefig(png, dpi=300)
    fig.savefig(svg)
    print(f"已生成：{png}")
    print(f"已生成：{svg}")


def main(argv=None):
    matplotlib.use("Agg")
    parser = argparse.ArgumentParser(description="Plot optical quantities from QE epsilon.x epsr/epsi data.")
    parser.add_argument("--directory", default=".", help="Directory containing epsr_*.dat and epsi_*.dat")
    parser.add_argument("--prefix", default="", help="QE prefix used in epsr_PREFIX.dat / epsi_PREFIX.dat")
    parser.add_argument("--kind", required=True, choices=("dielectric", "n", "kappa", "alpha", "absorptance", "reflectance"))
    parser.add_argument("--thickness-nm", type=float, default=100.0, help="Thickness for absorptance A=1-exp(-alpha*d), nm")
    parser.add_argument("--output-prefix", default=None)
    args = parser.parse_args(argv)

    epsr_path, epsi_path = find_pair(args.directory, args.prefix)
    if epsr_path is None:
        raise SystemExit(f"未在 {args.directory} 找到 epsr_*.dat 和 epsi_*.dat 配对文件。")

    energy_r, eps1 = load_eps_file(epsr_path)
    energy_i, eps2 = load_eps_file(epsi_path)
    if energy_r.shape != energy_i.shape or not np.allclose(energy_r, energy_i, rtol=1e-7, atol=1e-9):
        raise SystemExit("epsr 和 epsi 的能量网格不一致。")
    if args.kind == "absorptance" and args.thickness_nm <= 0:
        raise SystemExit("吸收率绘图需要正的样品厚度。")

    primary, secondary, suffix, ylabel = compute_quantity(args.kind, energy_r, eps1, eps2, args.thickness_nm)
    primary = add_average(primary)
    if secondary is not None:
        secondary = add_average(secondary)
    prefix = args.prefix
    if not prefix:
        prefix = epsr_path.stem.replace("epsr_", "", 1)
    output_prefix = args.output_prefix or str(Path(args.directory) / f"{prefix}_{sanitize_label(suffix)}")
    title = f"{prefix} {ylabel}"
    plot_lines(energy_r, primary, ylabel, title, output_prefix, secondary)


if __name__ == "__main__":
    main()
