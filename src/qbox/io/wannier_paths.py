"""Wannier/QE paths in the reciprocal basis of the original SCF cell.

Only automatic path discovery imports SeeK-path. No standardization or atom
reordering is applied to the caller's calculation cell.
"""
from dataclasses import dataclass
import math
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class Segment:
    start_label: str
    start: tuple[float, float, float]
    end_label: str
    end: tuple[float, float, float]

    def win_line(self):
        return f'{self.start_label} {_coords(self.start)} {self.end_label} {_coords(self.end)}'


@dataclass(frozen=True)
class PathResult:
    segments: tuple[Segment, ...]
    warnings: tuple[str, ...] = ()


def _coords(point):
    return ' '.join(f'{value:.12g}' for value in point)


def _vector(value):
    if isinstance(value, str):
        value = value.replace(',', ' ').split()
    try:
        values = tuple(float(str(v).replace('D', 'e').replace('d', 'e')) for v in value)
    except (TypeError, ValueError) as exc:
        raise ValueError('path coordinates must contain three finite numbers') from exc
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError('path coordinates must contain three finite numbers')
    return values


def normalize_path(path: Iterable[Any]) -> tuple[Segment, ...]:
    """Accept eight-token lines or explicit labelled segment dictionaries."""
    if isinstance(path, str):
        path = [line for line in path.splitlines() if line.strip()]
    try:
        items = list(path)
    except TypeError as exc:
        raise ValueError('kpoint_path must contain labelled segments') from exc
    if not items:
        raise ValueError('kpoint_path must not be empty')
    result = []
    for item in items:
        if isinstance(item, Segment):
            start_label, start, end_label, end = item.start_label, item.start, item.end_label, item.end
        elif isinstance(item, dict):
            try:
                start_label, start, end_label, end = (item[k] for k in ('start_label','start','end_label','end'))
            except KeyError as exc:
                raise ValueError('path segment requires start_label/start/end_label/end') from exc
        elif isinstance(item, str):
            parts = item.split()
            if len(parts) != 8:
                raise ValueError('path segment needs LABEL x y z LABEL x y z')
            start_label, start, end_label, end = parts[0],parts[1:4],parts[4],parts[5:8]
        else:
            raise ValueError('unsupported path segment')
        start, end = _vector(start), _vector(end)
        if start == end:
            raise ValueError('path segment endpoints must differ')
        for label, point in ((start_label,start),(end_label,end)):
            if not isinstance(label,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_+'\-]{0,19}",label):
                raise ValueError('path labels require 1–20 ASCII letters/numbers/underscore/+- or prime marks')
        result.append(Segment(start_label,start,end_label,end))
    return tuple(result)


def qe_path_card(path, points_per_segment=100):
    """Use QE crystal_b interpolation; zero weight marks a path break.

    Equal sample parameters do not guarantee the same W90 interpolation points.
    Use qe_band_kpt_card on the actual W90 output for pointwise comparisons.
    """
    if isinstance(points_per_segment,bool) or not isinstance(points_per_segment,int) or points_per_segment < 1:
        raise ValueError('points_per_segment must be a positive integer')
    segments = normalize_path(path)
    rows = []
    for index, segment in enumerate(segments):
        rows.append(f'{_coords(segment.start)} {points_per_segment} ! {segment.start_label}')
        if index + 1 == len(segments):
            rows.append(f'{_coords(segment.end)} 1 ! {segment.end_label}')
        elif segment.end != segments[index+1].start:
            rows.append(f'{_coords(segment.end)} 0 ! {segment.end_label}')
    return '\n'.join(['K_POINTS crystal_b',str(len(rows)),*rows]) + '\n'


def read_band_kpt(text: str) -> tuple[tuple[float,float,float], ...]:
    """Read the fractional coordinates in W90's seed_band.kpt, unchanged."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    try:
        count = int(lines[0])
    except (IndexError,ValueError) as exc:
        raise ValueError('band.kpt requires an integer point count') from exc
    if count < 1 or len(lines) != count + 1:
        raise ValueError('band.kpt point count does not match rows')
    points = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) != 4:
            raise ValueError('band.kpt requires three coordinates and a weight')
        points.append(_vector(parts[:3]))
        try:
            weight = float(parts[3].replace('D','e').replace('d','e'))
        except ValueError as exc:
            raise ValueError('invalid band.kpt weight') from exc
        if not math.isfinite(weight) or weight < 0:
            raise ValueError('band.kpt weight must be finite and nonnegative')
    return tuple(points)


def qe_band_kpt_card(text: str) -> str:
    points = read_band_kpt(text)
    return '\n'.join(['K_POINTS crystal',str(len(points)),*(f'{_coords(p)} 1' for p in points)]) + '\n'


def automatic_path(cell, positions, species, magnetic=False, with_time_reversal=None):
    """Get SeeK-path's original-cell path; distinct QE species stay distinct.

    The original-cell API handles axis permutations and nonprimitive cells.
    In a supercell this represents the associated primitive-cell path folded
    into the original reciprocal basis, not a new supercell symmetry path.
    """
    cell = tuple(_vector(row) for row in cell)
    positions = tuple(_vector(row) for row in positions)
    species = tuple(species)
    if len(cell) != 3 or not positions or len(positions) != len(species):
        raise ValueError('automatic path requires a 3x3 cell and matching atoms/species')
    a,b,c = cell
    det = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    if abs(det) < 1e-12:
        raise ValueError('automatic path cell is singular')
    if with_time_reversal is None:
        with_time_reversal = not magnetic
    if not isinstance(with_time_reversal,bool):
        raise ValueError('with_time_reversal must be a boolean')
    try:
        import seekpath
    except ImportError as exc:
        raise ValueError('automatic paths require optional seekpath; enter kpoint_path manually') from exc
    species_ids = {label:i+1 for i,label in enumerate(dict.fromkeys(species))}
    data = seekpath.get_path_orig_cell((cell,positions,[species_ids[label] for label in species]),
                                      with_time_reversal=with_time_reversal)
    segments = normalize_path([dict(start_label=a,start=data['point_coords'][a],
                                    end_label=b,end=data['point_coords'][b]) for a,b in data['path']])
    warnings = []
    if magnetic:
        warnings.append('Geometric symmetry is not magnetic symmetry; the path uses distinct QE species and conservative time reversal unless explicitly overridden.')
    if data.get('is_supercell'):
        warnings.append('Supercell: this is the associated primitive-cell path expressed in the original reciprocal basis.')
    return PathResult(segments,tuple(warnings))
