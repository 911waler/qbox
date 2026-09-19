#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calculate effective masses from QE CBM.dat with correct k-unit conversion.

QE bands.x writes the path coordinate in units of 2*pi/alat.  The existing
VASP effective-mass script expects k in Angstrom^-1, so this wrapper converts
both CBM.dat and high-symmetry labels before delegating the fit.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

BOHR_TO_ANGSTROM = 0.529177210903


def read_alat_angstrom(paths: Sequence[Path]) -> float:
    patterns = [
        re.compile(r"lattice parameter \(alat\)\s*=\s*([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s*a\.u\.", re.I),
        re.compile(r"celldm\(1\)\s*=\s*([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)", re.I),
    ]
    for path in paths:
        if not path or not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return float(match.group(1)) * BOHR_TO_ANGSTROM
    raise RuntimeError("未能从 QE 输出文件读取 alat。请用 --alat-angstrom 手动指定。")


def read_band_points(path: Path) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    if not points:
        raise RuntimeError(f"未能从 {path} 读取 CBM 数据。")
    return points


def read_labels_from_band_input(path: Path) -> List[str]:
    labels: List[str] = []
    lines = path.read_text(errors="ignore").splitlines()
    for i, raw in enumerate(lines):
        if not re.match(r"^\s*K_POINTS\s*(?:\{|\()?crystal_b(?:\}|\))?", raw, re.I):
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            break
        npts = int(lines[j].split()[0])
        for raw_k in lines[j + 1 : j + 1 + npts]:
            if "!" in raw_k:
                labels.append(raw_k.split("!", 1)[1].strip())
            else:
                labels.append(f"K{len(labels) + 1}")
        break
    if not labels:
        raise RuntimeError(f"未能从 {path} 读取 K_POINTS crystal_b 标签。")
    return labels


def read_xcoords_from_bands_output(path: Path) -> List[float]:
    xcoords: List[float] = []
    pattern = re.compile(r"x coordinate\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)", re.I)
    for raw in path.read_text(errors="ignore").splitlines():
        match = pattern.search(raw)
        if match:
            xcoords.append(float(match.group(1)))
    if not xcoords:
        raise RuntimeError(f"未能从 {path} 读取 high-symmetry x coordinate。")
    return xcoords


def merge_adjacent_duplicate_labels(labels: Sequence[str], xcoords: Sequence[float], tol: float) -> List[Tuple[str, float]]:
    if len(labels) != len(xcoords):
        raise RuntimeError(f"高对称点标签数({len(labels)})与 x 坐标数({len(xcoords)})不一致。")
    merged: List[Tuple[str, float]] = []
    for label, x in zip(labels, xcoords):
        clean = label.strip() or "K"
        if merged and abs(x - merged[-1][1]) <= tol:
            prev_label, prev_x = merged[-1]
            merged[-1] = (f"{prev_label}|{clean}", prev_x)
        else:
            merged.append((clean, x))
    return merged


def insert_split_duplicates(
    points: Sequence[Tuple[float, float]],
    split_xcoords: Sequence[float],
    tol: float,
) -> List[Tuple[float, float]]:
    """Duplicate internal high-symmetry points so the VASP fitter sees segments.

    QE crystal_b paths are continuous across most high-symmetry points; the
    existing fitter splits path segments only when adjacent k values repeat.
    """
    if len(points) < 3:
        return list(points)

    duplicate_after = set()
    k_values = [k for k, _ in points]
    for x in split_xcoords:
        idx = min(range(len(points)), key=lambda i: abs(k_values[i] - x))
        if idx == 0 or idx == len(points) - 1:
            continue
        if abs(k_values[idx] - x) > tol:
            continue
        prev_same = abs(k_values[idx] - k_values[idx - 1]) <= tol
        next_same = abs(k_values[idx] - k_values[idx + 1]) <= tol
        if prev_same or next_same:
            continue
        duplicate_after.add(idx)

    out: List[Tuple[float, float]] = []
    for idx, point in enumerate(points):
        out.append(point)
        if idx in duplicate_after:
            out.append(point)
    return out


