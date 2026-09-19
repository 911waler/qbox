"""postprocess.unfold edges: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import collections
    import json
    import math
    import pathlib
    import re
    import sys

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    RY_TO_EV = 13.605693122994
    output = pathlib.Path(_argv[1])
    reference_mode = _argv[2]
    reference_input = float(_argv[3])
    weight_threshold = float(_argv[4])
    energy_tolerance = float(_argv[5])
    plot_window = float(_argv[6])

    enk = np.atleast_2d(np.loadtxt(output / "enk.dat"))
    wnk = np.atleast_2d(np.loadtxt(output / "wnk.dat"))
    if enk.shape != wnk.shape:
        raise SystemExit(f"enk.dat 与 wnk.dat 形状不一致：{enk.shape} != {wnk.shape}")
    nbnd, nk = enk.shape
    metadata = json.loads((output / "unfold-metadata.json").read_text())

    first_band = 1
    unfold_input = output / "unfold.in"
    if unfold_input.is_file():
        match = re.search(r"\bfirst_band\s*=\s*(\d+)", unfold_input.read_text(errors="replace"), re.I)
        if match:
            first_band = int(match.group(1))

    fermi = None
    scf_output = output / "scf.out"
    if scf_output.is_file():
        scf_text = scf_output.read_text(errors="replace")
        matches = re.findall(r"the Fermi energy is\s+([-+0-9.Ee]+)\s+ev", scf_text, re.I)
        if not matches:
            matches = re.findall(r"highest occupied level \(ev\):\s+([-+0-9.Ee]+)", scf_text, re.I)
        if matches:
            fermi = float(matches[-1])
    if reference_mode == "relative":
        if fermi is None:
            raise SystemExit("选择了 E-EF 标尺，但未能从 scf.out 读取费米能级")
        reference_absolute = fermi + reference_input
    else:
        reference_absolute = reference_input

    def reconstruct_k_distance(meta, expected_nk):
        saved = np.asarray(meta.get("k_distance_inverse_angstrom", []), dtype=float)
        if saved.size == expected_nk and np.all(np.isfinite(saved)):
            return saved
        segments = meta.get("segment_point_counts", [])
        if not segments:
            raise SystemExit("unfold-metadata.json 缺少路径分段信息")
        result = np.full(expected_nk, np.nan, dtype=float)
        cursor = None
        cumulative = 0.0
        previous_end = None
        for item in segments:
            count = int(item["points"])
            if cursor is None:
                start = 0
            elif previous_end == item["start"]:
                start = cursor
            else:
                start = cursor + 1
            end = start + count
            if end >= expected_nk:
                raise SystemExit("metadata 路径点数超过 enk.dat 的 nk")
            length = float(item["length_inverse_angstrom"])
            result[start:end + 1] = np.linspace(cumulative, cumulative + length, count + 1)
            cumulative += length
            cursor = end
            previous_end = item["end"]
        if cursor != expected_nk - 1 or np.any(~np.isfinite(result)):
            raise SystemExit(
                f"metadata 与 enk.dat 的 K 点数不一致：metadata last={cursor}, nk={expected_nk}"
            )
        return result

    k_distance = reconstruct_k_distance(metadata, nk)
    energy_absolute = enk * RY_TO_EV
    weight_max = float(np.nanmax(wnk))
    weight_normalized = wnk / weight_max if weight_max > 0 else np.zeros_like(wnk)
    allowed = np.isfinite(energy_absolute) & np.isfinite(wnk)
    if weight_threshold > 0:
        allowed &= weight_normalized >= weight_threshold

    valence_mask = allowed & (energy_absolute < reference_absolute - energy_tolerance)
    conduction_mask = allowed & (energy_absolute > reference_absolute + energy_tolerance)

    vbm_rows = np.argmax(np.where(valence_mask, energy_absolute, -np.inf), axis=0)
    cbm_rows = np.argmin(np.where(conduction_mask, energy_absolute, np.inf), axis=0)
    has_vbm = np.any(valence_mask, axis=0)
    has_cbm = np.any(conduction_mask, axis=0)

    def selected_arrays(rows, present):
        columns = np.arange(nk)
        energies = np.full(nk, np.nan)
        raw_weights = np.full(nk, np.nan)
        normalized_weights = np.full(nk, np.nan)
        band_numbers = np.full(nk, -1, dtype=int)
        energies[present] = energy_absolute[rows[present], columns[present]]
        raw_weights[present] = wnk[rows[present], columns[present]]
        normalized_weights[present] = weight_normalized[rows[present], columns[present]]
        band_numbers[present] = rows[present] + first_band
        return energies, raw_weights, normalized_weights, band_numbers

    vbm_energy, vbm_weight, vbm_weight_norm, vbm_bands = selected_arrays(vbm_rows, has_vbm)
    cbm_energy, cbm_weight, cbm_weight_norm, cbm_bands = selected_arrays(cbm_rows, has_cbm)

    def write_simple(name, energies):
        present = np.isfinite(energies)
        data = np.column_stack((k_distance[present], energies[present]))
        np.savetxt(
            output / name,
            data,
            fmt=("%16.9f", "%16.9f"),
            header="k_distance_A^-1  energy_absolute_eV",
        )

    def write_detail(name, energies, bands, raw_weights, normalized_weights):
        with (output / name).open("w") as handle:
            handle.write(
                "# k_index  k_distance_A^-1  energy_absolute_eV  "
                "energy_minus_fermi_eV  band_index  raw_weight  normalized_weight\n"
            )
            for index in range(nk):
                if not np.isfinite(energies[index]):
                    continue
                relative = energies[index] - fermi if fermi is not None else float("nan")
                handle.write(
                    f"{index + 1:8d} {k_distance[index]:18.10f} {energies[index]:19.10f} "
                    f"{relative:22.10f} {bands[index]:11d} {raw_weights[index]:16.10e} "
                    f"{normalized_weights[index]:18.10e}\n"
                )

    write_simple("VBM.dat", vbm_energy)
    write_simple("CBM.dat", cbm_energy)
    write_detail("VBM_unfold_detail.dat", vbm_energy, vbm_bands, vbm_weight, vbm_weight_norm)
    write_detail("CBM_unfold_detail.dat", cbm_energy, cbm_bands, cbm_weight, cbm_weight_norm)

    band_min = np.nanmin(energy_absolute, axis=1)
    band_max = np.nanmax(energy_absolute, axis=1)
    crossing_rows = np.where(
        (band_min < reference_absolute - energy_tolerance)
        & (band_max > reference_absolute + energy_tolerance)
    )[0]
    crossing_bands = [int(row + first_band) for row in crossing_rows]

    def band_counts(bands):
        return {
            str(key): int(value)
            for key, value in sorted(collections.Counter(int(item) for item in bands if item > 0).items())
        }

    def ownership_switches(bands, present):
        count = 0
        for index in range(1, nk):
            if not (present[index - 1] and present[index]):
                continue
            if abs(k_distance[index] - k_distance[index - 1]) <= 1.0e-12:
                continue
            if bands[index] != bands[index - 1]:
                count += 1
        return count

    path_vbm = float(np.nanmax(vbm_energy)) if np.any(has_vbm) else None
    path_cbm = float(np.nanmin(cbm_energy)) if np.any(has_cbm) else None
    report = {
        "selection_method": "per-k upper/lower energy envelope",
        "energy_reference_mode": reference_mode,
        "energy_reference_input_eV": reference_input,
        "energy_reference_absolute_eV": reference_absolute,
        "fermi_energy_eV": fermi,
        "energy_tolerance_eV": energy_tolerance,
        "plot_window_half_width_eV": plot_window,
        "plot_edge_break_threshold_eV": 0.5,
        "plot_background_weight_encoding": False,
        "plot_background_alpha": 0.38,
        "normalized_weight_threshold": weight_threshold,
        "weight_filter_enabled": bool(weight_threshold > 0),
        "first_band": first_band,
        "nbnd": nbnd,
        "nk": nk,
        "crossing_bands": crossing_bands,
        "vbm_selected_band_counts": band_counts(vbm_bands),
        "cbm_selected_band_counts": band_counts(cbm_bands),
        "vbm_band_ownership_switches": ownership_switches(vbm_bands, has_vbm),
        "cbm_band_ownership_switches": ownership_switches(cbm_bands, has_cbm),
        "vbm_missing_kpoints": int(np.count_nonzero(~has_vbm)),
        "cbm_missing_kpoints": int(np.count_nonzero(~has_cbm)),
        "path_vbm_absolute_eV": path_vbm,
        "path_cbm_absolute_eV": path_cbm,
        "path_envelope_gap_eV": (
            path_cbm - path_vbm if path_vbm is not None and path_cbm is not None else None
        ),
    }
    (output / "band-edge-summary.json").write_text(json.dumps(report, indent=2) + "\n")

    if fermi is not None:
        plot_energy = energy_absolute - fermi
        plot_vbm = vbm_energy - fermi
        plot_cbm = cbm_energy - fermi
        plot_reference = reference_absolute - fermi
        ylabel = r"Energy - $E_F$ (eV)"
    else:
        plot_energy = energy_absolute
        plot_vbm = vbm_energy
        plot_cbm = cbm_energy
        plot_reference = reference_absolute
        ylabel = "Energy (eV)"

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "font.size": 13.0,
        "axes.linewidth": 0.8,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    fig, ax = plt.subplots(figsize=(8.0, 6.0))
    plot_low = plot_reference - plot_window
    plot_high = plot_reference + plot_window
    k_grid = np.broadcast_to(k_distance, plot_energy.shape)
    background_mask = (
        np.isfinite(plot_energy)
        & (plot_energy >= plot_low)
        & (plot_energy <= plot_high)
    )
    ax.scatter(
        k_grid[background_mask],
        plot_energy[background_mask],
        s=3.0,
        color=(0.0, 0.12, 0.55),
        alpha=0.38,
        linewidths=0,
        zorder=1,
    )

    def draw_envelope(energies, present, color):
        start = None
        for index in range(nk):
            valid = bool(present[index] and np.isfinite(energies[index]))
            disconnected = (
                index > 0
                and (
                    abs(k_distance[index] - k_distance[index - 1]) <= 1.0e-12
                    or (
                        present[index - 1]
                        and np.isfinite(energies[index - 1])
                        and abs(energies[index] - energies[index - 1]) > 0.5
                    )
                )
            )
            if valid and not disconnected:
                if start is None:
                    start = index
                continue
            if start is not None:
                end = index
                if end - start >= 2:
                    ax.plot(
                        k_distance[start:end], energies[start:end],
                        color=color, linewidth=4.0,
                        solid_capstyle="round", solid_joinstyle="round", zorder=4,
                    )
                elif end - start == 1:
                    ax.scatter(k_distance[start], energies[start], s=12, color=color, zorder=4)
                start = None
            if valid and disconnected:
                start = index
        if start is not None:
            if nk - start >= 2:
                ax.plot(
                    k_distance[start:nk], energies[start:nk],
                    color=color, linewidth=4.0,
                    solid_capstyle="round", solid_joinstyle="round", zorder=4,
                )
            else:
                ax.scatter(k_distance[start], energies[start], s=12, color=color, zorder=4)

    draw_envelope(plot_vbm, has_vbm, "#F23D18")
    draw_envelope(plot_cbm, has_cbm, "#19B43B")
    ax.axhline(plot_reference, color="#1F77B4", linestyle="--", linewidth=0.9, zorder=2)

    tick_indices = metadata.get("tick_indices", [])
    tick_labels = metadata.get("tick_labels", [])
    combined_ticks = []
    for index, label in zip(tick_indices, tick_labels):
        index = int(index)
        if index < 0 or index >= nk:
            continue
        position = float(k_distance[index])
        label = r"$\Gamma$" if str(label).upper() == "GAMMA" else str(label)
        if combined_ticks and math.isclose(position, combined_ticks[-1][0], abs_tol=1.0e-12):
            combined_ticks[-1][1] += "|" + label
        else:
            combined_ticks.append([position, label])
    for position, _label in combined_ticks:
        ax.axvline(position, color="#555555", linewidth=0.8, linestyle=(0, (8, 4)), zorder=0)
    if combined_ticks:
        ax.set_xticks([item[0] for item in combined_ticks])
        ax.set_xticklabels([item[1] for item in combined_ticks], fontsize=10)
    ax.set_xlim(float(k_distance[0]), float(k_distance[-1]))
    ax.set_ylim(plot_low, plot_high)
    ax.set_xlabel("k-path")
    ax.set_ylabel(ylabel)
    ax.tick_params(direction="out", width=0.8)
    fig.tight_layout()
    fig.savefig(output / "VBM_CBM_on_unfold_band.png", dpi=300)
    fig.savefig(output / "VBM_CBM_on_unfold_band.svg")
    plt.close(fig)

    print(f"能量分界（绝对）={reference_absolute:.8f} eV")
    if fermi is not None:
        print(f"Fermi={fermi:.8f} eV；分界 E-EF={reference_absolute - fermi:.8f} eV")
    print(f"路径 VBM={path_vbm:.8f} eV" if path_vbm is not None else "路径 VBM=未找到")
    print(f"路径 CBM={path_cbm:.8f} eV" if path_cbm is not None else "路径 CBM=未找到")
    print("跨越分界能量的 band=" + (",".join(map(str, crossing_bands)) if crossing_bands else "无"))
    print(f"已生成 {output / 'VBM.dat'}、{output / 'CBM.dat'}")
    print(f"已生成 {output / 'VBM_CBM_on_unfold_band.png'} 和 SVG")


if __name__ == "__main__":
    main()
