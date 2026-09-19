"""io.unfold patch bands: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import pathlib
    import re
    import sys

    input_path = pathlib.Path(_argv[1])
    kpoints_path = pathlib.Path(_argv[2])
    text = input_path.read_text()
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"\s*K_POINTS\b", line, re.I)), None)
    if start is None:
        raise SystemExit(f"{input_path} 中没有 K_POINTS 卡片")
    count_index = start + 1
    while count_index < len(lines) and not lines[count_index].strip():
        count_index += 1
    if count_index >= len(lines) or not re.fullmatch(r"\s*\d+\s*", lines[count_index]):
        raise SystemExit(f"{input_path} 的 K_POINTS crystal_b 数量行无效")
    count = int(lines[count_index].strip())
    end = count_index + 1 + count
    if end > len(lines):
        raise SystemExit(f"{input_path} 的 K_POINTS 数据行不足")
    new_lines = lines[:start] + kpoints_path.read_text().splitlines() + lines[end:]
    text = "\n".join(new_lines) + "\n"

    control = re.search(r"(?ims)^\s*&CONTROL\b(.*?)^\s*/\s*$", text)
    if not control:
        raise SystemExit(f"{input_path} 中没有有效的 &CONTROL")
    body = control.group(1)
    body = re.sub(r"(?im)^\s*wf_collect\s*=.*$", "", body)
    body = re.sub(r"(?im)^\s*disk_io\s*=.*$", "", body)
    replacement = "&CONTROL" + body.rstrip() + "\n   wf_collect      = .true.\n   disk_io         = 'low'\n /"
    text = text[:control.start()] + replacement + text[control.end():]
    input_path.write_text(text)


if __name__ == "__main__":
    main()
