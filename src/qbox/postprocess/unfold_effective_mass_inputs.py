"""postprocess.unfold effective mass inputs: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import json
    import math
    import pathlib
    import sys

    cbm_path, metadata_path, converted_path, labels_path = map(pathlib.Path, _argv[1:])
    metadata = json.loads(metadata_path.read_text())
    k_distance = [float(value) for value in metadata.get("k_distance_inverse_angstrom", [])]
    tick_indices = [int(value) for value in metadata.get("tick_indices", [])]
    tick_labels = [str(value) for value in metadata.get("tick_labels", [])]

    points = []
    for raw in cbm_path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            points.append((float(fields[0]), float(fields[1])))

    if not points:
        raise SystemExit(f"{cbm_path} 没有可用的 CBM 数据")
    if len(points) != len(k_distance):
        raise SystemExit(
            f"{cbm_path} 仅包含 {len(points)} 个 K 点，但 unfold metadata 包含 "
            f"{len(k_distance)} 个；请用权重阈值 0 重新提取完整 CBM.dat"
        )
    if any(abs(k - expected) > 2.0e-6 for (k, _energy), expected in zip(points, k_distance)):
        raise SystemExit(f"{cbm_path} 的 K 距离与 {metadata_path} 不一致")
    if not tick_indices or len(tick_indices) != len(tick_labels):
        raise SystemExit(f"{metadata_path} 缺少完整 tick_indices/tick_labels")
    if tick_indices[0] != 0 or tick_indices[-1] != len(points) - 1:
        raise SystemExit(f"{metadata_path} 的首尾高对称点索引无效")

    split_indices = set(tick_indices[1:-1])
    converted_points = []
    for index, point in enumerate(points):
        converted_points.append(point)
        if index not in split_indices:
            continue
        previous_same = index > 0 and abs(points[index - 1][0] - point[0]) <= 1.0e-10
        next_same = index + 1 < len(points) and abs(points[index + 1][0] - point[0]) <= 1.0e-10
        if not previous_same and not next_same:
            converted_points.append(point)

    merged_labels = []
    for index, label in zip(tick_indices, tick_labels):
        x = k_distance[index]
        clean = label.strip() or "K"
        if merged_labels and abs(x - merged_labels[-1][1]) <= 1.0e-10:
            merged_labels[-1] = (f"{merged_labels[-1][0]}|{clean}", x)
        else:
            merged_labels.append((clean, x))

    with converted_path.open("w") as handle:
        handle.write("# k(Angstrom^-1)  Energy(eV)\n")
        handle.write("# Prepared directly from QE unfold CBM.dat; no alat conversion applied.\n")
        for k, energy in converted_points:
            handle.write(f"{k:14.9f} {energy:16.9f}\n")

    with labels_path.open("w") as handle:
        handle.write("# K-Label  K-Coordinate(Angstrom^-1)\n")
        for label, x in merged_labels:
            handle.write(f"{label:16s} {x:14.9f}\n")

    print(f"[OK] unfold CBM K 点：{len(points)}；插入分段边界后：{len(converted_points)}")
    print(f"[OK] wrote {converted_path}")
    print(f"[OK] wrote {labels_path}")


if __name__ == "__main__":
    main()
