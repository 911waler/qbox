"""postprocess.band edges reference: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import sys
    from pathlib import Path

    bands_file = Path(_argv[1])
    reference = float(_argv[2])
    vbm_out = Path(_argv[3])
    cbm_out = Path(_argv[4])

    blocks = []
    current = []
    for raw in bands_file.read_text(errors="ignore").splitlines():
        if raw.strip():
            parts = raw.split()
            if len(parts) >= 2:
                current.append((float(parts[0]), float(parts[1])))
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    tol = 1.0e-7
    valence_candidates = []
    conduction_candidates = []
    crossing_bands = []

    for band_index, block in enumerate(blocks, start=1):
        energies = [energy for _, energy in block]
        band_min = min(energies)
        band_max = max(energies)
        if band_max < reference - tol:
            valence_candidates.append((band_max, band_index))
        elif band_min > reference + tol:
            conduction_candidates.append((band_min, band_index))
        else:
            crossing_bands.append((band_index, band_min, band_max))

    best_vbm = None
    best_cbm = None
    if valence_candidates:
        _, vbm_index = max(valence_candidates)
        block = blocks[vbm_index - 1]
        k_index, (k, energy) = max(enumerate(block, start=1), key=lambda item: item[1][1])
        best_vbm = (vbm_index, k_index, energy)
    if conduction_candidates:
        _, cbm_index = min(conduction_candidates)
        block = blocks[cbm_index - 1]
        k_index, (k, energy) = min(enumerate(block, start=1), key=lambda item: item[1][1])
        best_cbm = (cbm_index, k_index, energy)

    def write_band(match, outfile):
        if match is None:
            return False
        band_index, _, _ = match
        outfile.write_text("\n".join(f"{k:12.6f} {e:14.8f}" for k, e in blocks[band_index - 1]) + "\n")
        return True

    vbm_ok = write_band(best_vbm, vbm_out)
    cbm_ok = write_band(best_cbm, cbm_out)

    print(f"available_bands={len(blocks)}")
    print(f"reference_energy={reference:.8f}")
    print("selection_method=manual_reference")
    if crossing_bands:
        indexes = ",".join(str(item[0]) for item in crossing_bands)
        print(f"warning_crossing_bands={indexes}")
    if best_vbm:
        print(f"vbm_band={best_vbm[0]} vbm_k_index={best_vbm[1]} vbm_energy={best_vbm[2]:.8f} vbm_relative={best_vbm[2] - reference:.8f}")
    if best_cbm:
        print(f"cbm_band={best_cbm[0]} cbm_k_index={best_cbm[1]} cbm_energy={best_cbm[2]:.8f} cbm_relative={best_cbm[2] - reference:.8f}")

    if vbm_ok and cbm_ok:
        raise SystemExit(0)
    if vbm_ok or cbm_ok:
        raise SystemExit(2)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
