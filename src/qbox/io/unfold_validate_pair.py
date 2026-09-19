"""io.unfold validate pair: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import pathlib
    import re
    import sys

    scf_path, bands_path = map(pathlib.Path, _argv[1:3])
    scf_nelec, bands_nelec = map(float, _argv[3:5])

    def read_value(text, key):
        match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*([^\n,!/]+)", text)
        return match.group(1).strip().strip("'\"").lower() if match else None

    scf = scf_path.read_text()
    bands = bands_path.read_text()
    keys = (
        "prefix", "outdir", "pseudo_dir", "ibrav", "nat", "ntyp",
        "ecutwfc", "ecutrho", "input_dft", "nspin", "noncolin", "lspinorb",
        "occupations", "smearing", "degauss", "tot_charge",
    )
    differences = []
    for key in keys:
        left = read_value(scf, key)
        right = read_value(bands, key)
        if left != right:
            differences.append(f"{key}: SCF={left!r}, bands={right!r}")
    if differences:
        raise SystemExit("SCF 与 bands 的关键参数不一致：\n  " + "\n  ".join(differences))

    if abs(scf_nelec - bands_nelec) > 1.0e-6:
        raise SystemExit(
            f"SCF 与 bands 的电子数不一致：SCF={scf_nelec:g}, bands={bands_nelec:g}"
        )
    nearest_nelec = round(scf_nelec)
    is_integer_nelec = abs(scf_nelec - nearest_nelec) <= 1.0e-6
    is_odd_nelec = is_integer_nelec and nearest_nelec % 2 == 1

    for path, text in ((scf_path, scf), (bands_path, bands)):
        nspin = read_value(text, "nspin")
        if nspin == "2":
            raise SystemExit(f"{path} 设置了 nspin=2；当前 unfold 流程按非自旋极化方案设计")
        occupations = read_value(text, "occupations")
        if occupations not in {"fixed", "smearing"}:
            raise SystemExit(
                f"{path} 的 occupations={occupations!r}；当前 unfold 流程仅支持 fixed 或 smearing"
            )
        if is_odd_nelec and occupations != "smearing":
            raise SystemExit(
                f"{path} 是非自旋极化奇电子体系（nelec={scf_nelec:g}），"
                "必须使用 occupations='smearing'"
            )
    occupation = read_value(scf, "occupations")
    electron_kind = "奇数电子" if is_odd_nelec else ("偶数电子" if is_integer_nelec else "非整数电子")
    print(
        "SCF 与 bands 的关键参数一致；"
        f"nelec={scf_nelec:g}（{electron_kind}），使用非自旋极化 {occupation} 占据。"
    )


if __name__ == "__main__":
    main()
