"""postprocess.unfold plot: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import json
    import pathlib
    import re
    import sys

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    output = pathlib.Path(_argv[1])
    enk = np.atleast_2d(np.loadtxt(output / "enk.dat"))
    wnk = np.atleast_2d(np.loadtxt(output / "wnk.dat"))
    if enk.shape != wnk.shape:
        raise SystemExit(f"enk.dat 与 wnk.dat 形状不一致：{enk.shape} != {wnk.shape}")

    energy = enk * 13.605693122994
    fermi = None
    scf_output = output / "scf.out"
    if scf_output.is_file():
        text = scf_output.read_text(errors="replace")
        matches = re.findall(r"the Fermi energy is\s+([-+0-9.Ee]+)\s+ev", text, re.I)
        if not matches:
            matches = re.findall(r"highest occupied level \(ev\):\s+([-+0-9.Ee]+)", text, re.I)
        if matches:
            fermi = float(matches[-1])
            energy -= fermi

    metadata = json.loads((output / "unfold-metadata.json").read_text())
    nk = energy.shape[1]
    x = np.arange(nk, dtype=float)
    weight_max = float(np.nanmax(wnk))
    normalized = wnk / weight_max if weight_max > 0 else np.zeros_like(wnk)

    fig, ax = plt.subplots(figsize=(7.2, 5.4), constrained_layout=True)
    for band_energy, band_weight in zip(energy, normalized):
        ax.plot(x, band_energy, color="0.78", linewidth=0.35, zorder=1)
        ax.scatter(
            x, band_energy, s=2.0 + 18.0 * band_weight,
            c=band_weight, cmap="viridis", vmin=0.0, vmax=1.0,
            linewidths=0, alpha=0.85, zorder=2,
        )

    indices = metadata.get("tick_indices", [])
    labels = metadata.get("tick_labels", [])
    valid = [(int(i), str(label)) for i, label in zip(indices, labels) if int(i) < nk]
    if valid:
        combined = []
        for index, label in valid:
            label = r"$\Gamma$" if label.upper() == "GAMMA" else label
            if combined and index - combined[-1][0] <= 1:
                previous_index, previous_label = combined.pop()
                combined.append(((previous_index + index) / 2, previous_label + "|" + label))
            else:
                combined.append((index, label))
        for index, _label in combined:
            ax.axvline(index, color="0.82", linewidth=0.6, zorder=0)
        ax.set_xticks(
            [item[0] for item in combined], [item[1] for item in combined], fontsize=8
        )
    ax.axhline(0.0, color="black", linewidth=0.7, linestyle="--")
    ax.set_xlim(0, max(nk - 1, 1))
    ax.set_xlabel("Primitive-cell k path")
    ax.set_ylabel("Energy - $E_F$ (eV)" if fermi is not None else "Energy (eV)")
    ax.set_title("Unfolded band structure")
    fig.savefig(output / "unfold_band.png", dpi=300)
    fig.savefig(output / "unfold_band.svg")
    plt.close(fig)
    print(f"已生成 {output / 'unfold_band.png'} 和 {output / 'unfold_band.svg'}")


if __name__ == "__main__":
    main()
