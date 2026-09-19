"""postprocess.unfold geometry: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import json
    import math
    import pathlib
    import sys
    import warnings

    import numpy as np
    import seekpath
    from pymatgen.core import Structure
    from pymatgen.analysis.structure_matcher import ElementComparator, StructureMatcher

    warnings.filterwarnings("ignore", message=r"Issues encountered while parsing CIF:.*")

    primitive_path, supercell_path, defect_path, spacing_text, output_text = _argv[1:]
    k_spacing = float(spacing_text)
    if not math.isfinite(k_spacing) or k_spacing <= 0:
        raise SystemExit("原胞高对称路径 K 点间距必须是正数")
    output = pathlib.Path(output_text)
    primitive = Structure.from_file(primitive_path)
    supercell = Structure.from_file(supercell_path)
    defect = Structure.from_file(defect_path)

    a_pc = np.asarray(primitive.lattice.matrix, dtype=float)
    a_sc = np.asarray(supercell.lattice.matrix, dtype=float)
    m_float = a_sc @ np.linalg.inv(a_pc)
    m = np.rint(m_float).astype(int)
    residual = float(np.max(np.abs(m_float - m)))
    det = int(round(np.linalg.det(m)))
    if residual > 1.0e-5:
        raise SystemExit(
            "原胞与 pure 超胞不能由整数矩阵关联："
            f"max|M_float-round(M)|={residual:.3e}"
        )
    if det <= 0 or abs(np.linalg.det(m) - det) > 1.0e-8:
        raise SystemExit(f"超胞矩阵行列式无效：det(M)={np.linalg.det(m):.12g}")
    if len(supercell) != det * len(primitive):
        raise SystemExit(
            "原子数与超胞矩阵不一致："
            f"N_SC={len(supercell)}, det(M)*N_PC={det * len(primitive)}"
        )
    generated_supercell = primitive.copy()
    generated_supercell.make_supercell(m)
    replica_matcher = StructureMatcher(
        ltol=1.0e-5,
        stol=2.0e-3,
        angle_tol=0.01,
        primitive_cell=False,
        scale=False,
        attempt_supercell=False,
        comparator=ElementComparator(),
    )
    if not replica_matcher.fit(generated_supercell, supercell):
        raise SystemExit("pure 超胞的元素和周期性位点不是母相按 M 完整复制的结果")
    lattice_error = float(np.max(np.abs(a_sc - m @ a_pc)))
    if lattice_error > 1.0e-5:
        raise SystemExit(f"超胞晶格重构误差过大：{lattice_error:.3e} Angstrom")
    defect_lattice_error = float(
        np.max(np.abs(np.asarray(defect.lattice.matrix, dtype=float) - a_sc))
    )
    if defect_lattice_error > 1.0e-5:
        raise SystemExit(
            "掺杂/缺陷结构与 pure 超胞的晶格不一致："
            f"max|A_defect-A_SC|={defect_lattice_error:.3e} Angstrom"
        )

    cell = (
        a_pc,
        np.asarray(primitive.frac_coords, dtype=float),
        [int(site.specie.Z) for site in primitive],
    )
    path_data = seekpath.get_path(cell)
    point_coords = path_data["point_coords"]
    segments = path_data["path"]
    if not segments:
        raise SystemExit("seekpath 未返回原胞高对称路径")

    entries = []
    labels = []
    segment_point_counts = []
    reciprocal_pc = np.asarray(primitive.lattice.reciprocal_lattice.matrix, dtype=float)
    for index, (start_label, end_label) in enumerate(segments):
        start = np.asarray(point_coords[start_label], dtype=float)
        end = np.asarray(point_coords[end_label], dtype=float)
        segment_length = float(np.linalg.norm((end - start) @ reciprocal_pc))
        points = max(1, int(math.ceil(segment_length / k_spacing)))
        if index and segments[index - 1][1] != start_label:
            previous_end = np.asarray(point_coords[segments[index - 1][1]], dtype=float)
            entries.append((previous_end, 1, segments[index - 1][1]))
        entries.append((start, points, start_label))
        segment_point_counts.append(
            {
                "start": start_label,
                "end": end_label,
                "length_inverse_angstrom": segment_length,
                "points": points,
            }
        )
        labels.append(start_label)
    last_label = segments[-1][1]
    entries.append((np.asarray(point_coords[last_label], dtype=float), 1, last_label))
    labels.append(last_label)

    tick_indices = []
    tick_labels = []
    cursor = 0
    for _k_pc, count, label in entries:
        tick_indices.append(cursor)
        tick_labels.append(label)
        cursor += count

    expanded_kpoints_pc = []
    for index, (k_pc, count, _label) in enumerate(entries):
        if index + 1 < len(entries):
            next_k_pc = entries[index + 1][0]
            for step in range(count):
                expanded_kpoints_pc.append(
                    k_pc + (next_k_pc - k_pc) * (float(step) / float(count))
                )
        else:
            expanded_kpoints_pc.extend([k_pc.copy() for _ in range(count)])
    expanded_kpoints_pc = np.asarray(expanded_kpoints_pc, dtype=float)
    expanded_kpoints_sc = expanded_kpoints_pc @ m.T

    total_nk = len(expanded_kpoints_pc)
    k_distance = np.full(total_nk, np.nan, dtype=float)
    segment_cursor = None
    cumulative_distance = 0.0
    previous_end_label = None
    for item in segment_point_counts:
        if segment_cursor is None:
            start_index = 0
        elif previous_end_label == item["start"]:
            start_index = segment_cursor
        else:
            start_index = segment_cursor + 1
        end_index = start_index + int(item["points"])
        k_distance[start_index:end_index + 1] = np.linspace(
            cumulative_distance,
            cumulative_distance + float(item["length_inverse_angstrom"]),
            int(item["points"]) + 1,
        )
        cumulative_distance += float(item["length_inverse_angstrom"])
        segment_cursor = end_index
        previous_end_label = item["end"]
    if segment_cursor != total_nk - 1 or np.any(~np.isfinite(k_distance)):
        raise SystemExit(
            "展开路径距离构造失败："
            f"last_index={segment_cursor}, nk={total_nk}"
        )

    kpoints_lines = ["K_POINTS {crystal_b}", str(len(entries))]
    for k_pc, count, label in entries:
        k_sc = m @ k_pc
        kpoints_lines.append(
            f"{k_sc[0]: .10f} {k_sc[1]: .10f} {k_sc[2]: .10f} {count:4d} ! {label}"
        )

    output.mkdir(parents=True, exist_ok=True)
    (output / "unfold-kpoints.in").write_text("\n".join(kpoints_lines) + "\n")
    metadata = {
        "primitive_cif": pathlib.Path(primitive_path).name,
        "pristine_supercell_cif": pathlib.Path(supercell_path).name,
        "defect_supercell_cif": pathlib.Path(defect_path).name,
        "M_rows": m.tolist(),
        "SC_for_unfold": m.tolist(),
        "det_M": det,
        "matrix_rounding_residual": residual,
        "lattice_error_angstrom": lattice_error,
        "defect_lattice_error_angstrom": defect_lattice_error,
        "kpoint_spacing_inverse_angstrom": k_spacing,
        "segment_point_counts": segment_point_counts,
        "labels": labels,
        "tick_indices": tick_indices,
        "tick_labels": tick_labels,
        "expanded_kpoints_pc_fractional": expanded_kpoints_pc.tolist(),
        "expanded_kpoints_sc_fractional": expanded_kpoints_sc.tolist(),
        "k_distance_inverse_angstrom": k_distance.tolist(),
    }
    (output / "unfold-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"M={m.tolist()}")
    print(f"SC={m.tolist()}")
    print(f"det(M)={det}")
    print(
        "原胞路径逐段点数="
        + ", ".join(
            f"{item['start']}-{item['end']}:{item['points']}"
            for item in segment_point_counts
        )
    )


if __name__ == "__main__":
    main()
