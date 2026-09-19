"""postprocess.unfold discover: file-oriented scientific workflow."""

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
    from pymatgen.analysis.structure_matcher import ElementComparator, StructureMatcher
    from pymatgen.core import Structure
    from scipy.optimize import linear_sum_assignment

    warnings.filterwarnings("ignore", message=r"Issues encountered while parsing CIF:.*")

    scan_dir = pathlib.Path(_argv[1]).resolve()
    report_path = pathlib.Path(_argv[2])
    if not report_path.is_absolute():
        report_path = (pathlib.Path.cwd() / report_path).resolve()


    def public_name(path):
        """Return a useful file identifier without exposing the local directory."""
        return pathlib.Path(path).name or "structure"

    MATRIX_TOL = 1.0e-5
    LATTICE_TOL_ANGSTROM = 1.0e-5
    IDENTICAL_SITE_TOL = 2.0e-3
    DEFECT_SITE_TOL_ANGSTROM = 0.35

    audit = {
        "_comment": (
            "本报告记录 qbox unfold 自动结构识别的候选、判定依据、"
            "容差、拒绝原因及最终选择，用于复核结构分类；不参与 QE 或 unfold.x 计算。"
        ),
        "scan_directory": "scan",
        "selection_basis": "structure_content_only",
        "tolerances": {
            "integer_matrix": MATRIX_TOL,
            "lattice_angstrom": LATTICE_TOL_ANGSTROM,
            "identical_site_fractional_free_length": IDENTICAL_SITE_TOL,
            "defect_site_angstrom": DEFECT_SITE_TOL_ANGSTROM,
        },
        "parse_failures": [],
        "equivalent_groups": [],
        "primitive_candidates": [],
        "pristine_candidates": [],
        "pair_assessments": [],
        "selection": None,
        "status": "ambiguous",
        "reason": "",
    }


    def finish(status, reason, selection=None):
        audit["status"] = status
        audit["reason"] = reason
        audit["selection"] = selection
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
        print(f"STATUS\t{status.upper()}")
        print(f"SUMMARY\t{reason}")
        print(f"REPORT\t{public_name(report_path)}")
        if selection:
            print(f"PRIMITIVE\t{selection['primitive']}")
            print(f"PRISTINE\t{selection['pristine_supercell']}")
            print(f"DEFECT\t{selection['defect_supercell']}")
            print(f"MODE\t{selection['mode']}")
        raise SystemExit(0)


    paths = sorted(
        path for path in scan_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".cif"
    )
    items = []
    for path in paths:
        try:
            structure = Structure.from_file(path)
            if not structure.is_ordered:
                raise ValueError("包含部分占位或无序位点")
            items.append({"path": path, "structure": structure})
        except Exception as exc:
            audit["parse_failures"].append({"path": public_name(path), "error": "结构解析失败"})

    if audit["parse_failures"]:
        finish("ambiguous", "存在无法可靠解析的 CIF，已停止自动推导")
    if len(items) < 2:
        finish("ambiguous", "当前目录至少需要两个可解析且有序的结构")

    duplicate_matcher = StructureMatcher(
        ltol=1.0e-5,
        stol=1.0e-4,
        angle_tol=0.01,
        primitive_cell=False,
        scale=False,
        attempt_supercell=False,
        comparator=ElementComparator(),
    )
    groups = []
    for item in items:
        for group in groups:
            reference = group["representative"]["structure"]
            if (
                len(reference) == len(item["structure"])
                and reference.composition == item["structure"].composition
                and duplicate_matcher.fit(reference, item["structure"])
            ):
                group["members"].append(item)
                break
        else:
            groups.append({"representative": item, "members": [item]})

    for index, group in enumerate(groups):
        group["id"] = index
        structure = group["representative"]["structure"]
        audit["equivalent_groups"].append({
            "id": index,
            "representative": public_name(group["representative"]["path"]),
            "aliases": [public_name(item["path"]) for item in group["members"]],
            "atom_count": len(structure),
            "composition": structure.composition.formula,
        })

    minimum_atoms = min(len(group["representative"]["structure"]) for group in groups)
    primitive_groups = [
        group for group in groups
        if len(group["representative"]["structure"]) == minimum_atoms
    ]
    audit["primitive_candidates"] = [
        public_name(group["representative"]["path"]) for group in primitive_groups
    ]
    if len(primitive_groups) != 1:
        finish(
            "ambiguous",
            f"最少原子数为 {minimum_atoms}，但存在 {len(primitive_groups)} 个不等价候选",
        )

    primitive_group = primitive_groups[0]
    primitive = primitive_group["representative"]["structure"]
    pristine_groups = []
    replica_matcher = StructureMatcher(
        ltol=1.0e-5,
        stol=IDENTICAL_SITE_TOL,
        angle_tol=0.01,
        primitive_cell=False,
        scale=False,
        attempt_supercell=False,
        comparator=ElementComparator(),
    )
    for group in groups:
        if group is primitive_group:
            continue
        candidate = group["representative"]["structure"]
        raw_matrix = candidate.lattice.matrix @ np.linalg.inv(primitive.lattice.matrix)
        matrix = np.rint(raw_matrix).astype(int)
        residual = float(np.max(np.abs(raw_matrix - matrix)))
        determinant_float = float(np.linalg.det(matrix))
        determinant = int(round(determinant_float))
        assessment = {
            "path": public_name(group["representative"]["path"]),
            "matrix": matrix.tolist(),
            "matrix_rounding_residual": residual,
            "determinant": determinant,
            "expected_atom_count": determinant * len(primitive),
            "actual_atom_count": len(candidate),
            "is_pristine_replica": False,
        }
        if residual > MATRIX_TOL or determinant <= 1:
            assessment["rejection"] = "晶格不是母相的有效整数扩胞"
        elif abs(determinant_float - determinant) > 1.0e-8:
            assessment["rejection"] = "扩胞矩阵行列式不是有效正整数"
        elif len(candidate) != determinant * len(primitive):
            assessment["rejection"] = "原子数不等于 det(M) 乘母相原子数"
        else:
            generated = primitive.copy()
            generated.make_supercell(matrix)
            if replica_matcher.fit(generated, candidate):
                assessment["is_pristine_replica"] = True
                pristine_groups.append((group, matrix, determinant))
            else:
                assessment["rejection"] = "元素和周期性位点不等于母相的完整复制"
        audit["pristine_candidates"].append(assessment)

    if not pristine_groups:
        finish("ambiguous", "未找到母相的完整整数倍 pure 超胞")


    def same_lattice(left, right):
        return float(np.max(np.abs(left.lattice.matrix - right.lattice.matrix))) <= LATTICE_TOL_ANGSTROM


    def compare_sites(reference, candidate):
        ref_frac = np.asarray(reference.frac_coords, dtype=float)
        cand_frac = np.asarray(candidate.frac_coords, dtype=float)
        lattice = np.asarray(reference.lattice.matrix, dtype=float)
        ref_species = [str(site.specie) for site in reference]
        cand_species = [str(site.specie) for site in candidate]

        shifts = [np.zeros(3)]
        anchor_indices = sorted(
            range(len(reference)),
            key=lambda i: (ref_species.count(ref_species[i]), i),
        )[:3]
        for i in anchor_indices:
            matching = [j for j, specie in enumerate(cand_species) if specie == ref_species[i]]
            for j in matching:
                shifts.append(ref_frac[i] - cand_frac[j])
                if len(shifts) >= 33:
                    break
            if len(shifts) >= 33:
                break

        best = None
        for shift in shifts:
            delta = cand_frac[None, :, :] + shift - ref_frac[:, None, :]
            delta -= np.rint(delta)
            distances = np.linalg.norm(delta @ lattice, axis=2)
            rows, cols = linear_sum_assignment(distances)
            matched = [
                (int(i), int(j), float(distances[i, j]))
                for i, j in zip(rows, cols)
                if distances[i, j] <= DEFECT_SITE_TOL_ANGSTROM
            ]
            score = (len(matched), -sum(value for _i, _j, value in matched))
            if best is None or score > best[0]:
                best = (score, matched, shift)

        matched = best[1]
        substitutions = []
        for i, j, distance in matched:
            if ref_species[i] != cand_species[j]:
                substitutions.append({
                    "from": ref_species[i],
                    "to": cand_species[j],
                    "distance_angstrom": distance,
                })
        matched_reference = {i for i, _j, _distance in matched}
        matched_candidate = {j for _i, j, _distance in matched}
        vacancies = len(reference) - len(matched_reference)
        interstitials = len(candidate) - len(matched_candidate)
        max_displacement = max((distance for _i, _j, distance in matched), default=0.0)
        changed = len(substitutions) + vacancies + interstitials
        allowed_changes = max(8, int(math.ceil(0.15 * len(reference))))
        reliable = changed <= allowed_changes
        return {
            "substitutions": substitutions,
            "vacancies": vacancies,
            "interstitials": interstitials,
            "max_matched_displacement_angstrom": max_displacement,
            "origin_shift_fractional": np.mod(best[2], 1.0).tolist(),
            "changed_site_count": changed,
            "allowed_changed_site_count": allowed_changes,
            "reliable": reliable,
        }


    options = []
    for pristine_group, matrix, determinant in pristine_groups:
        pristine = pristine_group["representative"]["structure"]
        modified = []
        blockers = []
        for group in groups:
            if group is pristine_group or group is primitive_group:
                continue
            candidate = group["representative"]["structure"]
            if not same_lattice(pristine, candidate):
                continue
            comparison = compare_sites(pristine, candidate)
            pair = {
                "pristine": public_name(pristine_group["representative"]["path"]),
                "candidate": public_name(group["representative"]["path"]),
                **comparison,
            }
            audit["pair_assessments"].append(pair)
            if not comparison["reliable"]:
                blockers.append(pair)
            elif comparison["changed_site_count"]:
                modified.append((group, pair))
            elif comparison["max_matched_displacement_angstrom"] > 1.0e-3:
                pair["rejection"] = "仅检测到坐标位移，无法归类为替位、增加或删除"
                blockers.append(pair)

        if blockers or len(modified) > 1:
            continue
        if len(modified) == 1:
            defect_group, comparison = modified[0]
            options.append({
                "primitive": public_name(primitive_group["representative"]["path"]),
                "pristine_supercell": public_name(pristine_group["representative"]["path"]),
                "defect_supercell": public_name(defect_group["representative"]["path"]),
                "mode": "defect",
                "matrix": matrix.tolist(),
                "determinant": determinant,
                "defect_changes": comparison,
            })
        else:
            options.append({
                "primitive": public_name(primitive_group["representative"]["path"]),
                "pristine_supercell": public_name(pristine_group["representative"]["path"]),
                "defect_supercell": public_name(pristine_group["representative"]["path"]),
                "mode": "pristine",
                "matrix": matrix.tolist(),
                "determinant": determinant,
                "defect_changes": None,
            })

    if len(options) != 1:
        finish(
            "ambiguous",
            f"得到 {len(pristine_groups)} 个 pristine 候选和 {len(options)} 个无歧义组合，不能唯一选择",
        )

    selection = options[0]
    if selection["mode"] == "pristine":
        summary = (
            f"自动识别 pure 超胞：det(M)={selection['determinant']}，"
            "未发现替位、增加或删除，pure 同时作为 defect"
        )
    else:
        changes = selection["defect_changes"]
        summary = (
            f"自动识别缺陷超胞：替位 {len(changes['substitutions'])}，"
            f"空位 {changes['vacancies']}，间隙原子 {changes['interstitials']}"
        )
    finish("ok", summary, selection)


if __name__ == "__main__":
    main()
