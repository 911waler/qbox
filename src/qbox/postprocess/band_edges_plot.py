"""postprocess.band edges plot: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import re
    import sys
    from pathlib import Path

    import matplotlib as mpl
    import matplotlib.pyplot as plt

    bands_file = Path(_argv[1])
    vbm_file = Path(_argv[2])
    cbm_file = Path(_argv[3])
    output_prefix = _argv[4]
    bands_out = Path(_argv[5])

    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "font.size": 7,
        "axes.labelsize": 7,
        "xtick.labelsize": 6,
        "ytick.labelsize": 6,
        "legend.fontsize": 6,
        "axes.linewidth": 0.8,
        "svg.fonttype": "none",
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })

    def read_blocks(path):
        blocks = []
        current = []
        if not path.exists():
            return blocks
        for raw in path.read_text(errors="ignore").splitlines():
            if raw.strip():
                parts = raw.split()
                if len(parts) >= 2:
                    current.append((float(parts[0]), float(parts[1])))
            elif current:
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)
        return blocks

    def read_single_band(path):
        blocks = read_blocks(path)
        if not blocks:
            return []
        if len(blocks) == 1:
            return blocks[0]
        return [point for block in blocks for point in block]

    def read_xcoords(path):
        if not path.exists():
            return []
        coords = []
        pattern = re.compile(r"high-symmetry point:.*?x coordinate\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)")
        for line in path.read_text(errors="ignore").splitlines():
            match = pattern.search(line)
            if match:
                coords.append(float(match.group(1)))
        return coords

    bands = read_blocks(bands_file)
    if not bands:
        raise SystemExit("未能读取 bands.dat.gnu。")
    vbm = read_single_band(vbm_file)
    cbm = read_single_band(cbm_file)

    fig, ax = plt.subplots(figsize=(3.35, 4.2), constrained_layout=True)
    for block in bands:
        ax.plot(
            [x for x, _ in block],
            [y for _, y in block],
            color="#B8B8B8",
            linewidth=0.45,
            zorder=1,
        )

    if vbm:
        ax.plot([x for x, _ in vbm], [y for _, y in vbm], color="#C43B3B", linewidth=1.25, label="VBM.dat", zorder=3)
    if cbm:
        ax.plot([x for x, _ in cbm], [y for _, y in cbm], color="#1F5AA6", linewidth=1.25, label="CBM.dat", zorder=4)

    xcoords = read_xcoords(bands_out)
    if xcoords:
        ax.set_xlim(xcoords[0], xcoords[-1])
        ax.set_xticks(xcoords)
        ax.set_xticklabels([""] * len(xcoords))
        for xpos in xcoords:
            ax.axvline(xpos, color="#8A8A8A", linewidth=0.4, zorder=0)
    else:
        all_x = [x for block in bands for x, _ in block]
        if all_x:
            ax.set_xlim(min(all_x), max(all_x))

    edge_values = [y for _, y in vbm] + [y for _, y in cbm]
    if edge_values:
        ymin = min(edge_values) - 1.0
        ymax = max(edge_values) + 1.0
        if ymin < ymax:
            ax.set_ylim(ymin, ymax)

    ax.set_xlabel("Wave vector")
    ax.set_ylabel("Energy (eV)")
    ax.legend(frameon=False, loc="best")
    ax.tick_params(axis="both", which="major", pad=2, top=True, right=True)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)

    for ext in ("png", "svg"):
        fig.savefig(f"{output_prefix}.{ext}", dpi=600 if ext == "png" else None)
    plt.close(fig)
    print(f"已生成 VBM/CBM 叠加能带图：{output_prefix}.png/.svg")


if __name__ == "__main__":
    main()
