"""io.unfold write input: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import json
    import pathlib
    import sys

    prefix, first_band, last_band, output_text = _argv[1:]
    output = pathlib.Path(output_text)
    metadata = json.loads((output / "unfold-metadata.json").read_text())
    sc = metadata["SC_for_unfold"]
    lines = [
        "&inputpp",
        "  outdir       = './tmp'",
        f"  prefix       = '{prefix}'",
        f"  first_band   = {int(first_band)}",
        f"  last_band    = {int(last_band)}",
        "  sumover_G_uc = .true.",
    ]
    for index, row in enumerate(sc, start=1):
        lines.append(f"  SC({index},:)      = {row[0]}, {row[1]}, {row[2]}")
    lines.append("/")
    (output / "unfold.in").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
