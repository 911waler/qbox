"""io.convert pymatgen: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    import sys
    from pymatgen.core import Structure

    mode, infile, outfile = _argv[1], _argv[2], _argv[3]
    fmt = "poscar" if mode == "cif2vasp" else "cif"
    structure = Structure.from_file(infile)
    structure.to(filename=outfile, fmt=fmt)


if __name__ == "__main__":
    main()
