"""io.upf valence: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    from pathlib import Path
    import re
    import sys

    text = Path(_argv[1]).read_text(errors="ignore")
    patterns = [
        r"z_valence\s*=\s*['\"]?\s*([-+]?\d+(?:\.\d*)?(?:[eEdD][-+]?\d+)?)",
        r"Z\s+valence[^0-9+\-.]*([-+]?\d+(?:\.\d*)?(?:[eEdD][-+]?\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            val = float(m.group(1).replace("D", "E").replace("d", "e"))
            if val > 0:
                print(f"{val:.10g}")
                sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
