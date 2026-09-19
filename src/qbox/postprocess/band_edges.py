"""postprocess.band edges: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import sys
    from pathlib import Path

    bands_file = Path(_argv[1])
    vbm_index = int(_argv[2])
    cbm_index = int(_argv[3])
    vbm_out = Path(_argv[4])
    cbm_out = Path(_argv[5])

    blocks = []
    current = []
    for raw in bands_file.read_text(errors="ignore").splitlines():
        if raw.strip():
            parts = raw.split()
            if len(parts) >= 2:
                current.append(f"{float(parts[0]):12.6f} {float(parts[1]):14.8f}")
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    def write_block(index, outfile):
        if 1 <= index <= len(blocks):
            outfile.write_text("\n".join(blocks[index - 1]) + "\n")
            return True
        return False

    vbm_ok = write_block(vbm_index, vbm_out)
    cbm_ok = write_block(cbm_index, cbm_out)
    print(len(blocks))
    if vbm_ok and cbm_ok:
        raise SystemExit(0)
    if vbm_ok:
        raise SystemExit(2)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
