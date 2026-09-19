"""io.ldos reference: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import re
    import sys
    from pathlib import Path

    path = Path(_argv[1])
    text = path.read_text(errors="ignore")

    prefix = ""
    matches = re.findall(r"[/']([^/'\s]+)\.save", text)
    if matches:
        prefix = matches[-1]

    fermi = ""
    m = re.search(r"the Fermi energy is\s+([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+ev", text, re.I)
    if m:
        fermi = m.group(1)
    else:
        m = re.search(r"highest occupied,\s*lowest unoccupied level\s*\(ev\):\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)", text, re.I)
        if m:
            fermi = f"{(float(m.group(1)) + float(m.group(2))) / 2.0:.8f}"

    fft = re.findall(r"FFT dimensions:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", text, re.I)
    x = y = z = ""
    if fft:
        x, y, z = fft[-1]

    print(prefix, fermi, x, y, z)


if __name__ == "__main__":
    main()
