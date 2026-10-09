"""Sample SeeK-path phonon branches in the actual SCF reciprocal basis.

MATDYN must consume these as explicit crystalline points, not band endpoints.
Plot consumers must use ``segments`` (inclusive zero-based indices); a single
line through every MATDYN row would join disconnected branches and guards.
"""
from pathlib import Path
import math
import re
import warnings


def _load_cif_structure(cif_file):
    """Read the CIF for verification without idealizing fractional coordinates.

    Formula metadata is optional: the atom loop and the subsequent SCF match
    establish composition. When a formula is supplied, check it explicitly.
    pymatgen otherwise warns for valid label-only Multiwfn CIFs, and silently
    defaults malformed occupancies or drops unrecognized atom labels.
    """
    from pymatgen.core import Composition, Element
    from pymatgen.io.cif import CifFile, CifParser, str2float

    try:
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter('always')
            text = Path(cif_file).read_text()
            raw = CifFile.from_str(text)
            if len(raw.data) != 1:
                raise ValueError('expected exactly one structure data block')
            data = next(iter(raw.data.values())).data
            columns = ('_atom_site_label', '_atom_site_fract_x',
                       '_atom_site_fract_y', '_atom_site_fract_z')
            if any(not isinstance(data.get(key), list) or not data[key] for key in columns):
                raise ValueError('missing or invalid atomic coordinate loop')
            count = len(data['_atom_site_label'])
            for key in (*columns, '_atom_site_type_symbol', '_atom_site_occupancy'):
                if key in data and (not isinstance(data[key], list) or len(data[key]) != count):
                    raise ValueError(f'inconsistent atomic loop column {key}')
            for index in range(count):
                symbol = data.get('_atom_site_type_symbol', data['_atom_site_label'])[index]
                # Standard CIF labels may suffix an element with a site index
                # or separator; arbitrary labels require an explicit type.
                match = re.fullmatch(r'([A-Z][a-z]?)(?:[0-9_+\-].*)?', symbol)
                if match is None or not Element.is_valid_symbol(match[1]):
                    raise ValueError(f'invalid element or atom label {symbol!r}')
                coords = [str2float(data[key][index]) for key in columns[1:]]
                if not all(math.isfinite(value) for value in coords):
                    raise ValueError(f'nonfinite atom coordinates at row {index + 1}')
                if '_atom_site_occupancy' in data:
                    occupancy = str2float(data['_atom_site_occupancy'][index])
                    if not math.isfinite(occupancy) or occupancy != 1:
                        raise ValueError('SCF verification requires full, finite CIF site occupancies of 1')
            parser = CifParser.from_str(text, frac_tolerance=0, check_cif=False)
            parsed_data = next(iter(parser.as_dict().values()))
            coordinates_unchanged = all(
                len(data[key]) == len(parsed_data.get(key, [])) and
                all(str2float(before) == str2float(after)
                    for before, after in zip(data[key], parsed_data[key]))
                for key in columns[1:])
            structures = parser.parse_structures(primitive=False, check_occu=True, on_error='raise')
            if len(structures) != 1 or not structures[0].is_ordered:
                raise ValueError('expected one fully occupied, ordered CIF structure')
            source = structures[0]
            if not coordinates_unchanged:
                raise ValueError('CIF parser changed fractional coordinates despite disabled rounding')
            actual = source.composition.element_composition.fractional_composition.get_el_amt_dict()
            for key in ('_chemical_formula_sum', '_chemical_formula_structural'):
                if key in data and data[key] not in ('?', '.'):
                    expected = Composition(data[key], strict=True).element_composition.fractional_composition.get_el_amt_dict()
                    if set(expected) != set(actual):
                        raise ValueError(f'CIF formula {key} disagrees with atom-loop composition')
                    # Allow rounded formula metadata, but compare normalized
                    # fractions so multiplying a formula cannot hide an error.
                    if any(not math.isclose(expected[element], actual[element],
                                            rel_tol=parser.comp_tol, abs_tol=1e-8)
                           for element in expected):
                        raise ValueError(f'CIF formula {key} disagrees with atom-loop composition')
        diagnostics = [str(item.message) for item in emitted] + parser.warnings
        benign_diagnostics = set()
        symop_keys = ('_symmetry_equiv_pos_as_xyz', '_symmetry_equiv_pos_as_xyz_',
                      '_space_group_symop_operation_xyz', '_space_group_symop_operation_xyz_')
        from pymatgen.core.operations import SymmOp
        for key in symop_keys:
            if isinstance(data.get(key), str):
                try:
                    operation = SymmOp.from_xyz_str(data[key])
                except ValueError:
                    continue
                if (operation.rotation_matrix.tolist() == [[1,0,0],[0,1,0],[0,0,1]] and
                        all(abs(value-round(value)) < 1e-12 for value in operation.translation_vector)):
                    benign_diagnostics.add('A 1-line symmetry op P1 CIF is detected!')
        # A successful derivation from an explicit space-group name is normal.
        # Do not accept fallback after a present but invalid symop definition.
        if not any(data.get(key) not in (None, '?', '.') for key in symop_keys):
            for key in data:
                if (key.startswith('_symmetry_space_group_name_') or
                        key.rstrip('_') in ('_space_group_name_Hall', '_space_group_name_H-M_alt')):
                    if data[key] not in ('?', '.'):
                        benign_diagnostics.add(
                            f'No _symmetry_equiv_pos_as_xyz type key found. Spacegroup from {key} used.')
        # pymatgen reports "rounded" even when an exact 1/3 or 2/3 is written
        # back unchanged at tolerance zero. Ignore only this proven no-op.
        diagnostics = [message for message in diagnostics if message not in benign_diagnostics and not (
            coordinates_unchanged and re.fullmatch(
                r'\d+ fractional coordinates rounded to ideal values to avoid issues with finite precision\.',
                message))]
        if diagnostics:
            raise ValueError('CIF parsing diagnostic: ' + '; '.join(dict.fromkeys(diagnostics)))
        return source
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'CIF verification failed: {exc}') from exc