def write_converted_band(points: Iterable[Tuple[float, float]], out: Path, scale: float) -> None:
    with out.open("w", encoding="utf-8") as fw:
        fw.write("# k(Angstrom^-1)  Energy(eV)\n")
        fw.write(f"# Converted from QE bands.x coordinate by scale = 2*pi/alat = {scale:.12f} Angstrom^-1\n")
        for k_qe, energy in points:
            fw.write(f"{k_qe * scale:12.6f} {energy:14.8f}\n")


def write_converted_labels(labels: Sequence[Tuple[str, float]], out: Path, scale: float) -> None:
    with out.open("w", encoding="utf-8") as fw:
        fw.write("# K-Label  K-Coordinate(Angstrom^-1)\n")
        for label, x_qe in labels:
            fw.write(f"{label:16s} {x_qe * scale:12.6f}\n")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Convert QE CBM.dat k-units to Angstrom^-1 and calculate effective mass."
    )
    parser.add_argument("-b", "--band", default="CBM.dat", help="QE CBM.dat file.")
    parser.add_argument("--band-input", default="vcrelax.bands.in", help="QE pw.x bands input with K_POINTS crystal_b labels.")
    parser.add_argument("--bands-output", default="bands.out", help="QE bands.x output with high-symmetry x coordinates.")
    parser.add_argument("--qe-output", default="band.out", help="QE pw.x bands output used to read alat.")
    parser.add_argument("--scf-output", default="scf.out", help="Fallback QE scf output used to read alat.")
    parser.add_argument("--alat-angstrom", type=float, default=None, help="Override alat in Angstrom.")
    parser.add_argument("--converted-band", default="CBM_Ainv.dat", help="Converted CBM.dat output.")
    parser.add_argument("--converted-labels", default="KLABELS_QE_Ainv", help="Converted KLABELS output.")
    parser.add_argument("--vasp-script", required=True, help="Effective-mass fitting script supplied explicitly by the caller.")
    parser.add_argument("--no-split-at-labels", action="store_true", help="Do not duplicate high-symmetry k points for segment splitting.")
    parser.add_argument("--split-tol", type=float, default=5.0e-4, help="Tolerance in QE k-coordinate units for matching split points.")
    parser.add_argument("--dry-run", action="store_true", help="Only write converted files; do not run the fitting script.")
    args, passthrough = parser.parse_known_args(argv)

    band = Path(args.band)
    band_input = Path(args.band_input)
    bands_output = Path(args.bands_output)
    converted_band = Path(args.converted_band)
    converted_labels = Path(args.converted_labels)

    alat_angstrom = args.alat_angstrom
    if alat_angstrom is None:
        alat_angstrom = read_alat_angstrom([Path(args.qe_output), Path(args.scf_output)])
    if alat_angstrom <= 0:
        raise RuntimeError("alat 必须大于 0。")

    scale = 2.0 * math.pi / alat_angstrom
    points = read_band_points(band)
    labels = read_labels_from_band_input(band_input)
    xcoords = read_xcoords_from_bands_output(bands_output)
    merged_labels = merge_adjacent_duplicate_labels(labels, xcoords, tol=1.0e-6)

    if not args.no_split_at_labels:
        points = insert_split_duplicates(points, xcoords, tol=args.split_tol)

    write_converted_band(points, converted_band, scale)
    write_converted_labels(merged_labels, converted_labels, scale)

    print(f"[OK] alat = {alat_angstrom:.9f} Angstrom")
    print(f"[OK] k scale = 2*pi/alat = {scale:.12f} Angstrom^-1")
    print(f"[OK] wrote {converted_band}")
    print(f"[OK] wrote {converted_labels}")

    if args.dry_run:
        return

    cmd = [sys.executable]
    if os.environ.get("_QBOX_OFFLINE_ROOT"):
        cmd.extend(["-I", "-B"])
    cmd.extend([
        args.vasp_script,
        "-b",
        str(converted_band),
        "-l",
        str(converted_labels),
        *passthrough,
    ])
    print("[RUN] " + " ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
