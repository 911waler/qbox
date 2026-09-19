#!/usr/bin/env python3
"""Package-local compatibility entry for the dopant PDOS workflow."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qbox.postprocess.dopant_pdos import main

if __name__ == "__main__":
    raise SystemExit(main())
