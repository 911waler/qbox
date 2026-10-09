"""QE 7.x lattice conventions, without standardizing or rotating the cell.

Definitions follow https://www.quantum-espresso.org/Doc/INPUT_PW.html#ibrav
and QE Modules/latgen.f90. Vectors are returned as rows in Angstrom.
"""
import math

BOHR_ANGSTROM = 0.529177210903


def _number(value, name):
    try:
        result = float(str(value).replace('D', 'e').replace('d', 'e'))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be a finite number') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number')
    return result


def build_cell(namelists, cell_rows=None, cell_unit=None):
    """Return the actual QE cell, supporting all documented integer ibrav.

    For ibrav=0, ``cell_rows`` must contain the three CELL_PARAMETERS rows
    and ``cell_unit`` must be angstrom, bohr, or alat. Both celldm and A/B/C
    parameter families in the same input are rejected as ambiguous.
    """
    system = {str(key).lower().replace(' ', ''): value
              for key, value in namelists.get('system', {}).items()}
    ibrav = system.get('ibrav', 0)
    if type(ibrav) is not int or ibrav not in {0,1,2,3,-3,4,5,-5,6,7,8,9,-9,91,10,11,12,-12,13,-13,14}:
        raise ValueError('unsupported QE ibrav')
    using_celldm = any(key.startswith('celldm(') for key in system)
    if using_celldm and any(key in system for key in ('a','b','c','cosab','cosac','cosbc')):
        raise ValueError('use either celldm or A/B/C/cos parameters, not both')

    def required(key, positive=False):
        if key not in system:
            raise ValueError(f'ibrav={ibrav} requires {key}')
        value = _number(system[key], key)
        if positive and value <= 0:
            raise ValueError(f'{key} must be positive')
        return value

    def angle(index, key):
        value = required(f'celldm({index})' if using_celldm else key)
        if not -1 < value < 1:
            raise ValueError(f'{key} cosine must lie strictly between -1 and 1')
        return value

    scale_key = 'celldm(1)' if using_celldm else 'a'
    a = required(scale_key, True) * (BOHR_ANGSTROM if using_celldm else 1) if scale_key in system else None
    if ibrav == 0:
        unit = (cell_unit or '').strip().lower().strip('{}()').strip()
        if unit not in ('angstrom','bohr','alat'):
            raise ValueError('CELL_PARAMETERS requires explicit angstrom, bohr or alat units')
        if unit in ('angstrom','bohr') and a is not None:
            raise ValueError('CELL_PARAMETERS angstrom/bohr with A or celldm(1) specifies the lattice parameter twice')
        if unit == 'alat' and a is None:
            raise ValueError('CELL_PARAMETERS alat requires A or celldm(1)')
        scale = {'angstrom':1., 'bohr':BOHR_ANGSTROM, 'alat':a}[unit]
        try:
            if len(cell_rows) != 3 or any(len(row) != 3 for row in cell_rows):
                raise ValueError('CELL_PARAMETERS requires three rows of three numbers')
            cell = [[_number(x, 'CELL_PARAMETERS') * scale for x in row] for row in cell_rows]
        except TypeError as exc:
            raise ValueError('CELL_PARAMETERS requires three rows of three numbers') from exc
    else:
        if cell_rows is not None and len(cell_rows):
            raise ValueError('CELL_PARAMETERS conflicts with nonzero ibrav')
        if a is None:
            raise ValueError('nonzero ibrav requires A or celldm(1)')
        b, c = a, a
        if ibrav in (8,9,-9,91,10,11,12,-12,13,-13,14):
            b = required('celldm(2)' if using_celldm else 'b', True) * (a if using_celldm else 1)
        if ibrav in (4,6,7,8,9,-9,91,10,11,12,-12,13,-13,14):
            c = required('celldm(3)' if using_celldm else 'c', True) * (a if using_celldm else 1)
        h, k, l = a/2, b/2, c/2
        if ibrav in (1,6,8):
            cell = ((a,0,0),(0,b,0),(0,0,c))
        elif ibrav == 2:
            cell = ((-h,0,h),(0,h,h),(-h,h,0))
        elif ibrav in (3,11):
            cell = ((h,k,l),(-h,k,l),(-h,-k,l))
        elif ibrav == -3:
            cell = ((-h,h,h),(h,-h,h),(h,h,-h))
        elif ibrav == 4:
            cell = ((a,0,0),(-h,math.sqrt(3)*h,0),(0,0,c))
        elif abs(ibrav) == 5:
            cosine = angle(4, 'cosab')
            if cosine <= -.5:
                raise ValueError('rhombohedral cosine must exceed -0.5')
            tx, ty, tz = math.sqrt((1-cosine)/2), math.sqrt((1-cosine)/6), math.sqrt((1+2*cosine)/3)
            if ibrav == 5:
                cell = ((a*tx,-a*ty,a*tz),(0,2*a*ty,a*tz),(-a*tx,-a*ty,a*tz))
            else:
                u = a/math.sqrt(3) * (tz-2*math.sqrt(2)*ty)
                v = a/math.sqrt(3) * (tz+math.sqrt(2)*ty)
                cell = ((u,v,v),(v,u,v),(v,v,u))
        elif ibrav == 7:
            cell = ((h,-h,l),(h,h,l),(-h,-h,l))
        elif ibrav == 9:
            cell = ((h,k,0),(-h,k,0),(0,0,c))
        elif ibrav == -9:
            cell = ((h,-k,0),(h,k,0),(0,0,c))
        elif ibrav == 91:
            cell = ((a,0,0),(0,k,-l),(0,k,l))
        elif ibrav == 10:
            cell = ((h,0,l),(h,k,0),(0,k,l))
        elif ibrav in (12,13):
            cosine = angle(4, 'cosab')
            y = b*math.sqrt(1-cosine*cosine)
            cell = ((a,0,0),(b*cosine,y,0),(0,0,c)) if ibrav == 12 else ((h,0,-l),(b*cosine,y,0),(h,0,l))
        elif ibrav in (-12,-13):
            cosine = angle(5, 'cosac')
            z = c*math.sqrt(1-cosine*cosine)
            cell = ((a,0,0),(0,b,0),(c*cosine,0,z)) if ibrav == -12 else ((h,k,0),(-h,k,0),(c*cosine,0,z))
        else:  # triclinic, celldm order is bc, ac, ab
            ca, cb, cg = angle(4,'cosbc'), angle(5,'cosac'), angle(6,'cosab')
            sin_gamma = math.sqrt(1-cg*cg)
            determinant = 1+2*ca*cb*cg-ca*ca-cb*cb-cg*cg
            if determinant <= 0:
                raise ValueError('triclinic angles do not define a positive-volume cell')
            cell = ((a,0,0),(b*cg,b*sin_gamma,0),
                    (c*cb,c*(ca-cb*cg)/sin_gamma,c*math.sqrt(determinant)/sin_gamma))
    x,y,z = cell
    volume = x[0]*(y[1]*z[2]-y[2]*z[1])-x[1]*(y[0]*z[2]-y[2]*z[0])+x[2]*(y[0]*z[1]-y[1]*z[0])
    if abs(volume) < 1e-12:
        raise ValueError('QE cell is singular')
    return tuple(tuple(float(value) for value in row) for row in cell)
