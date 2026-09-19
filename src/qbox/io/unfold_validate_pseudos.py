"""io.unfold validate pseudos: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import pathlib
    import re
    import sys

    input_path = pathlib.Path(_argv[1])
    text = input_path.read_text()
    match = re.search(r"(?im)^\s*pseudo_dir\s*=\s*['\"]([^'\"]+)", text)
    if not match:
        raise SystemExit(f"{input_path} 未设置 pseudo_dir")
    pseudo_dir = pathlib.Path(match.group(1)).expanduser()
    lines = text.splitlines()
    ntyp_match = re.search(r"(?im)^\s*ntyp\s*=\s*(\d+)", text)
    if not ntyp_match:
        raise SystemExit(f"{input_path} 未设置 ntyp")
    ntyp = int(ntyp_match.group(1))
    try:
        start = next(i for i, line in enumerate(lines) if re.match(r"\s*ATOMIC_SPECIES\b", line, re.I)) + 1
    except StopIteration:
        raise SystemExit(f"{input_path} 没有 ATOMIC_SPECIES")
    files = []
    for line in lines[start:]:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 3:
            break
        files.append(fields[2])
        if len(files) == ntyp:
            break
    if len(files) != ntyp:
        raise SystemExit(f"{input_path} 仅解析到 {len(files)}/{ntyp} 个赝势文件")
    for name in files:
        path = pseudo_dir / name
        if not path.is_file():
            raise SystemExit(f"赝势文件不存在：{path}")
        header = path.read_text(errors="replace")[:20000]
        if not re.search(r'pseudo_type\s*=\s*["\']NC["\']', header, re.I):
            raise SystemExit(f"unfold 仅允许 NC 赝势：{path}")
        if re.search(r'is_ultrasoft\s*=\s*["\']T["\']|is_paw\s*=\s*["\']T["\']', header, re.I):
            raise SystemExit(f"检测到 USPP/PAW 赝势：{path}")


if __name__ == "__main__":
    main()
