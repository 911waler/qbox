#!/usr/bin/env python3
"""Compatibility launcher for the packaged dopant-PDOS analysis."""
from pathlib import Path
import sys

source = Path(__file__).resolve().parent / "src"
if source.is_dir():
    sys.path.insert(0, str(source))

from qbox.postprocess.dopant_pdos import main


if __name__ == "__main__":
    main()
