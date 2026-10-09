"""Gamma-containing, unshifted full meshes shared by QE and Wannier90.

Coordinates follow the Wannier90 kmesh utility: x outermost, z fastest.
This module and its command-line entry point require only the standard library.
"""
import argparse
import math


def validate_grid(grid):
    """Return three positive integer dimensions; shifted meshes are unsupported."""
    try:
        dimensions = tuple(grid)
    except TypeError as exc:
        raise ValueError('grid requires three positive integers') from exc
    if len(dimensions) != 3 or any(type(n) is not int or n <= 0 for n in dimensions):
        raise ValueError('grid requires three positive integers, with no shifts')
    return dimensions


def generate_mesh(grid):
    """Return all fractional reciprocal coordinates in deterministic order."""
    nx, ny, nz = validate_grid(grid)
    return [(i / nx, j / ny, k / nz)
            for i in range(nx) for j in range(ny) for k in range(nz)]


def format_qe(grid):
    """Format a complete QE K_POINTS crystal card with normalized weights."""
    dimensions = validate_grid(grid)
    count = math.prod(dimensions)
    rows = ['K_POINTS crystal', str(count)]
    rows.extend(' '.join(f'{x:.14f}' for x in (*point, 1 / count))
                for point in generate_mesh(dimensions))
    return '\n'.join(rows) + '\n'


def format_wannier(grid):
    """Format three-column rows for a Wannier90 kpoints block."""
    return ''.join(' '.join(f'{x:.14f}' for x in point) + '\n'
                   for point in generate_mesh(grid))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dimensions', nargs=3, type=int, metavar='N')
    parser.add_argument('--format', choices=('qe', 'wannier'), default='qe')
    args = parser.parse_args(argv)
    try:
        output = format_qe(args.dimensions) if args.format == 'qe' else format_wannier(args.dimensions)
    except ValueError as exc:
        parser.error(str(exc))
    print(output, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