def _check_cif(scf, cif_file):
    """Verify structural equivalence without ever adopting the CIF cell."""
    try:
        from pymatgen.core import Structure
        from pymatgen.analysis.structure_matcher import StructureMatcher
        from ase.io.espresso import label_to_symbol
    except ImportError as exc:
        raise ValueError('CIF verification requires the optional pymatgen and ASE structure dependencies') from exc
    source = _load_cif_structure(cif_file)
    source.remove_oxidation_states()
    target = Structure(scf.cell, [label_to_symbol(label) for label, _ in scf.atoms],
                       [position for _, position in scf.atoms])
    matcher = StructureMatcher(ltol=1e-5, stol=1e-4, angle_tol=.001,
                               primitive_cell=False, scale=False, attempt_supercell=False)
    if len(source) != len(target) or not matcher.fit(source, target):
        raise ValueError('CIF and SCF structures do not match: use the actual SCF cell/atoms or omit the CIF')


def generate_phonon_path(scf_file: str | Path, cif_file: str | Path | None = None,
                        *, dimension: int = 3, periodic_axis: int = 3,
                        points_per_segment: int = 20) -> dict:
    """Generate a JSON-safe explicit q path and the metadata needed to plot it.

    ``points_per_segment`` includes both endpoints; an extra interior sample
    is inserted if necessary to disambiguate a folded Gamma limit. Segments retain independent
    endpoints, including repeated Gamma at a turn. ``guard_indices`` are extra
    MATDYN rows that isolate a starting Gamma from an unrelated prior branch;
    they are excluded from all plotted segments. Distances are in inverse
    Angstrom and do not accumulate across a discontinuity (guards are None).

    In 2D, ``periodic_axis`` is the one-based *nonperiodic* cell-vector index,
    shared with phonon settings. Only SeeK-path segments entirely in that
    reciprocal plane are retained. A tilted vacuum vector or insufficient
    in-plane path is rejected rather than projected into a made-up path.
    Dimension is explicit; vacuum length never implicitly selects 2D.

    In 1D, ``periodic_axis`` is the one-based periodic cell-vector index. The
    path is Gamma to 0.5 along that reciprocal axis in the actual SCF first BZ,
    with all other components zero. Its Cartesian alignment is checked for
    compatibility with QE one-dim ASR. A longitudinal supercell folds the
    primitive phonons into this smaller SCF Brillouin zone.

    In 2D/3D supercells this is the associated primitive-cell path expressed in the
    SCF reciprocal basis; the labels do not describe the supercell first BZ.
    """
    if type(dimension) is not int or dimension not in (1, 2, 3):
        raise ValueError('automatic phonon paths support dimension=1, dimension=2 or dimension=3')
    if type(periodic_axis) is not int or periodic_axis not in (1, 2, 3):
        raise ValueError('periodic_axis must be a one-based axis index (1, 2 or 3)')
    if type(points_per_segment) is not int or points_per_segment < 2:
        raise ValueError('points_per_segment must be an integer of at least 2')
    try:
        import numpy as np
        import seekpath
    except ImportError as exc:
        raise ValueError('automatic phonon paths require the optional numpy and seekpath dependencies') from exc
    from qbox.io.phonon_inputs import load_scf
    scf = load_scf(scf_file)
    if not scf.cell or not scf.atoms:
        raise ValueError('SCF input must define a complete cell and atomic positions')
    if cif_file is not None:
        _check_cif(scf, cif_file)
    cell = np.asarray(scf.cell, dtype=float)
    # QE Modules/cell_base.f90 chooses the supplied alat, or the length of
    # the first vector for explicit bohr/angstrom CELL_PARAMETERS.
    from qbox.io.qe_lattice import BOHR_ANGSTROM
    alat = scf.get('system','a')
    if alat is None:
        celldm = scf.get('system','celldm(1)')
        alat = float(celldm)*BOHR_ANGSTROM if celldm is not None else float(np.linalg.norm(cell[0]))
    coordinates = np.asarray([position for _, position in scf.atoms], dtype=float)
    labels = [label for label, _ in scf.atoms]
    types = {label:index+1 for index,label in enumerate(dict.fromkeys(labels))}
    magnetic = (scf.get('system','nspin',1) != 1 or scf.get('system','noncolin',False)
                or scf.get('system','lspinorb',False))
    notes = []
    if dimension == 1:
        axis = periodic_axis-1
        row = cell[axis]
        if any(abs(row[i])>1e-8*np.linalg.norm(row) for i in range(3) if i!=axis):
            raise ValueError('1D periodic vector must align with its corresponding Cartesian axis for one-dim ASR')
        if any(abs(np.dot(row,cell[i]))>1e-8*np.linalg.norm(row)*np.linalg.norm(cell[i])
               for i in range(3) if i!=axis):
            raise ValueError('1D periodic vector must be perpendicular (orthogonal) to the nonperiodic cell vectors')
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter('ignore', DeprecationWarning)
        data = seekpath.get_path_orig_cell((cell, coordinates, [types[label] for label in labels]),
                                          with_time_reversal=not magnetic)
    notes.extend(str(item.message) for item in emitted
                 if dimension != 1 or not issubclass(item.category,seekpath.SupercellWarning))
    if magnetic:
        notes.append('Geometric symmetry is not magnetic symmetry; distinct QE species are retained and time reversal is disabled.')
    if data.get('is_supercell') and dimension != 1:
        notes.append('Supercell: the associated primitive-cell path is expressed in the SCF reciprocal basis; labels are not supercell first-BZ labels.')
    point_coords = {label:np.asarray(point,dtype=float) for label,point in data['point_coords'].items()}
    for point in point_coords.values():
        point[np.abs(point)<1e-10] = 0.
    paths = list(data['path'])
    if dimension == 1:
        # The path is determined by the declared 1D periodicity, independently
        # of SeeK-path's 3D branches. Its supercell flag is diagnostic only.
        endpoint = np.zeros(3)
        endpoint[periodic_axis-1] = .5
        boundary_label = ('X','Y','Z')[periodic_axis-1]
        point_coords = {'GAMMA':np.zeros(3),boundary_label:endpoint}
        paths = [('GAMMA',boundary_label)]
        notes.append(f'1D path: Gamma to q{periodic_axis}=0.5 uses the actual SCF first Brillouin zone; a longitudinal supercell folds phonons into this smaller zone.')
    elif dimension == 2:
        axis = periodic_axis-1
        for other in range(3):
            if other == axis:
                continue
            cosine = np.dot(cell[axis],cell[other]) / (np.linalg.norm(cell[axis])*np.linalg.norm(cell[other]))
            if abs(cosine)>1e-8:
                raise ValueError('2D nonperiodic cell vector must be perpendicular (orthogonal) to the periodic plane')
        paths = [(a,b) for a,b in paths if abs(point_coords[a][axis])<1e-8 and abs(point_coords[b][axis])<1e-8]
        in_plane = [point_coords[label] for pair in paths for label in pair]
        if not in_plane or np.linalg.matrix_rank(np.asarray(in_plane),tol=1e-8)<2:
            raise ValueError('SeeK-path provides no reliable two-dimensional in-plane path for this SCF cell')
        for pair in paths:
            for label in pair:
                point_coords[label][axis] = 0.
        notes.append(f'2D path: only complete SeeK-path segments in q{periodic_axis}=0 are retained; nonperiodic axis was explicitly selected.')
    if not paths:
        raise ValueError('SeeK-path returned no phonon path segments')
    reciprocal = 2*np.pi*np.linalg.inv(cell).T
    qpoints, output_labels, segments, guards, distances = [], [], [], [], []
    cumulative = 0.

    def append(point, label='', distance=None):
        qpoints.append([float(x) for x in point])
        output_labels.append(label)
        distances.append(None if distance is None else float(distance))

    for start_label,end_label in paths:
        start,end = point_coords[start_label],point_coords[end_label]
        if not np.all(np.isfinite(start)) or not np.all(np.isfinite(end)) or np.allclose(start,end,rtol=0,atol=1e-12):
            raise ValueError('SeeK-path returned invalid or zero-length phonon segments')
        # QE 7.5 matdyn.f90: integer crystal q is Gamma-equivalent, but the
        # forward direction is selected only if the previous Cartesian q is
        # exactly zero. This also matters at folded supercell boundary points.
        if qpoints and np.max(np.abs(start-np.rint(start)))<=1e-6 and qpoints[-1]!=[0.,0.,0.]:
            guards.append(len(qpoints))
            append((0.,0.,0.))
        first = len(qpoints)
        length = np.linalg.norm((end-start)@reciprocal)
        sample = np.linspace(start,end,points_per_segment)
        # If the preceding sample is Gamma, QE chooses a forward difference.
        # Insert an interior sample so the ending Gamma uses its own segment.
        if np.max(np.abs(end-np.rint(end)))<=1e-6 and np.array_equal(sample[-2],np.zeros(3)):
            sample = np.insert(sample,len(sample)-1,(sample[-2]+end)/2,axis=0)
        for index,point in enumerate(sample):
            label = start_label if index==0 else end_label if index==len(sample)-1 else ''
            distance = cumulative + np.linalg.norm((point-start)@reciprocal)
            append(point,label,distance)
        segments.append({'start':first,'end':len(qpoints)-1,'start_label':start_label,'end_label':end_label})
        cumulative += length
    if guards:
        notes.append('Extra Gamma guard rows isolate MATDYN nonanalytic limits. Plot only the segments metadata; do not connect every output row.')
    return {'coordinate_system':'crystal','q_in_cryst_coord':True,'q_in_band_form':False,
            'qpoints':qpoints,'qpoints_matdyn':(np.asarray(qpoints)@np.linalg.inv(cell).T*alat).tolist(),
            'alat_angstrom':float(alat),'labels':output_labels,'segments':segments,
            'breaks':[segment['start'] for segment in segments[1:]],
            'guard_indices':guards,'distances':distances,'warnings':list(dict.fromkeys(notes)),
            'is_supercell':bool(data.get('is_supercell',False)),
            'dimension':dimension,'nonperiodic_axis':periodic_axis if dimension==2 else None,
            'periodic_axis':periodic_axis if dimension==1 else None,
            'points_per_segment':points_per_segment,'cell_angstrom':cell.tolist()}
