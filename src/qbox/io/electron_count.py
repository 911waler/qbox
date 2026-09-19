"""io.electron count: file-oriented scientific workflow."""

def main(argv=None):
    """Run the workflow with explicit CLI-style arguments."""
    import sys
    _argv = [__file__, *(sys.argv[1:] if argv is None else argv)]
    from pathlib import Path
    import re
    import sys

    path = Path(_argv[1])
    text = path.read_text(errors="ignore").splitlines()
    pseudo_dir = Path(".")
    species = {}
    counts = {}
    tot_charge = 0.0
    in_species = False
    in_pos = False

    for raw in text:
        line = raw.strip()
        low = line.lower()
        if low.startswith("pseudo_dir") and "=" in line:
            value = line.split("=", 1)[1].strip().strip(",").strip("'\"")
            pseudo_dir = Path(value).expanduser()
        if low.startswith("tot_charge") and "=" in line:
            value = line.split("=", 1)[1].split("!", 1)[0].strip().strip(",")
            try:
                tot_charge = float(value.replace("D", "E").replace("d", "e"))
            except ValueError:
                sys.exit(1)
        if low.startswith("atomic_species"):
            in_species = True
            in_pos = False
            continue
        if low.startswith("atomic_positions"):
            in_pos = True
            in_species = False
            continue
        if line.startswith("&") or line == "/" or low.startswith(("cell_parameters", "k_points")):
            in_species = False
            if not low.startswith("atomic_positions"):
                in_pos = False
        if in_species and line and not line.startswith(("!", "#")):
            parts = line.split()
            if len(parts) >= 3:
                species[parts[0]] = parts[2]
        elif in_pos and line and not line.startswith(("!", "#")):
            parts = line.split()
            if len(parts) >= 4 and re.match(r"^[A-Za-z][A-Za-z]?$", parts[0]):
                counts[parts[0]] = counts.get(parts[0], 0) + 1

    def z_valence(pp):
        try:
            data = pp.read_text(errors="ignore")
        except Exception:
            return None
        m = re.search(r"z_valence\s*=\s*['\"]?\s*([-+]?\d+(?:\.\d*)?(?:[eEdD][-+]?\d+)?)", data, re.I)
        if not m:
            m = re.search(r"Z\s+valence[^0-9+\-.]*([-+]?\d+(?:\.\d*)?(?:[eEdD][-+]?\d+)?)", data, re.I)
        if not m:
            return None
        return float(m.group(1).replace("D", "E").replace("d", "e"))

    total = 0.0
    for symbol, count in counts.items():
        ppname = species.get(symbol)
        if not ppname:
            sys.exit(1)
        z = z_valence(pseudo_dir / ppname)
        if z is None or z <= 0:
            sys.exit(1)
        total += z * count

    total -= tot_charge
    if total <= 0:
        sys.exit(1)
    print(f"{total:.10g}")


if __name__ == "__main__":
    main()
