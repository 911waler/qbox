"""postprocess.convergence plot: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import sys
    from pathlib import Path
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    all_path, last_path, output_prefix = _argv[1:]

    def read_data(path):
        rows = []
        for line in Path(path).read_text(errors="ignore").splitlines():
            fields = line.split()
            if len(fields) >= 2:
                rows.append((float(fields[0]), float(fields[1])))
        if not rows:
            raise ValueError("convergence data is empty")
        return list(zip(*rows))

    all_x, all_y = read_data(all_path)
    last_x, last_y = read_data(last_path)
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 7.2), constrained_layout=True)
    for ax, x, y, title in ((axes[0], all_x, all_y, "Total variation"), (axes[1], last_x, last_y, "Last 5 steps")):
        ax.plot(x, y, marker="o", linewidth=1.8, markersize=4.5, color="#185FA5")
        ax.set_xlabel("Steps")
        ax.set_ylabel("Energy variation (eV)")
        ax.set_title(title)
        ax.grid(True, linewidth=0.5, alpha=0.35)
    fig.savefig(output_prefix + ".png", dpi=300)
    fig.savefig(output_prefix + ".svg")


if __name__ == "__main__":
    main()
