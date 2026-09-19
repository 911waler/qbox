"""io.convert ase: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import sys
    from ase.io import read, write

    infile, outfile = _argv[1], _argv[2]
    atoms = read(infile)
    write(outfile, atoms)


if __name__ == "__main__":
    main()
