"""Real scientific and qbox oracles; bundled Python -I -B, outputs only in work."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import warnings


def require(condition, message):
    if not condition: raise ValueError(message)


def scientific(work, fixtures, expected, record):
    import numpy as np
    from scipy import linalg, integrate, optimize, special, fft, sparse
    for dtype in (np.float32,np.float64,np.complex64,np.complex128):
        a=np.array([[3,1],[1,2]],dtype=dtype)
        b=np.array([9,8],dtype=dtype)
        tolerance=1e-5 if dtype in (np.float32,np.complex64) else 1e-12
        np.testing.assert_allclose(a@a,[[10,5],[5,5]],rtol=tolerance)
        np.testing.assert_allclose(np.linalg.solve(a,b),[2,3],rtol=tolerance)
        np.testing.assert_allclose(linalg.solve(a,b),[2,3],rtol=tolerance)
        np.testing.assert_allclose(linalg.blas.get_blas_funcs('gemm',(a,))(1,a,a),[[10,5],[5,5]],rtol=tolerance)
    require(abs(integrate.quad(lambda x:x*x,0,1)[0]-1/3)<1e-12,'SciPy integrate')
    require(abs(optimize.brentq(lambda x:x*x-2,1,2)-2**0.5)<1e-12,'SciPy optimize')
    require(special.gamma(5)==24,'SciPy special')
    np.testing.assert_allclose(fft.ifft(fft.fft(np.arange(8))),np.arange(8),atol=1e-12)
    np.testing.assert_allclose(sparse.linalg.spsolve(sparse.eye(3,format='csc'),np.ones(3)),np.ones(3))
    record('numpy-scipy','BLAS/LAPACK, four scalar types, integration/optimization/FFT/sparse')

    import matplotlib
    matplotlib.use('Agg',force=True)
    from matplotlib import pyplot as plt
    fig,ax=plt.subplots();ax.plot([0,1,2],[0,1,0]);ax.contour(np.arange(16).reshape(4,4))
    png=work/'plot.png';fig.savefig(png);plt.close(fig)
    data=png.read_bytes()
    require(data[:8]==b'\x89PNG\r\n\x1a\n' and len(data)>1000,'Agg PNG output')
    require(all(struct.unpack('>II',data[16:24])),'PNG dimensions')
    record('matplotlib-agg','PNG signature and positive image dimensions')

    from ase.io import read
    from ase.neighborlist import neighbor_list
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    cif=fixtures/'silicon.cif'
    def check_structure(path):
        atoms=read(str(path))
        with warnings.catch_warnings():
            # convert_basic intentionally emits identity symmetry without an
            # explicit operation loop; accept only that known P1 diagnostic.
            warnings.filterwarnings('ignore',message='No _symmetry_equiv_pos_as_xyz type key found.*',category=UserWarning)
            warnings.filterwarnings('ignore',message='Issues encountered while parsing CIF: No _symmetry_equiv_pos_as_xyz type key found.*',category=UserWarning)
            structure=Structure.from_file(path)
        require(atoms.get_chemical_symbols()==expected['elements'],'ASE elements')
        require(len(structure)==expected['atom_count'],'pymatgen atom count')
        require([str(site.specie) for site in structure]==expected['elements'],'pymatgen elements')
        for value in (atoms.get_volume(),structure.volume):
            require(abs(value-expected['volume'])<expected['absolute_tolerance'],'cell volume')
        np.testing.assert_allclose(atoms.cell.lengths(),expected['cell_lengths'],rtol=0,atol=expected['absolute_tolerance'])
        np.testing.assert_allclose(structure.lattice.abc,expected['cell_lengths'],rtol=0,atol=expected['absolute_tolerance'])
        np.testing.assert_allclose(atoms.get_scaled_positions(),[[0,0,0]],atol=1e-10)
        np.testing.assert_allclose(structure.frac_coords,[[0,0,0]],atol=1e-10)
        return atoms,structure
    atoms,structure=check_structure(cif)
    from pymatgen.util import coord_cython
    np.testing.assert_allclose(coord_cython.pbc_shortest_vectors(structure.lattice,[[0.,0.,0.]],[[0.1,0.,0.]]),[[[0.5,0.,0.]]],atol=1e-12)
    require(SpacegroupAnalyzer(structure).get_space_group_number()==expected['spacegroup'],'pymatgen symmetry')
    require(neighbor_list('d',atoms,5.1).size==6,'ASE periodic neighbors')
    record('ase-pymatgen','fixed Si structure, volume, coordinates, native symmetry and neighbors')

    import seekpath,spglib
    cell=(atoms.cell.tolist(),atoms.get_scaled_positions().tolist(),atoms.numbers.tolist())
    path=seekpath.get_path(cell)
    np.testing.assert_allclose(path['point_coords']['GAMMA'],expected['gamma'],atol=1e-12)
    require([list(p) for p in path['path']]==expected['path_segments'],'seekpath fixed cubic segments')
    for start,end in path['path']:
        require(start in path['point_coords'] and end in path['point_coords'],'seekpath labels')
        require(np.isfinite([path['point_coords'][start],path['point_coords'][end]]).all(),'seekpath coordinates')
    require(spglib.get_symmetry_dataset(cell).number==expected['spacegroup'],'spglib space group')
    record('seekpath-spglib','Gamma, fixed simple cubic path, space group 221')

    from qbox.io import convert_ase,convert_pymatgen,convert_basic,kpath
    for name,module in (('ase',convert_ase),('pymatgen',convert_pymatgen),('basic',convert_basic)):
        directory=work/name;directory.mkdir()
        poscar=directory/'POSCAR'; roundtrip=directory/'roundtrip.cif'
        if name=='ase':
            module.main([str(cif),str(poscar)]);module.main([str(poscar),str(roundtrip)])
        else:
            module.main(['cif2vasp',str(cif),str(poscar)]);module.main(['vasp2cif',str(poscar),str(roundtrip)])
        check_structure(poscar);check_structure(roundtrip)
        record('qbox-convert-'+name,'direct backend CIF → POSCAR → CIF and independent readback')
    # Each loader is called separately before the public CLI, so its fallback
    # cannot conceal a broken ASE/pymatgen backend.
    for loader in (kpath.load_with_ase,kpath.load_with_pymatgen,kpath.load_with_basic_cif):
        loaded=loader(str(cif));np.testing.assert_allclose(loaded[0],atoms.cell,atol=1e-8)
    output=io.StringIO()
    with contextlib.redirect_stdout(output): kpath.main([str(cif),'--points',str(expected['segment_points'])])
    text=output.getvalue();(work/'K_POINTS').write_text(text)
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    require(lines[0]=='K_POINTS {crystal_b}','qbox K_POINTS header')
    require(int(lines[1])==expected['kpath_rows']==len(lines[2:]),'qbox path row count')
    expected_labels=['GAMMA','X','M','GAMMA','R','X','R','M']
    for index,line in enumerate(lines[2:]):
        values,label=line.split('!');x,y,z,count=values.split();label=label.strip()
        require(label==expected_labels[index],'qbox path label')
        np.testing.assert_allclose([float(x),float(y),float(z)],path['point_coords'][label],atol=1e-6)
        require(int(count)==(1 if index in (5,7) else expected['segment_points']),'qbox path interpolation count')
    record('qbox-kpath','fixed header, eight rows, coordinates, labels, segment counts')

    from qbox.postprocess import band_edges
    vbm=work/'VBM.dat';cbm=work/'CBM.dat';output=io.StringIO()
    with contextlib.redirect_stdout(output):
        try: band_edges.main([str(fixtures/'bands.dat.gnu'),'1','2',str(vbm),str(cbm)])
        except SystemExit as exc: require(exc.code==0,'band_edges exit status')
    require(output.getvalue()=='2\n','band count')
    require(vbm.read_text()==expected['vbm_text'],'fixed VBM text')
    require(cbm.read_text()==expected['cbm_text'],'fixed CBM text')
    record('qbox-band-edges','exact two-band VBM/CBM text')

    import orjson,pandas
    require(orjson.loads(orjson.dumps({'v':np.arange(3)},option=orjson.OPT_SERIALIZE_NUMPY))=={'v':[0,1,2]},'orjson native serialization')
    require(pandas.DataFrame({'a':[1,2,3]}).a.sum()==6,'pandas native sum')
    from lxml import etree,objectify
    xml=etree.XML(b'<a><b>2</b></a>')
    require(xml.xpath('string(b)')=='2' and objectify.fromstring(b'<a><b>2</b></a>').b.pyval==2,'lxml XML/objectify')
    style=etree.XML(b'<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:template match="/"><out><xsl:value-of select="a/b"/></out></xsl:template></xsl:stylesheet>')
    require('<out>2</out>' in str(etree.XSLT(style)(xml)),'lxml XSLT')
    schema=etree.XML(b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="a" type="xs:string"/></xs:schema>')
    require(etree.XMLSchema(schema).validate(etree.XML(b'<a>ok</a>')),'lxml XMLSchema')
    require(etree.fromstring(b'<?xml version="1.0" encoding="ISO-8859-1"?><a>caf\xe9</a>').text=='caf\u00e9','lxml encoding')
    require(etree.LIBXML_COMPILED_VERSION==(2,14,6) and etree.LIBXSLT_COMPILED_VERSION==(1,1,43),'lxml pinned static dependencies')
    from PIL import Image
    buf=io.BytesIO();Image.new('RGB',(10,10)).save(buf,format='PNG');buf.seek(0)
    require(Image.open(buf).size==(10,10),'Pillow native PNG')
    import contourpy,kiwisolver
    require(len(contourpy.contour_generator(z=[[0,1],[0,1]]).lines(0.5))==1,'contourpy')
    variable=kiwisolver.Variable('x');solver=kiwisolver.Solver();solver.addConstraint(variable==2);solver.updateVariables()
    require(variable.value()==2,'kiwisolver')
    from fontTools.misc.bezierTools import solveQuadratic
    require(sorted(solveQuadratic(1,-3,2))==[1,2],'fonttools native bezier roots')
    import charset_normalizer
    require(str(charset_normalizer.from_bytes(b'qbox').best())=='qbox','charset_normalizer')
    record('native-components','orjson/pandas/lxml/Pillow/contourpy/kiwisolver/fonttools/charset-normalizer native operations')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True,type=Path)
    parser.add_argument('--work',required=True,type=Path)
    args=parser.parse_args(argv)
    report={'schema_version':1,'release_id':None,'manifest_sha256':None,'phase':'smoke','checks':[]}
    def record(name,detail): report['checks'].append({'name':name,'status':'passed','detail':detail})
    try:
        root=args.release.resolve(strict=True);work=args.work.resolve()
        require(not work.is_relative_to(root),'work must be outside release')
        require(not work.exists() or not any(work.iterdir()),'work must be a dedicated empty directory')
        work.mkdir(parents=True,exist_ok=True)
        manifest_path=root/'metadata/manifest.json';manifest=json.loads(manifest_path.read_bytes())
        report.update(release_id=manifest['release_id'],manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest())
        spec=importlib.util.spec_from_file_location('qbox_verify',Path(__file__).with_name('verify.py'))
        verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
        verify.verify_interpreter(root,manifest)
        require(not os.environ.get('DISPLAY'),'DISPLAY must be unset for headless smoke')
        os.environ.update(MPLCONFIGDIR=str(work/'matplotlib'),XDG_CACHE_HOME=str(work/'cache'),MPLBACKEND='Agg')
        record('isolation',{'executable':sys.executable,'sys_path':sys.path,'isolated':sys.flags.isolated,'bytecode_disabled':sys.dont_write_bytecode})
        fixtures=Path(__file__).resolve().parent/'fixtures'
        scientific(work,fixtures,json.loads((fixtures/'expected.json').read_bytes()),record)
    except BaseException as exc:
        report['checks'].append({'name':'smoke','status':'failed','detail':str(exc)})
        print(json.dumps(report,sort_keys=True));return 1
    print(json.dumps(report,sort_keys=True));return 0


if __name__=='__main__': raise SystemExit(main())
