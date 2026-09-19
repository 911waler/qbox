"""io.effective mass inputs: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import re
    import sys
    from pathlib import Path

    scf_src = Path(_argv[1])
    bands_src = Path(_argv[2])
    bandsx_src = Path(_argv[3])
    em_dir = Path(_argv[4])
    prefix = _argv[5]
    em_kpoints_src = Path(_argv[6]) if len(_argv) > 6 and _argv[6] else None

    scf_text = scf_src.read_text(errors="ignore")
    bands_text = bands_src.read_text(errors="ignore")
    bandsx_text = bandsx_src.read_text(errors="ignore")

    def get_value(text, key, default):
        m = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*([^,\n]+)", text)
        return m.group(1).strip() if m else default

    pseudo_dir = get_value(scf_text, "pseudo_dir", get_value(bands_text, "pseudo_dir", "'./'"))
    ecutwfc = get_value(scf_text, "ecutwfc", "80")
    ecutrho = get_value(scf_text, "ecutrho", "800")
    nat = get_value(scf_text, "nat", get_value(bands_text, "nat", "0"))
    ntyp = get_value(scf_text, "ntyp", get_value(bands_text, "ntyp", "0"))

    def replace_value(text, key, value):
        pattern = re.compile(rf"(?im)^(\s*{re.escape(key)}\s*=\s*)[^,\n]+(,?)")
        if pattern.search(text):
            return pattern.sub(rf"\g<1>{value}\2", text, count=1)
        return text

    def ensure_system_key(text, key, value):
        if re.search(rf"(?im)^\s*{re.escape(key)}\s*=", text):
            return replace_value(text, key, value)
        return re.sub(r"(?im)^(\s*/\s*)$", f"   {key:<15s} = {value}\n\\1", text, count=1)

    def remove_system_keys(text, keys):
        for key in keys:
            text = re.sub(rf"(?im)^\s*{re.escape(key)}\s*=.*\n?", "", text)
        return text

    def extract_tail(text):
        m = re.search(r"(?ims)^\s*CELL_PARAMETERS\b.*$", text)
        if not m:
            raise RuntimeError("未能从输入文件读取 CELL_PARAMETERS 及后续结构信息。")
        return m.group(0).rstrip() + "\n"

    def extract_kpoints(text):
        m = re.search(r"(?ims)^\s*K_POINTS\s*(?:\{|\()?crystal_b(?:\}|\))?.*$", text)
        if not m:
            raise RuntimeError("未能从 bands 输入文件读取 K_POINTS crystal_b。")
        return m.group(0).rstrip() + "\n"

    scf_out = scf_text
    scf_out = replace_value(scf_out, "calculation", "'scf'")
    scf_out = replace_value(scf_out, "outdir", "'./tmp'")
    scf_out = replace_value(scf_out, "prefix", f"'{prefix}'")
    scf_out = replace_value(scf_out, "verbosity", "'high'")
    if not re.search(r"(?im)^\s*tstress\s*=", scf_out):
        scf_out = re.sub(r"(?im)^(\s*/\s*)$", "   tstress         = .true.\n\\1", scf_out, count=1)
    if not re.search(r"(?im)^\s*tprnfor\s*=", scf_out):
        scf_out = re.sub(r"(?im)^(\s*/\s*)$", "   tprnfor         = .true.\n\\1", scf_out, count=1)

    bands_out = bands_text
    bands_out = replace_value(bands_out, "calculation", "'bands'")
    bands_out = replace_value(bands_out, "outdir", "'./tmp'")
    bands_out = replace_value(bands_out, "prefix", f"'{prefix}'")
    bands_out = replace_value(bands_out, "verbosity", "'high'")
    if em_kpoints_src and em_kpoints_src.is_file():
        kpoints = em_kpoints_src.read_text(errors="ignore").strip() + "\n"
        bands_out = re.sub(r"(?ims)^\s*K_POINTS\b.*$", kpoints, bands_out)

    bx = bandsx_text
    bx = replace_value(bx, "prefix", f"'{prefix}'")
    bx = replace_value(bx, "outdir", "'./tmp'")
    bx = replace_value(bx, "filband", "'bands.dat'")
    if not re.search(r"(?im)^\s*filband\s*=", bx):
        bx = re.sub(r"(?im)^(\s*/\s*)$", "   filband         = 'bands.dat'\n\\1", bx, count=1)
    if not re.search(r"(?im)^\s*lsym\s*=", bx):
        bx = re.sub(r"(?im)^(\s*/\s*)$", "   lsym            = .false.\n\\1", bx, count=1)

    (em_dir / f"{prefix}.scf.in").write_text(scf_out, encoding="utf-8")
    (em_dir / f"{prefix}.bands.in").write_text(bands_out, encoding="utf-8")
    (em_dir / "bands.in").write_text(bx, encoding="utf-8")
    print(f"wrote {em_dir / (prefix + '.scf.in')}")
    print(f"wrote {em_dir / (prefix + '.bands.in')}")
    print(f"wrote {em_dir / 'bands.in'}")


if __name__ == "__main__":
    main()
